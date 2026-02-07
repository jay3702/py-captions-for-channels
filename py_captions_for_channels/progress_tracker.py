"""Progress tracking for long-running processes with database backend."""

import json
import logging
from pathlib import Path
from typing import Optional
from .database import get_db
from .services.progress_service import ProgressService

LOG = logging.getLogger(__name__)


class ProgressTracker:
    """Track progress of running processes via database (formerly JSON file)."""

    def __init__(self, progress_file: Path):
        """Initialize progress tracker.

        Args:
            progress_file: Path to legacy JSON file (used for migration only)
        """
        self.progress_file = progress_file
        self._migrate_from_json()

    def _get_service(self) -> ProgressService:
        """Get ProgressService with database session."""
        db = next(get_db())
        return ProgressService(db)

    def _migrate_from_json(self):
        """Migrate progress data from JSON to database on first run."""
        if not self.progress_file.exists():
            return

        migration_marker = self.progress_file.parent / ".progress_migrated"
        if migration_marker.exists():
            return  # Already migrated

        try:
            with open(self.progress_file, "r", encoding="utf-8") as f:
                progress_data = json.load(f)

            if progress_data:
                service = self._get_service()
                for job_id, prog_info in progress_data.items():
                    service.update_progress(
                        job_id=job_id,
                        process_type=prog_info.get("process_type", "unknown"),
                        percent=prog_info.get("percent", 0.0),
                        message=prog_info.get("message", ""),
                        details=prog_info.get("details"),
                    )

            # Mark as migrated
            migration_marker.touch()

            # Rename JSON file to preserve it
            backup_path = str(self.progress_file) + ".migrated"
            self.progress_file.rename(backup_path)
            LOG.info("Migrated progress data from JSON to database")

        except Exception as e:
            LOG.debug("Error migrating progress from JSON: %s", e)

    def update_progress(
        self,
        job_id: str,
        process_type: str,
        percent: float,
        message: str = "",
        details: dict = None,
    ):
        """Update progress for a job (now stored in database).

        Args:
            job_id: Job identifier
            process_type: Type of process ("whisper" or "ffmpeg")
            percent: Progress percentage (0-100)
            message: Optional progress message
            details: Optional additional details dict
        """
        try:
            service = self._get_service()
            service.update_progress(job_id, process_type, percent, message, details)
        except Exception as e:
            LOG.debug("Error updating progress for %s: %s", job_id, e)

    def clear_progress(self, job_id: str):
        """Remove progress data for a completed job (now from database).

        Args:
            job_id: Job identifier to remove
        """
        try:
            service = self._get_service()
            service.clear_progress(job_id)
        except Exception as e:
            LOG.debug("Error clearing progress for %s: %s", job_id, e)

    def get_all_progress(self) -> dict:
        """Get all current progress data (now from database).

        Returns:
            Dict mapping job_id to progress info (matches old JSON format)
        """
        try:
            service = self._get_service()
            return service.get_all_progress_dict()
        except Exception as e:
            LOG.debug("Error reading progress: %s", e)
            return {}

    def get_progress(self, job_id: str) -> Optional[dict]:
        """Get progress for a specific job (now from database).

        Args:
            job_id: Job identifier

        Returns:
            Progress dict or None if not found (matches old JSON format)
        """
        try:
            service = self._get_service()
            progress = service.get_progress(job_id)
            return service.to_dict(progress) if progress else None
        except Exception as e:
            LOG.debug("Error getting progress for %s: %s", job_id, e)
            return None


# Global progress tracker instance
_progress_tracker: Optional[ProgressTracker] = None


def get_progress_tracker() -> ProgressTracker:
    """Get the global progress tracker instance."""
    global _progress_tracker
    if _progress_tracker is None:
        progress_file = Path.cwd() / "data" / "progress.json"
        _progress_tracker = ProgressTracker(progress_file)
    return _progress_tracker
