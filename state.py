import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from config import ALL_LIMBS, DEFAULT_ANGLES_DEG


@dataclass
class DeviceSample:
    device_id: str
    pitch_rad: float
    last_seen: float


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

    def update_device_sample(self, device_id: str, pitch_rad: float):
        with self.lock:
            self.latest_by_device[device_id] = DeviceSample(
                device_id=device_id,
                pitch_rad=pitch_rad,
                last_seen=time.time(),
            )

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