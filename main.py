import threading

from config import FILTER_INTERVAL_SEC
from heart_rate import start_heart_rate_thread
from server import run_server
from state import AppState
from visualizer import run_visualizer


def main():
    app_state = AppState()

    flask_thread = threading.Thread(target=run_server, args=(app_state,), daemon=True)
    flask_thread.start()

    start_heart_rate_thread(app_state)

    run_visualizer(app_state, FILTER_INTERVAL_SEC)


if __name__ == "__main__":
    main()