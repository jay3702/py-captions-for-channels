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

# =============================================================================
# DATA STORAGE
# =============================================================================
# Base directory for all application data (database, logs, quarantine, state).
# Point this to a volume with ample disk space. The application itself is
# lightweight; this directory is where large files accumulate.
# Individual paths below can still be overridden independently.
DATA_DIR = os.getenv("DATA_DIR", "./data")

# ChannelWatch WebSocket endpoint (usually not needed - webhooks preferred)
CHANNELWATCH_URL = os.getenv("CHANNELWATCH_URL", "ws://localhost:8501/events")

# Channels DVR server base URL
CHANNELS_DVR_URL = os.getenv("CHANNELS_DVR_URL", "http://localhost:8089")

# Full Channels DVR API URL (defaults to DVR URL + /api/v1)
CHANNELS_API_URL = os.getenv(
    "CHANNELS_API_URL", f"{CHANNELS_DVR_URL.rstrip('/')}/api/v1"
)

# DVR recordings storage path (root directory where recordings are stored)
DVR_RECORDINGS_PATH = os.getenv("DVR_RECORDINGS_PATH", "/recordings")

# Local test directory (for development - overrides network DVR path)
# When set, uses local sample files instead of network repository
LOCAL_TEST_DIR = os.getenv("LOCAL_TEST_DIR", None)

# Caption command to run (whisper or other captioning tool)
CAPTION_COMMAND = os.getenv("CAPTION_COMMAND", 'echo "Would process: {path}"')

# Caption delay in milliseconds (0 = no delay)
# Shifts all caption timestamps forward to create delay between audio and captions
CAPTION_DELAY_MS = int(os.getenv("CAPTION_DELAY_MS", "0"))

# Pipeline optimization mode (Whisper + ffmpeg)
# "standard" - Use hardcoded parameters (default, proven)
# "automatic" - Detect encoding and optimize parameters per file
OPTIMIZATION_MODE = os.getenv(
    "OPTIMIZATION_MODE", os.getenv("WHISPER_MODE", "standard")
)

# Whisper device selection
# "auto" - Automatically detect and use GPU if available, fallback to CPU
# "cuda" - Force GPU usage (will fail if GPU not available)
# "cpu" - Force CPU-only processing (useful for testing or when GPU is busy)
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto").lower()

# Language selection for audio/subtitle processing
# PRIMARY FEATURE: Only process audio and subtitle tracks in the specified language
# Audio language: ISO 639-2/3 language code (eng, spa, fra, deu, etc.)
AUDIO_LANGUAGE = os.getenv("AUDIO_LANGUAGE", "eng")
# Subtitle language: ISO code, "same" (use audio language), or "none" (no subtitles)
SUBTITLE_LANGUAGE = os.getenv("SUBTITLE_LANGUAGE", "same")
# Language fallback: What to do when preferred language not found
# "first" - Use first available stream
# "skip" - Skip processing this recording
LANGUAGE_FALLBACK = os.getenv("LANGUAGE_FALLBACK", "first")

# Preserve all audio tracks in output (default: true)
# true - Copy all audio tracks (slower encoding, preserves language options)
# false - Filter to selected track (faster encoding, loses alternates)
# Set to false to speed up multi-language recordings at cost of losing tracks
PRESERVE_ALL_AUDIO_TRACKS = os.getenv("PRESERVE_ALL_AUDIO_TRACKS", "1").lower() in (
    "true",
    "1",
    "yes",
)

# Hardware-accelerated decoding (NVDEC/CUVID)
# "auto" - Detect and use NVDEC if available (recommended)
# "cuda" - Force CUDA hardware decode (fails if unavailable)
# "off"  - Disable hardware decode, use CPU software decode
# When enabled, MPEG-2 and H.264 input is decoded on the GPU (NVDEC),
# keeping frames in GPU memory for NVENC encoding — avoids CPU bottleneck.
HWACCEL_DECODE = os.getenv("HWACCEL_DECODE", "auto").lower()

# Video encoding quality settings
# NVENC_CQ: Constant Quality for NVIDIA GPU encoding (0-51, lower=better)
#   18 = Near-transparent (high quality)
#   23 = Good quality/size balance (default, matches pre-config encoder behavior)
#   28 = Acceptable quality (faster encoding)
NVENC_CQ = get_env_int("NVENC_CQ", 23)

# X264_CRF: Constant Rate Factor for CPU encoding (0-51, lower=better)
#   18 = Near-transparent (high quality)
#   23 = Good quality/size balance (default, matches x264 standard default)
#   28 = Acceptable quality (faster encoding)
X264_CRF = get_env_int("X264_CRF", 23)

# Database file location (SQLite)
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "py_captions.db"))

# State file for tracking last processed timestamp
STATE_FILE = os.getenv("STATE_FILE", os.path.join(DATA_DIR, "state.json"))

# Channels DVR log path (for log-based source, if implemented)
LOG_PATH = os.getenv("LOG_PATH", "/var/log/channels-dvr.log")

# Event source configuration
# DISCOVERY_MODE: unified setting for event source ("polling", "webhook", "mock")
# Default: "webhook"
DISCOVERY_MODE = os.getenv("DISCOVERY_MODE", "webhook")

