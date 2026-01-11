import json
import os
from datetime import datetime

class StateBackend:
    """
    Tracks last processed timestamp to ensure idempotency.
    Stores state in a JSON file.
    """

    def __init__(self, path: str):
        self.path = path
        self.last_ts = None
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                    self.last_ts = datetime.fromisoformat(data["last_timestamp"])
            except Exception:
                # Corrupt state file? Reset safely.
                self.last_ts = None

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
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"last_timestamp": ts.isoformat()}, f)

        os.replace(tmp, self.path)
        self.last_ts = ts