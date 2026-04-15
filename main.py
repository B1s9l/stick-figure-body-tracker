import argparse
import threading

from config import FILTER_INTERVAL_SEC
from heart_rate import start_heart_rate_thread
from replay_visualizer import run_replay_visualizer
from server import run_server
from state import AppState
from visualizer import run_visualizer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true", help="Run replay visualizer from log files")
    parser.add_argument("--log-file", default="", help="Optional log file path to preload in replay mode")
    args = parser.parse_args()

    if args.replay:
        run_replay_visualizer(args.log_file)
        return

    app_state = AppState()

    flask_thread = threading.Thread(target=run_server, args=(app_state,), daemon=True)
    flask_thread.start()

    start_heart_rate_thread(app_state)

    run_visualizer(app_state, FILTER_INTERVAL_SEC)


if __name__ == "__main__":
    main()