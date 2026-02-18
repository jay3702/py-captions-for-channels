"""Job number manager for tracking job sequence numbers.

Provides incrementing job numbers that reset at midnight for easy reference.
Midnight is determined by the configured server timezone, not UTC.
"""

import os
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class JobNumberManager:
    """Manages sequential job numbers that reset at midnight.

    Thread-safe incrementing job numbers starting from 1.
    Automatically resets to 1 at midnight in the configured server timezone.
    """

    def __init__(self, server_tz: ZoneInfo | None = None):
        """Initialize job number manager.
        
        Args:
            server_tz: Timezone to use for "today" calculations. If None, uses UTC.
        """
        self._lock = threading.Lock()
        self._counter = 0
        self._current_date = None
        self._server_tz = server_tz or timezone.utc
        self._reset_if_new_day()

    def _reset_if_new_day(self):
        """Reset counter if we've crossed into a new day (in server timezone)."""
        today = datetime.now(self._server_tz).date()
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
# Initialize with server timezone from environment
def _get_server_tz() -> ZoneInfo | timezone:
    """Get server timezone from environment or fall back to UTC."""
    tz_name = os.getenv("SERVER_TZ") or os.getenv("TZ")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            # Invalid timezone name, fall back to UTC
            pass
    return timezone.utc


_job_number_manager = JobNumberManager(server_tz=_get_server_tz())


def get_job_number_manager() -> JobNumberManager:
    """Get the global job number manager instance."""
    return _job_number_manager
