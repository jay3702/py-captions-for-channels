import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime
import json

# Verbosity levels
LOG_LEVELS = {
    "minimal": logging.INFO,
    "medium": logging.DEBUG,
    "verbose": 15,  # Custom level between DEBUG and INFO
    "maximum": 5,  # Custom level below DEBUG
}

logging.addLevelName(15, "VERBOSE")
logging.addLevelName(5, "MAXIMUM")


def verbose(self, message, *args, **kws):
    if self.isEnabledFor(15):
        self._log(15, message, args, **kws)


def maximum(self, message, *args, **kws):
    if self.isEnabledFor(5):
        self._log(5, message, args, **kws)


logging.Logger.verbose = verbose
logging.Logger.maximum = maximum


def get_log_level():
    level = os.environ.get("LOG_VERBOSITY", "minimal").lower()
    return LOG_LEVELS.get(level, logging.INFO)


def get_log_path():
    # Use a relative path for portability and CI compatibility
    return os.environ.get("LOG_PATH", "./logs/pipeline.log")


def get_logger(name="pipeline", job_id=None):
    logger = logging.getLogger(f"{name}.{job_id}" if job_id else name)
    logger.setLevel(get_log_level())
    if not logger.handlers:
        log_path = get_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        formatter = StructuredLogFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        # Also log to stdout for container logs
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    # Attach job_id to all log records if provided
    if job_id is not None:

        def add_job_id(record):
            record.job_id = job_id
            return True

        logger.addFilter(add_job_id)
    return logger


class StructuredLogFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "event": getattr(record, "event", None),
            "msg": record.getMessage(),
        }
        # Add job_id if present
        job_id = getattr(record, "job_id", None)
        if job_id is not None:
            log_entry["job_id"] = job_id
        # Add extra fields if present
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_entry.update(record.extra)
        return json.dumps(log_entry)
