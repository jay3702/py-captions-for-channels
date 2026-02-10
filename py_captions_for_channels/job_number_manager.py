"""Job number manager for tracking job sequence numbers.

Provides incrementing job numbers that reset at midnight for easy reference.
"""

import threading
from datetime import datetime, timezone


class JobNumberManager:
    """Manages sequential job numbers that reset at midnight.

    Thread-safe incrementing job numbers starting from 1.
    Automatically resets to 1 at midnight (UTC).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = 0
        self._current_date = None
        self._reset_if_new_day()

    def _reset_if_new_day(self):
        """Reset counter if we've crossed into a new day."""
        today = datetime.now(timezone.utc).date()
        if self._current_date != today:
            self._counter = 0
            self._current_date = today

    def get_next(self) -> int:
        """Get the next job number.

        Returns:
            Next sequential job number (1-indexed)
        """
        with self._lock:
            self._reset_if_new_day()
            self._counter += 1
            return self._counter

    def get_current(self) -> int:
        """Get the current job number without incrementing.

        Returns:
            Current job number (0 if no jobs yet today)
        """
        with self._lock:
            self._reset_if_new_day()
            return self._counter


# Global singleton instance
_job_number_manager = JobNumberManager()


def get_job_number_manager() -> JobNumberManager:
    """Get the global job number manager instance."""
    return _job_number_manager
