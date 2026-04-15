HOST = "0.0.0.0"
PORT = 6000

WINDOW_W = 1300
WINDOW_H = 850
FPS = 60

SHOW_RAW_PACKETS = False

SMOOTHING_ALPHA = 0.10
ANGLE_DEADBAND_DEG = 0.6
FILTER_INTERVAL_SEC = 1.0 / 60.0

PITCH_MIN = -1.5
PITCH_MAX = 1.5

HEAD_RADIUS = 28
TORSO_LEN = 190

SHOULDER_WIDTH = 140
HIP_WIDTH = 90

UPPER_ARM_LEN = 80
FOREARM_LEN = 85

UPPER_LEG_LEN = 110
LOWER_LEG_LEN = 105

BG_COLOR = (28, 30, 36)
TEXT_COLOR = (230, 230, 230)
CONNECTED_COLOR = (120, 255, 120)
DISCONNECTED_COLOR = (220, 90, 90)

DEVICE_TO_LIMB = {
    "iphone_forearm_right": "forearm_right",
    # "iphone_upperarm_right": "upperarm_right",
    # "iphone_upperarm_left": "upperarm_left",
    # "iphone_forearm_left": "forearm_left",
    
    # "iphone_upperleg_right": "upperleg_right",
    # "iphone_lowerleg_right": "lowerleg_right",
    # "iphone_upperleg_left": "upperleg_left",
    # "iphone_lowerleg_left": "lowerleg_left",
}

ALL_LIMBS = [
    "upperarm_right",
    "forearm_right",
    "upperarm_left",
    "forearm_left",
    "upperleg_right",
    "lowerleg_right",
    "upperleg_left",
    "lowerleg_left",
]

DEFAULT_ANGLES_DEG = {
    "upperarm_right": 0.0,
    "forearm_right": 0.0,
    "upperarm_left": 180.0,
    "forearm_left": 180.0,
    "upperleg_right": 90.0,
    "lowerleg_right": 90.0,
    "upperleg_left": 90.0,
    "lowerleg_left": 90.0,
}

LIMB_LENGTHS = {
    "upperarm_right": UPPER_ARM_LEN,
    "forearm_right": FOREARM_LEN,
    "upperarm_left": UPPER_ARM_LEN,
    "forearm_left": FOREARM_LEN,
    "upperleg_right": UPPER_LEG_LEN,
    "lowerleg_right": LOWER_LEG_LEN,
    "upperleg_left": UPPER_LEG_LEN,
    "lowerleg_left": LOWER_LEG_LEN,
}

# Garmin HRM 600
GARMIN_HR_ADDRESS = "80DE3980-B4F9-4B50-1064-8C6FB170344E"
GARMIN_HR_CHAR = "00002a37-0000-1000-8000-00805f9b34fb"
HR_STALE_TIMEOUT_SEC = 4.0