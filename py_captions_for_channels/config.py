"""
Configuration settings for py-captions-for-channels.

Settings can be overridden via environment variables.
"""

import os


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


# ChannelWatch WebSocket endpoint (port 8501, not 8089)
CHANNELWATCH_URL = os.getenv("CHANNELWATCH_URL", "ws://192.168.3.150:8501/events")

# Channels DVR API endpoint
CHANNELS_API_URL = os.getenv("CHANNELS_API_URL", "http://192.168.3.150:8089")

# Caption command to run (whisper or other captioning tool)
CAPTION_COMMAND = os.getenv(
    "CAPTION_COMMAND", "/usr/local/bin/whisper --model medium {path}"
)

# State file for tracking last processed timestamp
STATE_FILE = os.getenv("STATE_FILE", "/var/lib/py-captions/state.json")

# Channels DVR log path (for log-based source, if implemented)
LOG_PATH = os.getenv(
    "LOG_PATH", "/share/CACHEDEV1_DATA/.qpkg/ChannelsDVR/channels-dvr.log"
)

# Event source configuration
USE_MOCK = get_env_bool("USE_MOCK", False)  # Changed default to False for production
USE_WEBHOOK = get_env_bool("USE_WEBHOOK", True)  # Changed default to True

# Webhook configuration (when USE_WEBHOOK=True)
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")  # Listen on all interfaces
WEBHOOK_PORT = get_env_int(
    "WEBHOOK_PORT", 9000
)  # Port for ChannelWatch webhook notifications

# Pipeline configuration
DRY_RUN = get_env_bool(
    "DRY_RUN", True
)  # If True, print commands instead of executing them
