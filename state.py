import threading
import time
import math
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

from config import (
    ALL_LIMBS,
    DEFAULT_ANGLES_DEG,
    GPS_METRICS_MIN_DT_SEC,
    GPS_METRICS_MAX_DT_SEC,
    GPS_SPEED_EMA_ALPHA,
    GPS_ACCEL_EMA_ALPHA,
)
from logging_runtime import SessionLogger


@dataclass
class DeviceSample:
    device_id: str
    pitch_rad: float
    last_seen: float
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accel_abs_avg: Optional[float] = None


class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.logger = SessionLogger()
        self.recording_active = False
        self.current_log_path: Optional[str] = None

        self.latest_by_device: Dict[str, DeviceSample] = {}
        self.smoothed_angles_deg: Dict[str, float] = {
            limb: DEFAULT_ANGLES_DEG[limb] for limb in ALL_LIMBS
        }

        self.hr_connected: bool = False
        self.hr_bpm: Optional[int] = None
        self.hr_last_seen: float = 0.0
        self.hr_status_text: str = "not connected"

        self.gps_provider_device: Optional[str] = None
        self.gps_simulation_active: bool = False
        self.gps_simulated_coord: Optional[Tuple[float, float]] = None
        self.gps_coordinate_history: List[Tuple[float, float]] = []
        self.markers: List[Dict] = []
        self.gps_last_calc_ts: Optional[float] = None
        self.gps_last_calc_coord: Optional[Tuple[float, float]] = None
        self.gps_speed_mps: Optional[float] = None
        self.gps_accel_mps2: Optional[float] = None

    def _log_event_locked(self, ts: float, event_type: str, payload: Dict):
        if not self.recording_active:
            return

        event = {"ts": ts, "type": event_type}
        event.update(payload)
        self.logger.log_event(event)

    def start_recording(self):
        with self.lock:
            if self.recording_active and self.current_log_path is not None:
                return self.current_log_path

            log_path = self.logger.start()
            self.recording_active = True
            self.current_log_path = log_path
            return log_path

    def stop_recording(self):
        with self.lock:
            if not self.recording_active:
                return
            self.recording_active = False
            self.current_log_path = None

        self.logger.stop()

    def get_recording_status(self):
        with self.lock:
            return {
                "active": self.recording_active,
                "path": self.current_log_path,
            }

    def _reset_gps_metrics_locked(self):
        self.gps_last_calc_ts = None
        self.gps_last_calc_coord = None
        self.gps_speed_mps = None
        self.gps_accel_mps2 = None

    def _current_gps_coords_locked(self):
        if self.gps_simulation_active and self.gps_simulated_coord is not None:
            return self.gps_simulated_coord

        self._update_gps_provider_locked()
        if self.gps_provider_device is None:
            return None

        sample = self.latest_by_device.get(self.gps_provider_device)
        if sample is None or sample.latitude is None or sample.longitude is None:
            if self.gps_coordinate_history:
                return self.gps_coordinate_history[-1]
            return None

        return sample.latitude, sample.longitude

    def _markers_copy_locked(self):
        return [dict(marker) for marker in self.markers]

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)

        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return r * c

    def _update_gps_metrics_locked(self, ts: float, latitude: float, longitude: float):
        if self.gps_last_calc_ts is None or self.gps_last_calc_coord is None:
            self.gps_last_calc_ts = ts
            self.gps_last_calc_coord = (latitude, longitude)
            return

        dt = ts - self.gps_last_calc_ts
        if dt < GPS_METRICS_MIN_DT_SEC:
            # Keep the previous baseline so dt can accumulate across fast updates.
            return

        if dt > GPS_METRICS_MAX_DT_SEC:
            # Gap too large: re-anchor baseline and wait for next valid segment.
            self.gps_last_calc_ts = ts
            self.gps_last_calc_coord = (latitude, longitude)
            return

        prev_lat, prev_lon = self.gps_last_calc_coord
        distance_m = self._haversine_m(prev_lat, prev_lon, latitude, longitude)
        inst_speed_mps = distance_m / max(dt, 1e-6)

        prev_speed = self.gps_speed_mps if self.gps_speed_mps is not None else inst_speed_mps
        smoothed_speed = prev_speed + (inst_speed_mps - prev_speed) * GPS_SPEED_EMA_ALPHA

        inst_accel_mps2 = (smoothed_speed - prev_speed) / max(dt, 1e-6)
        prev_accel = self.gps_accel_mps2 if self.gps_accel_mps2 is not None else inst_accel_mps2
        smoothed_accel = prev_accel + (inst_accel_mps2 - prev_accel) * GPS_ACCEL_EMA_ALPHA

        self.gps_speed_mps = smoothed_speed
        self.gps_accel_mps2 = smoothed_accel
        self.gps_last_calc_ts = ts
        self.gps_last_calc_coord = (latitude, longitude)

    def _update_gps_provider_locked(self):
        if self.gps_simulation_active:
            return

        now = time.time()
        if self.gps_provider_device is not None:
            current = self.latest_by_device.get(self.gps_provider_device)
            if (
                current is not None
                and current.latitude is not None
                and current.longitude is not None
                and (now - current.last_seen) < 2.0
            ):
                return

        self.gps_provider_device = None
        for device_id, sample in self.latest_by_device.items():
            if (
                sample.latitude is not None
                and sample.longitude is not None
                and (now - sample.last_seen) < 2.0
            ):
                self.gps_provider_device = device_id
                return

    def update_device_sample(
        self,
        device_id: str,
        pitch_rad: float,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        accel_abs_avg: Optional[float] = None,
    ):
        with self.lock:
            ts = time.time()
            self.latest_by_device[device_id] = DeviceSample(
                device_id=device_id,
                pitch_rad=pitch_rad,
                last_seen=ts,
                latitude=latitude,
                longitude=longitude,
                accel_abs_avg=accel_abs_avg,
            )

            self._log_event_locked(
                ts,
                "sensor",
                {
                    "device_id": device_id,
                    "pitch_rad": pitch_rad,
                    "latitude": latitude,
                    "longitude": longitude,
                    "accel_abs_avg": accel_abs_avg,
                },
            )

            self._update_gps_provider_locked()

            if (
                not self.gps_simulation_active
                and self.gps_provider_device == device_id
                and latitude is not None
                and longitude is not None
            ):
                coordinate = (latitude, longitude)
                if not self.gps_coordinate_history or self.gps_coordinate_history[-1] != coordinate:
                    self.gps_coordinate_history.append(coordinate)
                self._update_gps_metrics_locked(ts, latitude, longitude)

    def create_marker(self, name: str = "Unlabeled marker"):
        with self.lock:
            ts = time.time()
            coordinates = self._current_gps_coords_locked()
            marker = {
                "ts": ts,
                "type": "marker",
                "marker_id": uuid.uuid4().hex,
                "name": name,
                "latitude": coordinates[0] if coordinates is not None else None,
                "longitude": coordinates[1] if coordinates is not None else None,
            }
            self.markers.append(marker)
            self._log_event_locked(ts, "marker", marker)
            return marker

    def get_markers_copy(self):
        with self.lock:
            return self._markers_copy_locked()

    def start_gps_simulation(self, latitude: float, longitude: float):
        with self.lock:
            self.gps_simulation_active = True
            self.gps_simulated_coord = (latitude, longitude)
            self.gps_provider_device = None
            self.gps_coordinate_history = [self.gps_simulated_coord]
            self._reset_gps_metrics_locked()
            self._update_gps_metrics_locked(time.time(), latitude, longitude)

    def update_simulated_gps(self, latitude: float, longitude: float):
        with self.lock:
            if not self.gps_simulation_active:
                return

            coordinate = (latitude, longitude)
            self.gps_simulated_coord = coordinate

            if not self.gps_coordinate_history or self.gps_coordinate_history[-1] != coordinate:
                self.gps_coordinate_history.append(coordinate)

            self._update_gps_metrics_locked(time.time(), latitude, longitude)

    def stop_gps_simulation(self, clear_history: bool = True):
        with self.lock:
            self.gps_simulation_active = False
            self.gps_simulated_coord = None
            self._reset_gps_metrics_locked()

            if clear_history:
                self.gps_coordinate_history.clear()

    def snapshot_devices(self):
        with self.lock:
            return dict(self.latest_by_device)

    def get_smoothed_angles_copy(self):
        with self.lock:
            return dict(self.smoothed_angles_deg)

    def set_smoothed_angle(self, limb: str, angle_deg: float):
        with self.lock:
            self.smoothed_angles_deg[limb] = angle_deg

    def get_smoothed_angle(self, limb: str) -> float:
        with self.lock:
            return self.smoothed_angles_deg[limb]

    def set_hr_connected(self, connected: bool, status_text: str):
        with self.lock:
            self.hr_connected = connected
            self.hr_status_text = status_text
            if not connected:
                self.hr_last_seen = 0.0

    def update_hr_bpm(self, bpm: int):
        with self.lock:
            now = time.time()
            self.hr_connected = True
            self.hr_bpm = bpm
            self.hr_last_seen = now
            self.hr_status_text = "connected"
            self._log_event_locked(now, "hr", {"bpm": bpm})

    def get_hr_snapshot(self):
        with self.lock:
            return {
                "connected": self.hr_connected,
                "bpm": self.hr_bpm,
                "last_seen": self.hr_last_seen,
                "status_text": self.hr_status_text,
            }

    def get_gps_snapshot(self):
        with self.lock:
            if self.gps_simulation_active and self.gps_simulated_coord is not None:
                latitude, longitude = self.gps_simulated_coord
                return {
                    "provider": "simulation",
                    "latitude": latitude,
                    "longitude": longitude,
                    "history": list(self.gps_coordinate_history),
                    "markers": self._markers_copy_locked(),
                    "speed_mps": self.gps_speed_mps,
                    "speed_kmh": self.gps_speed_mps * 3.6 if self.gps_speed_mps is not None else None,
                    "accel_mps2": self.gps_accel_mps2,
                }

            self._update_gps_provider_locked()

            latitude = None
            longitude = None
            if self.gps_provider_device is not None:
                sample = self.latest_by_device.get(self.gps_provider_device)
                if sample is not None:
                    latitude = sample.latitude
                    longitude = sample.longitude

            return {
                "provider": self.gps_provider_device,
                "latitude": latitude,
                "longitude": longitude,
                "history": list(self.gps_coordinate_history),
                "markers": self._markers_copy_locked(),
                "speed_mps": self.gps_speed_mps,
                "speed_kmh": self.gps_speed_mps * 3.6 if self.gps_speed_mps is not None else None,
                "accel_mps2": self.gps_accel_mps2,
            }

    def clear_gps_history(self):
        with self.lock:
            self.gps_coordinate_history.clear()