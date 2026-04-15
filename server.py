from flask import Flask, request

from config import HOST, PORT, SHOW_RAW_PACKETS
from state import AppState


def to_float(data, key, default=None):
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


def first_float(data, keys):
    for key in keys:
        value = to_float(data, key, None)
        if value is not None:
            return value
    return None


def create_flask_app(app_state: AppState) -> Flask:
    app = Flask(__name__)

    @app.route("/sensor", methods=["POST"])
    def sensor():
        payload = request.json or {}

        if SHOW_RAW_PACKETS:
            print("RAW PACKET:", payload)

        device_id = payload.get("deviceID", "unknown")
        pitch_rad = to_float(payload, "motionPitch", 0.0)
        latitude = to_float(payload, "latitude", None)
        longitude = to_float(payload, "longitude", None)

        if latitude is None:
            latitude = to_float(payload, "locationLatitude", None)
        if longitude is None:
            longitude = to_float(payload, "locationLongitude", None)

        if latitude is None and isinstance(payload.get("location"), dict):
            latitude = to_float(payload["location"], "latitude", None)
        if longitude is None and isinstance(payload.get("location"), dict):
            longitude = to_float(payload["location"], "longitude", None)

        accel_x = first_float(payload, [
            "accelerationX",
            "userAccelerationX",
            "accelX",
            "motionUserAccelerationX",
            "linearAccelerationX",
        ])
        accel_y = first_float(payload, [
            "accelerationY",
            "userAccelerationY",
            "accelY",
            "motionUserAccelerationY",
            "linearAccelerationY",
        ])
        accel_z = first_float(payload, [
            "accelerationZ",
            "userAccelerationZ",
            "accelZ",
            "motionUserAccelerationZ",
            "linearAccelerationZ",
        ])

        if isinstance(payload.get("acceleration"), dict):
            if accel_x is None:
                accel_x = to_float(payload["acceleration"], "x", None)
            if accel_y is None:
                accel_y = to_float(payload["acceleration"], "y", None)
            if accel_z is None:
                accel_z = to_float(payload["acceleration"], "z", None)

        if isinstance(payload.get("accelerometer"), dict):
            if accel_x is None:
                accel_x = to_float(payload["accelerometer"], "x", None)
            if accel_y is None:
                accel_y = to_float(payload["accelerometer"], "y", None)
            if accel_z is None:
                accel_z = to_float(payload["accelerometer"], "z", None)

        if isinstance(payload.get("userAcceleration"), dict):
            if accel_x is None:
                accel_x = to_float(payload["userAcceleration"], "x", None)
            if accel_y is None:
                accel_y = to_float(payload["userAcceleration"], "y", None)
            if accel_z is None:
                accel_z = to_float(payload["userAcceleration"], "z", None)

        if isinstance(payload.get("motionUserAcceleration"), dict):
            if accel_x is None:
                accel_x = to_float(payload["motionUserAcceleration"], "x", None)
            if accel_y is None:
                accel_y = to_float(payload["motionUserAcceleration"], "y", None)
            if accel_z is None:
                accel_z = to_float(payload["motionUserAcceleration"], "z", None)

        accel_abs_avg = None
        if accel_x is not None and accel_y is not None and accel_z is not None:
            accel_abs_avg = (abs(accel_x) + abs(accel_y) + abs(accel_z)) / 3.0

        app_state.update_device_sample(device_id, pitch_rad, latitude, longitude, accel_abs_avg)
        return "ok"

    return app


def run_server(app_state: AppState):
    app = create_flask_app(app_state)
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)