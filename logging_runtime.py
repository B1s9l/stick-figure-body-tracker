import json
import os
import queue
import threading
from pathlib import Path
from typing import Dict, Iterable, Optional

from config import LOG_FILE_EXTENSION, LOG_FILE_PREFIX, LOG_QUEUE_MAXSIZE, LOGS_DIR


class SessionLogger:
    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._current_log_path: Optional[str] = None
        self._queue: Optional[queue.Queue] = None
        self._worker: Optional[threading.Thread] = None
        self._stop_token = object()

    def _ensure_log_dir(self) -> Path:
        root = Path(__file__).resolve().parent
        log_dir = root / LOGS_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def _next_log_index(self, log_dir: Path) -> int:
        max_index = 0
        for path in log_dir.glob(f"{LOG_FILE_PREFIX}*{LOG_FILE_EXTENSION}"):
            stem = path.stem
            if not stem.startswith(LOG_FILE_PREFIX):
                continue
            suffix = stem[len(LOG_FILE_PREFIX):]
            try:
                max_index = max(max_index, int(suffix))
            except ValueError:
                continue
        return max_index + 1

    def _build_log_path(self) -> str:
        log_dir = self._ensure_log_dir()
        next_index = self._next_log_index(log_dir)
        file_name = f"{LOG_FILE_PREFIX}{next_index}{LOG_FILE_EXTENSION}"
        return str(log_dir / file_name)

    def _writer_loop(self, log_path: str, event_queue: queue.Queue):
        with open(log_path, "a", encoding="utf-8") as handle:
            while True:
                item = event_queue.get()
                if item is self._stop_token:
                    break
                handle.write(json.dumps(item, separators=(",", ":"), ensure_ascii=True))
                handle.write("\n")
                handle.flush()

    def start(self) -> str:
        with self._lock:
            if self._active and self._current_log_path is not None:
                return self._current_log_path

            log_path = self._build_log_path()
            event_queue: queue.Queue = queue.Queue(maxsize=LOG_QUEUE_MAXSIZE)
            worker = threading.Thread(
                target=self._writer_loop,
                args=(log_path, event_queue),
                daemon=True,
            )
            worker.start()

            self._queue = event_queue
            self._worker = worker
            self._active = True
            self._current_log_path = log_path
            return log_path

    def stop(self):
        with self._lock:
            if not self._active or self._queue is None or self._worker is None:
                self._active = False
                self._current_log_path = None
                return

            event_queue = self._queue
            worker = self._worker
            event_queue.put(self._stop_token)

            self._queue = None
            self._worker = None
            self._active = False
            self._current_log_path = None

        worker.join(timeout=2.0)

    def log_event(self, event: Dict):
        with self._lock:
            if not self._active or self._queue is None:
                return
            event_queue = self._queue

        try:
            event_queue.put_nowait(event)
        except queue.Full:
            # Drop events if producers temporarily outrun disk writes.
            return

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def current_log_path(self) -> Optional[str]:
        with self._lock:
            return self._current_log_path

    @staticmethod
    def rewrite_jsonl(path: str, events: Iterable[Dict]):
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, separators=(",", ":"), ensure_ascii=True))
                handle.write("\n")

        os.replace(temp_path, path)
