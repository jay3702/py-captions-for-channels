"""
Configuration settings for py-captions-for-channels.

All settings can be overridden via environment variables or .env file.
See .env.example for all available options.
"""

import os
from pathlib import Path


def get_env_bool(key: str, default: bool) -> bool:
    """Get boolean from environment variable."""
    value = os.getenv(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def get_env_int(key: str, default: int) -> int:
    """Get integer from environment variable."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# Load .env file if it exists (for local development)
def load_dotenv():
    """Load environment variables from .env file if it exists."""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if key not in os.environ:
                        os.environ[key] = value


load_dotenv()

# ChannelWatch WebSocket endpoint (usually not needed - webhooks preferred)
CHANNELWATCH_URL = os.getenv("CHANNELWATCH_URL", "ws://localhost:8501/events")

# Channels DVR API endpoint
CHANNELS_API_URL = os.getenv("CHANNELS_API_URL", "http://localhost:8089")

# Caption command to run (whisper or other captioning tool)
CAPTION_COMMAND = os.getenv("CAPTION_COMMAND", 'echo "Would process: {path}"')

# State file for tracking last processed timestamp
STATE_FILE = os.getenv("STATE_FILE", "./data/state.json")

# Channels DVR log path (for log-based source, if implemented)
LOG_PATH = os.getenv("LOG_PATH", "/var/log/channels-dvr.log")

# Event source configuration
USE_MOCK = get_env_bool("USE_MOCK", False)
USE_WEBHOOK = get_env_bool("USE_WEBHOOK", True)

# Webhook configuration (when USE_WEBHOOK=True)
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = get_env_int("WEBHOOK_PORT", 9000)

# Pipeline configuration
DRY_RUN = get_env_bool("DRY_RUN", True)
PIPELINE_TIMEOUT = get_env_int("PIPELINE_TIMEOUT", 3600)
STALE_EXECUTION_SECONDS = get_env_int("STALE_EXECUTION_SECONDS", 900)

# Whitelist configuration
WHITELIST_FILE = os.getenv("WHITELIST_FILE", "./whitelist.txt")

# API timeout
API_TIMEOUT = get_env_int("API_TIMEOUT", 10)

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_VERBOSITY = os.getenv("LOG_VERBOSITY", "NORMAL")  # MINIMAL, NORMAL, or VERBOSE
LOG_FILE = os.getenv(
    "LOG_FILE", "./app.log"
)  # Write logs to file (in addition to stdout)

# Logging visuals and stats
LOG_DIVIDER_LENGTH = get_env_int("LOG_DIVIDER_LENGTH", 40)
LOG_DIVIDER_CHAR = os.getenv("LOG_DIVIDER_CHAR", "-")
LOG_STATS_ENABLED = get_env_bool("LOG_STATS_ENABLED", True)

# Validate LOG_VERBOSITY
if LOG_VERBOSITY.upper() not in ("MINIMAL", "NORMAL", "VERBOSE"):
    raise ValueError(
        f"Invalid LOG_VERBOSITY: {LOG_VERBOSITY}. Must be MINIMAL, NORMAL, or VERBOSE"
    )