# Set USE_* flags based on DISCOVERY_MODE for backward compatibility
USE_MOCK = get_env_bool("USE_MOCK", DISCOVERY_MODE == "mock")
USE_WEBHOOK = get_env_bool("USE_WEBHOOK", DISCOVERY_MODE == "webhook")
USE_POLLING = get_env_bool("USE_POLLING", DISCOVERY_MODE == "polling")

# Webhook configuration (when USE_WEBHOOK=True)
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = get_env_int("WEBHOOK_PORT", 9000)

# Polling configuration (when USE_POLLING=True)
POLL_INTERVAL_SECONDS = get_env_int("POLL_INTERVAL_SECONDS", 120)  # 2 minutes default
POLL_LIMIT = get_env_int("POLL_LIMIT", 150)  # Fetch 150 most recent recordings
POLL_MAX_AGE_HOURS = get_env_int(
    "POLL_MAX_AGE_HOURS", 24
)  # Consider recordings up to 24 hours old
POLL_MAX_QUEUE_SIZE = get_env_int(
    "POLL_MAX_QUEUE_SIZE", 1
)  # Max pending/running executions (1=serial to avoid Whisper model race conditions)

# Pipeline configuration
DRY_RUN = get_env_bool("DRY_RUN", False)
PIPELINE_TIMEOUT = get_env_int("PIPELINE_TIMEOUT", 3600)
STALE_EXECUTION_SECONDS = get_env_int("STALE_EXECUTION_SECONDS", PIPELINE_TIMEOUT)
MANUAL_PROCESS_POLL_SECONDS = get_env_int("MANUAL_PROCESS_POLL_SECONDS", 10)
# Backward compatibility - support old env var name
REPROCESS_POLL_SECONDS = MANUAL_PROCESS_POLL_SECONDS

# Whitelist configuration
WHITELIST_FILE = os.getenv("WHITELIST_FILE", "./whitelist.txt")

# API timeout
API_TIMEOUT = get_env_int("API_TIMEOUT", 10)

# Server timezone for "today" calculations (job numbers, etc.)
# All timestamps are stored in UTC, but "today" is relative to this timezone
# Format: IANA timezone names (e.g., "America/New_York", "Europe/London")
# Default: System timezone if not specified
SERVER_TZ = os.getenv("SERVER_TZ")

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_VERBOSITY = os.getenv("LOG_VERBOSITY", "NORMAL")  # MINIMAL, NORMAL, or VERBOSE
LOG_FILE = os.getenv(
    "LOG_FILE", os.path.join(DATA_DIR, "app.log")
)  # Write logs to file (in addition to stdout)
LOG_FILE_READ = os.getenv("LOG_FILE_READ", LOG_FILE)
LOG_VERBOSITY_FILE = os.getenv(
    "LOG_VERBOSITY_FILE", os.path.join(DATA_DIR, "log_verbosity.json")
)

# Logging visuals and stats
LOG_DIVIDER_LENGTH = get_env_int("LOG_DIVIDER_LENGTH", 40)
LOG_DIVIDER_CHAR = os.getenv("LOG_DIVIDER_CHAR", "-")
LOG_STATS_ENABLED = get_env_bool("LOG_STATS_ENABLED", True)

# Validate LOG_VERBOSITY
if LOG_VERBOSITY.upper() not in ("MINIMAL", "NORMAL", "VERBOSE"):
    raise ValueError(
        f"Invalid LOG_VERBOSITY: {LOG_VERBOSITY}. Must be MINIMAL, NORMAL, or VERBOSE"
    )

# Orphan file cleanup configuration
ORPHAN_CLEANUP_ENABLED = get_env_bool("ORPHAN_CLEANUP_ENABLED", False)
ORPHAN_CLEANUP_INTERVAL_HOURS = get_env_int("ORPHAN_CLEANUP_INTERVAL_HOURS", 24)
ORPHAN_CLEANUP_IDLE_THRESHOLD_MINUTES = get_env_int(
    "ORPHAN_CLEANUP_IDLE_THRESHOLD_MINUTES", 15
)

# Quarantine directory for orphaned files (before permanent deletion)
QUARANTINE_DIR = os.getenv("QUARANTINE_DIR", os.path.join(DATA_DIR, "quarantine"))
QUARANTINE_EXPIRATION_DAYS = get_env_int("QUARANTINE_EXPIRATION_DAYS", 30)

# Media file extensions to check when detecting orphaned .srt/.orig files
# Comma-separated list of extensions (with leading dot)
# An .srt or .orig is only considered orphaned if no file with any of these
# extensions exists at the same path stem.
MEDIA_FILE_EXTENSIONS = tuple(
    ext.strip()
    for ext in os.getenv("MEDIA_FILE_EXTENSIONS", ".mpg,.ts,.mkv,.mp4,.avi").split(",")
    if ext.strip()
)

# --- Experimental features ---
# Channels Files audit: cross-reference DVR API with filesystem
CHANNELS_FILES_ENABLED = get_env_bool("CHANNELS_FILES_ENABLED", False)
