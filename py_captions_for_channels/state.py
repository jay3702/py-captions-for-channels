import json
import os
from datetime import datetime


class StateBackend:
    """
    Tracks last processed timestamp to ensure idempotency.
    Also tracks failed/forced reprocessing requests.
    Stores state in a JSON file.
    """

    def __init__(self, path: str):
        self.path = path
        self.last_ts = None
        self.reprocess_paths = set()  # Paths marked for reprocessing
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                    ts_str = data.get("last_timestamp")
                    if ts_str:
                        self.last_ts = datetime.fromisoformat(ts_str)
                    # Load reprocess queue if it exists
                    self.reprocess_paths = set(data.get("reprocess_paths", []))
            except Exception:
                # Corrupt state file? Reset safely.
                self.last_ts = None
                self.reprocess_paths = set()

    def should_process(self, ts: datetime) -> bool:
        """
        Returns True if this timestamp is newer than the last processed one.
        """
        return self.last_ts is None or ts > self.last_ts

    def update(self, ts: datetime):
        """
        Persist the new timestamp safely using an atomic write.
        Ensures the directory exists before writing.
        """
        self.last_ts = ts  # Update in-memory state
        self._persist_state(ts, self.reprocess_paths)

    def mark_for_reprocess(self, path: str):
        """
        Mark a file path for reprocessing (forced retry).
        """
        self.reprocess_paths.add(path)
        self._persist_state(self.last_ts, self.reprocess_paths)

    def has_reprocess_request(self, path: str) -> bool:
        """
        Check if a path is marked for reprocessing.
        """
        return path in self.reprocess_paths

    def clear_reprocess_request(self, path: str):
        """
        Clear a reprocess request after handling it.
        """
        if path in self.reprocess_paths:
            self.reprocess_paths.discard(path)
            self._persist_state(self.last_ts, self.reprocess_paths)

    def get_reprocess_queue(self) -> list:
        """
        Return list of paths awaiting reprocessing.
        """
        return list(self.reprocess_paths)

    def _persist_state(self, ts: datetime, reprocess_paths: set):
        """
        Persist state safely using an atomic write.
        """
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            data = {
                "last_timestamp": ts.isoformat() if ts else None,
                "reprocess_paths": sorted(list(reprocess_paths)),
            }
            json.dump(data, f)

        os.replace(tmp, self.path)
