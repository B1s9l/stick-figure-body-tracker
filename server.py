from flask import Flask, request

from config import HOST, PORT, SHOW_RAW_PACKETS
from state import AppState


def to_float(data, key, default=None):
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


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

        app_state.update_device_sample(device_id, pitch_rad, latitude, longitude)
        return "ok"

    return app


def run_server(app_state: AppState):
    app = create_flask_app(app_state)
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)