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

        app_state.update_device_sample(device_id, pitch_rad)
        return "ok"

    return app


def run_server(app_state: AppState):
    app = create_flask_app(app_state)
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)