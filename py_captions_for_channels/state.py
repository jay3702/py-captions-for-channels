"""State management for pipeline with database backend for manual queue."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .database import get_db
from .services.manual_queue_service import ManualQueueService


class StateBackend:
    """
    Tracks last processed timestamp to ensure idempotency.
    Also tracks manual processing requests (user-selected recordings).

    State storage:
    - last_ts: Stored in JSON file for backward compatibility
    - manual_process_queue: Migrated to database (ManualQueueItem model)
    """

    def __init__(self, path: str):
        self.path = path
        self.last_ts = None
        self._load()
        self._migrate_manual_queue()

    def _get_service(self) -> ManualQueueService:
        """Get ManualQueueService with database session."""
        db = next(get_db())
        return ManualQueueService(db)

    def _migrate_manual_queue(self):
        """Migrate manual process queue from JSON to database on first run."""
        migration_marker = Path(self.path).parent / ".manual_queue_migrated"

        if migration_marker.exists():
            return  # Already migrated

        # Check if we have data in JSON to migrate
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                    manual_data = data.get(
                        "manual_process_paths", data.get("reprocess_paths", [])
                    )

                    if manual_data:
                        service = self._get_service()

                        # Handle both list (old) and dict (new) formats
                        if isinstance(manual_data, list):
                            for path in manual_data:
                                service.add_to_queue(path)
                        else:
                            for path, settings in manual_data.items():
                                service.add_to_queue(
                                    path,
                                    skip_caption_generation=settings.get(
                                        "skip_caption_generation", False
                                    ),
                                    log_verbosity=settings.get(
                                        "log_verbosity", "NORMAL"
                                    ),
                                )

                        # Mark as migrated
                        migration_marker.touch()

                        # Rename state.json to preserve it
                        backup_path = self.path + ".manual_queue_migrated"
                        if not os.path.exists(backup_path):
                            with open(backup_path, "w") as f:
                                json.dump(data, f, indent=2)
            except Exception:
                pass  # Ignore migration errors

    def _load(self):
        """Load last_ts from JSON file (manual queue now in database)."""
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                    ts_str = data.get("last_timestamp")
                    if ts_str:
                        self.last_ts = datetime.fromisoformat(ts_str)
            except Exception:
                # Corrupt state file? Reset safely.
                self.last_ts = None

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
        self._persist_state(ts)

    def mark_for_manual_process(
        self,
        path: str,
        skip_caption_generation: bool = False,
        log_verbosity: str = "NORMAL",
    ):
        """
        Mark a file path for manual processing with specific settings.
        Now stores in database via ManualQueueService.
        """
        service = self._get_service()
        service.add_to_queue(path, skip_caption_generation, log_verbosity)

    def has_manual_process_request(self, path: str) -> bool:
        """
        Check if a path is marked for manual processing.
        Now checks database via ManualQueueService.
        """
        service = self._get_service()
        return service.has_path(path)

    def get_manual_process_settings(self, path: str) -> dict:
        """
        Get manual process settings for a path.
        Now retrieves from database via ManualQueueService.
        """
        service = self._get_service()
        item = service.get_queue_item(path)
        if item:
            return {
                "skip_caption_generation": item.skip_caption_generation,
                "log_verbosity": item.log_verbosity,
            }
        return {"skip_caption_generation": False, "log_verbosity": "NORMAL"}

    def clear_manual_process_request(self, path: str):
        """
        Clear a manual process request after handling it.
        Now removes from database via ManualQueueService.
        """
        service = self._get_service()
        service.remove_from_queue(path)

    def get_manual_process_queue(self) -> list:
        """
        Return list of paths awaiting manual processing.
        Now retrieves from database via ManualQueueService.
        """
        service = self._get_service()
        return service.get_queue_paths()

    def _persist_state(self, ts: datetime):
        """
        Persist last_ts safely using an atomic write.
        Manual queue is now persisted in database.
        """
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            # Handle ts as both datetime and string
            timestamp_str = None
            if ts:
                timestamp_str = ts if isinstance(ts, str) else ts.isoformat()
            data = {
                "last_timestamp": timestamp_str,
                # manual_process_paths removed - now in database
            }
            json.dump(data, f)

        os.replace(tmp, self.path)
