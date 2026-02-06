"""Progress tracking for long-running processes (Whisper, FFmpeg)."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOG = logging.getLogger(__name__)


class ProgressTracker:
    """Track progress of running processes via JSON file updates."""

    def __init__(self, progress_file: Path):
        """Initialize progress tracker.

        Args:
            progress_file: Path to JSON file for storing progress data
        """
        self.progress_file = progress_file
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)

    def update_progress(
        self,
        job_id: str,
        process_type: str,
        percent: float,
        message: str = "",
        details: dict = None,
    ):
        """Update progress for a job.

        Args:
            job_id: Job identifier
            process_type: Type of process ("whisper" or "ffmpeg")
            percent: Progress percentage (0-100)
            message: Optional progress message
            details: Optional additional details dict
        """
        try:
            # Read existing progress data
            progress_data = {}
            if self.progress_file.exists():
                try:
                    with open(self.progress_file, "r", encoding="utf-8") as f:
                        progress_data = json.load(f)
                except Exception:
                    pass

            # Update progress for this job
            progress_data[job_id] = {
                "process_type": process_type,
                "percent": min(100.0, max(0.0, percent)),
                "message": message,
                "details": details or {},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            # Write back to file
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(progress_data, f, indent=2)

        except Exception as e:
            LOG.debug("Error updating progress for %s: %s", job_id, e)

    def clear_progress(self, job_id: str):
        """Remove progress data for a completed job.

        Args:
            job_id: Job identifier to remove
        """
        try:
            if not self.progress_file.exists():
                return

            with open(self.progress_file, "r", encoding="utf-8") as f:
                progress_data = json.load(f)

            if job_id in progress_data:
                del progress_data[job_id]

                with open(self.progress_file, "w", encoding="utf-8") as f:
                    json.dump(progress_data, f, indent=2)

        except Exception as e:
            LOG.debug("Error clearing progress for %s: %s", job_id, e)

    def get_all_progress(self) -> dict:
        """Get all current progress data.

        Returns:
            Dict mapping job_id to progress info
        """
        try:
            if not self.progress_file.exists():
                return {}

            with open(self.progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            LOG.debug("Error reading progress: %s", e)
            return {}

    def get_progress(self, job_id: str) -> Optional[dict]:
        """Get progress for a specific job.

        Args:
            job_id: Job identifier

        Returns:
            Progress dict or None if not found
        """
        all_progress = self.get_all_progress()
        return all_progress.get(job_id)


# Global progress tracker instance
_progress_tracker: Optional[ProgressTracker] = None


def get_progress_tracker() -> ProgressTracker:
    """Get the global progress tracker instance."""
    global _progress_tracker
    if _progress_tracker is None:
        progress_file = Path.cwd() / "data" / "progress.json"
        _progress_tracker = ProgressTracker(progress_file)
    return _progress_tracker
