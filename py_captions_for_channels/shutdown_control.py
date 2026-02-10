"""
Global shutdown control for graceful and immediate shutdown.

This module provides a centralized shutdown state that can be accessed
by both the watcher and web API to coordinate application shutdown.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

LOG = logging.getLogger(__name__)


@dataclass
class ShutdownState:
    """Tracks shutdown state and timing."""

    requested: bool = False
    graceful: bool = False
    requested_at: Optional[datetime] = None
    initiated_by: Optional[str] = None


class ShutdownController:
    """Manages application shutdown state."""

    def __init__(self):
        self._state = ShutdownState()
        self._shutdown_event = asyncio.Event()

    def request_immediate_shutdown(self, initiated_by: str = "api"):
        """
        Request immediate shutdown (kill switch).

        Args:
            initiated_by: Who initiated the shutdown (e.g., "api", "signal")
        """
        if self._state.requested:
            LOG.warning("Shutdown already requested, ignoring duplicate request")
            return

        self._state.requested = True
        self._state.graceful = False
        self._state.requested_at = datetime.now(timezone.utc)
        self._state.initiated_by = initiated_by
        self._shutdown_event.set()

        LOG.warning(
            "🛑 IMMEDIATE SHUTDOWN REQUESTED by %s at %s",
            initiated_by,
            self._state.requested_at.isoformat(),
        )

    def request_graceful_shutdown(self, initiated_by: str = "api"):
        """
        Request graceful shutdown (finish current job, then exit).

        Args:
            initiated_by: Who initiated the shutdown (e.g., "api", "signal")
        """
        if self._state.requested:
            LOG.warning("Shutdown already requested, ignoring duplicate request")
            return

        self._state.requested = True
        self._state.graceful = True
        self._state.requested_at = datetime.now(timezone.utc)
        self._state.initiated_by = initiated_by
        self._shutdown_event.set()

        LOG.warning(
            "⏸️  GRACEFUL SHUTDOWN REQUESTED by %s at %s "
            "(will finish current job and exit)",
            initiated_by,
            self._state.requested_at.isoformat(),
        )

    def is_shutdown_requested(self) -> bool:
        """Check if any shutdown has been requested."""
        return self._state.requested

    def is_graceful_shutdown(self) -> bool:
        """Check if graceful shutdown is requested."""
        return self._state.requested and self._state.graceful

    def is_immediate_shutdown(self) -> bool:
        """Check if immediate shutdown is requested."""
        return self._state.requested and not self._state.graceful

    def get_state(self) -> dict:
        """Get current shutdown state as a dict."""
        return {
            "shutdown_requested": self._state.requested,
            "shutdown_graceful": self._state.graceful,
            "shutdown_requested_at": (
                self._state.requested_at.isoformat()
                if self._state.requested_at
                else None
            ),
            "shutdown_initiated_by": self._state.initiated_by,
        }

    async def wait_for_shutdown(self):
        """Wait for shutdown signal (for use in event loops)."""
        await self._shutdown_event.wait()


# Global singleton instance
_shutdown_controller = ShutdownController()


def get_shutdown_controller() -> ShutdownController:
    """Get the global shutdown controller instance."""
    return _shutdown_controller
