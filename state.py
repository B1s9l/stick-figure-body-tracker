import threading
import time
import math
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

        self.latest_by_device: Dict[str, DeviceSample] = {}
        self.smoothed_angles_deg: Dict[str, float] = {
            limb: DEFAULT_ANGLES_DEG[limb] for limb in ALL_LIMBS
        }

        self.hr_connected: bool = False
        self.hr_bpm: Optional[int] = None
        self.hr_last_seen: float = 0.0
        self.hr_status_text: str = "not connected"

        self.gps_provider_device: Optional[str] = None
        self.gps_coordinate_history: List[Tuple[float, float]] = []
        self.gps_last_calc_ts: Optional[float] = None
        self.gps_last_calc_coord: Optional[Tuple[float, float]] = None
        self.gps_speed_mps: Optional[float] = None
        self.gps_accel_mps2: Optional[float] = None

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
        if dt < GPS_METRICS_MIN_DT_SEC or dt > GPS_METRICS_MAX_DT_SEC:
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

            self._update_gps_provider_locked()

            if self.gps_provider_device == device_id and latitude is not None and longitude is not None:
                coordinate = (latitude, longitude)
                if not self.gps_coordinate_history or self.gps_coordinate_history[-1] != coordinate:
                    self.gps_coordinate_history.append(coordinate)
                self._update_gps_metrics_locked(ts, latitude, longitude)

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
            self.hr_connected = True
            self.hr_bpm = bpm
            self.hr_last_seen = time.time()
            self.hr_status_text = "connected"

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
                "speed_mps": self.gps_speed_mps,
                "speed_kmh": self.gps_speed_mps * 3.6 if self.gps_speed_mps is not None else None,
                "accel_mps2": self.gps_accel_mps2,
            }

    def clear_gps_history(self):
        with self.lock:
            self.gps_coordinate_history.clear()