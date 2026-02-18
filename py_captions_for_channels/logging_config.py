"""
Logging configuration for py-captions-for-channels.

Supports:
- Job ID tracking with formatted markers
- Multiple verbosity levels (MINIMAL, NORMAL, VERBOSE)
- Context-aware formatting for processing jobs
- File and console output
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional
from contextvars import ContextVar
from datetime import datetime

# Try to import ZoneInfo (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# Context variable to track current job ID
_job_id_context: ContextVar[Optional[str]] = ContextVar("job_id", default=None)


class JobIDFormatter(logging.Formatter):
    """Custom formatter that includes job ID markers for easy log parsing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get server timezone on initialization
        self._tz = self._get_timezone()

    def _get_timezone(self):
        """Get server timezone from SERVER_TZ env var."""
        tz_name = os.getenv("SERVER_TZ")
        if tz_name and ZoneInfo:
            try:
                return ZoneInfo(tz_name)
            except Exception:
                pass
        # Fallback to local system timezone
        try:
            return datetime.now().astimezone().tzinfo
        except Exception:
            return None

    def formatTime(self, record, datefmt=None):
        """Override formatTime to use server timezone."""
        # Get time in server timezone
        if self._tz:
            dt = datetime.fromtimestamp(record.created, tz=self._tz)
        else:
            dt = datetime.fromtimestamp(record.created).astimezone()

        if datefmt:
            return dt.strftime(datefmt)
        else:
            return dt.isoformat()

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with job ID marker if available."""
        job_id = _job_id_context.get()

        # Create base message
        base_msg = super().format(record)

        # Add job ID prefix if available
        if job_id:
            return f"[{job_id}] {base_msg}"
        return base_msg


class VerbosityFilter(logging.Filter):
    """Filter that controls which records are logged based on verbosity level."""

    def __init__(self, verbosity_level: str):
        """Initialize filter with verbosity level.

        Args:
            verbosity_level: One of 'MINIMAL', 'NORMAL', 'VERBOSE'
        """
        super().__init__()
        self.verbosity_level = verbosity_level.upper()

        # Map verbosity levels to minimum log levels
        # MINIMAL: Only warnings and errors (skip info/debug)
        # NORMAL: Info and above (current behavior)
        # VERBOSE: Debug and above (all messages)
        self.level_map = {
            "MINIMAL": logging.WARNING,
            "NORMAL": logging.INFO,
            "VERBOSE": logging.DEBUG,
        }

        self.min_level = self.level_map.get(self.verbosity_level, logging.INFO)

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter based on verbosity level."""
        return record.levelno >= self.min_level


def set_job_id(job_id: Optional[str]) -> None:
    """Set the current job ID for log formatting.

    Args:
        job_id: Job identifier (e.g., 'CNN News Central @ 22:01:16') or None to clear
    """
    _job_id_context.set(job_id)


def get_job_id() -> Optional[str]:
    """Get the current job ID."""
    return _job_id_context.get()


_current_verbosity: str = "NORMAL"


def configure_logging(
    verbosity: str = "NORMAL", log_file: Optional[str] = None
) -> None:
    """Configure logging with job markers and verbosity levels.

    Args:
        verbosity: One of 'MINIMAL', 'NORMAL', 'VERBOSE'
        log_file: Optional path to write logs to file (in addition to stdout)
    """
    global _current_verbosity
    verbosity = verbosity.upper()
    if verbosity not in ("MINIMAL", "NORMAL", "VERBOSE"):
        raise ValueError(
            f"Invalid verbosity level: {verbosity}. Must be MINIMAL, NORMAL, or VERBOSE"
        )

    # Create formatter with job ID support
    formatter = JobIDFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Create verbosity filter
    verbosity_filter = VerbosityFilter(verbosity)
    _current_verbosity = verbosity

    # Get root logger and configure it
    root_logger = logging.getLogger()
    root_logger.setLevel(
        logging.DEBUG
    )  # Allow all levels through; filter controls output
    root_logger.handlers.clear()  # Remove any existing handlers

    # Always add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(verbosity_filter)
    root_logger.addHandler(console_handler)

    # Add file handler if requested
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(verbosity_filter)
        root_logger.addHandler(file_handler)

    # Suppress SQLAlchemy pool noise (cannot rollback errors)
    # We already handle these in our code with try/except
    sqlalchemy_pool_logger = logging.getLogger("sqlalchemy.pool")
    sqlalchemy_pool_logger.setLevel(logging.CRITICAL)

    # Ensure no duplicate propagation
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.propagate = True
            logger.handlers.clear()


def set_verbosity(verbosity: str) -> None:
    """Update verbosity level on existing handlers."""
    global _current_verbosity
    verbosity = verbosity.upper()
    if verbosity not in ("MINIMAL", "NORMAL", "VERBOSE"):
        raise ValueError(
            f"Invalid verbosity level: {verbosity}. Must be MINIMAL, NORMAL, or VERBOSE"
        )

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        found = False
        for flt in handler.filters:
            if isinstance(flt, VerbosityFilter):
                flt.verbosity_level = verbosity
                flt.min_level = flt.level_map.get(verbosity, logging.INFO)
                found = True
        if not found:
            handler.addFilter(VerbosityFilter(verbosity))

    _current_verbosity = verbosity


def get_verbosity() -> str:
    """Return current logging verbosity."""
    return _current_verbosity


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
