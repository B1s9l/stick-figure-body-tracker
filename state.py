import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

from config import ALL_LIMBS, DEFAULT_ANGLES_DEG


@dataclass
class DeviceSample:
    device_id: str
    pitch_rad: float
    last_seen: float
    latitude: Optional[float] = None
    longitude: Optional[float] = None


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
    ):
        with self.lock:
            self.latest_by_device[device_id] = DeviceSample(
                device_id=device_id,
                pitch_rad=pitch_rad,
                last_seen=time.time(),
                latitude=latitude,
                longitude=longitude,
            )

            self._update_gps_provider_locked()

            if self.gps_provider_device == device_id and latitude is not None and longitude is not None:
                coordinate = (latitude, longitude)
                if not self.gps_coordinate_history or self.gps_coordinate_history[-1] != coordinate:
                    self.gps_coordinate_history.append(coordinate)

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
            }

    def clear_gps_history(self):
        with self.lock:
            self.gps_coordinate_history.clear()