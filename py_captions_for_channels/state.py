import json
import os
from datetime import datetime, timezone


class StateBackend:
    """
    Tracks last processed timestamp to ensure idempotency.
    Also tracks manual processing requests (user-selected recordings).
    Stores state in a JSON file.
    """

    def __init__(self, path: str):
        self.path = path
        self.last_ts = None
        self.manual_process_paths = (
            {}
        )  # Paths marked for manual processing -> {skip_caption_generation, log_verbosity}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                    ts_str = data.get("last_timestamp")
                    if ts_str:
                        self.last_ts = datetime.fromisoformat(ts_str)
                    # Load manual process queue - handle both old (reprocess_paths)
                    # and new (manual_process_paths) naming, and old (list)
                    # and new (dict) formats
                    manual_data = data.get(
                        "manual_process_paths", data.get("reprocess_paths", [])
                    )
                    if isinstance(manual_data, list):
                        # Old format: convert to dict with default settings
                        self.manual_process_paths = {
                            path: {
                                "skip_caption_generation": False,
                                "log_verbosity": "NORMAL",
                            }
                            for path in manual_data
                        }
                    else:
                        # New format: dict
                        self.manual_process_paths = manual_data
            except Exception:
                # Corrupt state file? Reset safely.
                self.last_ts = None
                self.manual_process_paths = {}

    def should_process(self, ts: datetime) -> bool:
        """
        Returns True if this timestamp is newer than the last processed one.
        Ensures both timestamps have timezone info for comparison.
        """
        if self.last_ts is None:
            return True

        # Ensure both timestamps are timezone-aware for comparison
        ts_aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
        last_ts_aware = (
            self.last_ts
            if self.last_ts.tzinfo is not None
            else self.last_ts.replace(tzinfo=timezone.utc)
        )

        return ts_aware > last_ts_aware

    def update(self, ts: datetime):
        """
        Persist the new timestamp safely using an atomic write.
        Ensures the directory exists before writing.
        """
        self.last_ts = ts  # Update in-memory state
        self._persist_state(ts, self.manual_process_paths)

    def mark_for_manual_process(
        self,
        path: str,
        skip_caption_generation: bool = False,
        log_verbosity: str = "NORMAL",
    ):
        """
        Mark a file path for manual processing with specific settings.
        """
        self.manual_process_paths[path] = {
            "skip_caption_generation": skip_caption_generation,
            "log_verbosity": log_verbosity,
        }
        self._persist_state(self.last_ts, self.manual_process_paths)

    def has_manual_process_request(self, path: str) -> bool:
        """
        Check if a path is marked for manual processing.
        """
        return path in self.manual_process_paths

    def get_manual_process_settings(self, path: str) -> dict:
        """
        Get manual process settings for a path.
        """
        return self.manual_process_paths.get(
            path, {"skip_caption_generation": False, "log_verbosity": "NORMAL"}
        )

    def clear_manual_process_request(self, path: str):
        """
        Clear a manual process request after handling it.
        """
        if path in self.manual_process_paths:
            del self.manual_process_paths[path]
            self._persist_state(self.last_ts, self.manual_process_paths)

    def get_manual_process_queue(self) -> list:
        """
        Return list of paths awaiting manual processing.
        """
        return list(self.manual_process_paths.keys())

    def _persist_state(self, ts: datetime, manual_process_paths: dict):
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
                "manual_process_paths": manual_process_paths,
            }
            json.dump(data, f)

        os.replace(tmp, self.path)
