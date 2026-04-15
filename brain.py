from config import (
    DEVICE_TO_LIMB,
    ALL_LIMBS,
    PITCH_MIN,
    PITCH_MAX,
    SMOOTHING_ALPHA,
    ANGLE_DEADBAND_DEG,
)
from state import AppState


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def smooth_value(current: float, target: float, alpha: float) -> float:
    return current + (target - current) * alpha


def get_device_id_for_limb(limb: str):
    for device_id, mapped_limb in DEVICE_TO_LIMB.items():
        if mapped_limb == limb:
            return device_id
    return None


def map_pitch_to_halfcircle_deg(pitch_rad: float) -> float:
    """
    Maps pitch from [-1.5, +1.5] to [0, 180]
    """
    p = clamp(pitch_rad, PITCH_MIN, PITCH_MAX)
    return 60.0 * (p + 1.5)


def map_arm_pitch_to_screen_angle(pitch_rad: float, limb: str) -> float:
    """
    Desired semantic mapping:
      pitch -1.5 -> down
      pitch  0.0 -> horizontal
      pitch +1.5 -> up

    halfcircle:
      -1.5 -> 0
       0.0 -> 90
      +1.5 -> 180

    Convert to screen angles:
      right side: down=90, out=0, up=-90
      left side:  down=90, out=180, up=270
    """
    halfcircle = map_pitch_to_halfcircle_deg(pitch_rad)

    if limb.endswith("_right"):
        return 90.0 - halfcircle
    else:
        return 90.0 + halfcircle


def map_leg_pitch_to_screen_angle(pitch_rad: float, limb: str) -> float:
    """
    Same pitch-only mapping for now:
      -1.5 -> vertical down
       0.0 -> horizontal forward
      +1.5 -> vertical up toward torso

    right side: 90 -> 0 -> -90
    left side:  90 -> 180 -> 270
    """
    halfcircle = map_pitch_to_halfcircle_deg(pitch_rad)

    if limb.endswith("_right"):
        return 90.0 - halfcircle
    else:
        return 90.0 + halfcircle


def compute_target_angle(limb: str, pitch_rad: float) -> float:
    if "arm" in limb or "forearm" in limb:
        return map_arm_pitch_to_screen_angle(pitch_rad, limb)
    if "leg" in limb:
        return map_leg_pitch_to_screen_angle(pitch_rad, limb)
    return 0.0


def update_angles(app_state: AppState):
    snapshot = app_state.snapshot_devices()

    for limb in ALL_LIMBS:
        device_id = get_device_id_for_limb(limb)
        if device_id is None:
            continue

        sample = snapshot.get(device_id)
        if sample is None:
            continue

        target = compute_target_angle(limb, sample.pitch_rad)
        current = app_state.get_smoothed_angle(limb)

        if abs(target - current) < ANGLE_DEADBAND_DEG:
            continue

        new_angle = smooth_value(current, target, SMOOTHING_ALPHA)
        app_state.set_smoothed_angle(limb, new_angle)