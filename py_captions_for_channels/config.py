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
CHANNELWATCH_URL = os.getenv("CHANNELWATCH_URL") or "ws://localhost:8501/events"

# Channels DVR server base URL
CHANNELS_DVR_URL = os.getenv("CHANNELS_DVR_URL") or "http://localhost:8089"

# Channels DVR API base URL — kept for backward compatibility.
# Code appends /api/v1/... to this value, so it should NOT include /api/v1.
# If someone explicitly sets CHANNELS_API_URL with /api/v1, strip it.
_raw_api_url = os.getenv("CHANNELS_API_URL") or CHANNELS_DVR_URL
CHANNELS_API_URL = _raw_api_url.rstrip("/")
if CHANNELS_API_URL.endswith("/api/v1"):
    CHANNELS_API_URL = CHANNELS_API_URL[: -len("/api/v1")]

# Glances system monitor URL (e.g., http://localhost:61208)
# Set to enable the System Monitor tab in the web UI
GLANCES_URL = os.getenv("GLANCES_URL", "")

# DVR recordings storage path (root directory where recordings are stored)
DVR_RECORDINGS_PATH = os.getenv("DVR_RECORDINGS_PATH", "/recordings")

# Path prefix mapping for distributed deployments.
# When the Channels DVR API returns file paths that differ from where the
# captions system accesses the same files (e.g., DVR on one host, captions
# on another with an NFS/SMB mount), set these to translate API paths.
#
# DVR_PATH_PREFIX — the prefix as the DVR server reports it
# LOCAL_PATH_PREFIX — the corresponding path on the captions host / mount
#
# Example:
#   DVR: /home/channels/DVR/TV/…  →  Captions host mounts at /mnt/dvr-media/TV/…
#   DVR_PATH_PREFIX=/home/channels/DVR
#   LOCAL_PATH_PREFIX=/mnt/dvr-media
#
# When both are set, every API-returned path that starts with DVR_PATH_PREFIX
# will have that prefix swapped for LOCAL_PATH_PREFIX before any file I/O.
# When unset (default), paths pass through unchanged (single-host setup).
DVR_PATH_PREFIX = os.getenv("DVR_PATH_PREFIX", "").rstrip("/") or None
LOCAL_PATH_PREFIX = os.getenv("LOCAL_PATH_PREFIX", "").rstrip("/") or None


def translate_dvr_path(api_path: str) -> str:
    """Translate a Channels DVR API path to a local filesystem path.

    If DVR_PATH_PREFIX and LOCAL_PATH_PREFIX are both configured, replaces
    the DVR prefix with the local prefix.  Otherwise returns the path
    unchanged.

    Args:
        api_path: Path string as returned by the Channels DVR API.

    Returns:
        Translated path suitable for local filesystem access.
    """
    if not DVR_PATH_PREFIX or not LOCAL_PATH_PREFIX:
        return api_path
    if api_path.startswith(DVR_PATH_PREFIX):
        translated = LOCAL_PATH_PREFIX + api_path[len(DVR_PATH_PREFIX):]
        return translated
    return api_path


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

# Audio codec for the encode step
# "auto"  - Copy audio if source codec is MP4-compatible (ac3, eac3, aac, mp3, flac,
#            opus), otherwise re-encode to AAC.  Fastest option for broadcast sources.
# "copy"  - Always stream-copy audio (fastest, but may fail if codec is incompatible)
# "aac"   - Always re-encode to AAC 256 kbps (legacy behaviour, slowest)
AUDIO_CODEC = os.getenv("AUDIO_CODEC", "auto").lower()

# Hardware-accelerated decoding
# "auto" - Detect best available: NVDEC → QSV → VAAPI → CPU (recommended)
# "cuda" - Force NVIDIA NVDEC/CUVID hardware decode
# "qsv"  - Force Intel Quick Sync Video hardware decode
# "vaapi" - Force VA-API hardware decode (Intel/AMD on Linux)
# "off"  - Disable hardware decode, always use CPU software decode
# When enabled, input video is decoded on the GPU's fixed-function hardware,
# keeping frames in GPU memory for hardware encoding — avoids CPU bottleneck.
HWACCEL_DECODE = os.getenv("HWACCEL_DECODE", "auto").lower()

# GPU encoder selection (which hardware encoder to prefer)
# "auto"   - Detect best available: NVENC → QSV → AMF → VAAPI → CPU
# "nvenc"  - Force NVIDIA NVENC
# "qsv"    - Force Intel Quick Sync Video encoder
# "amf"    - Force AMD AMF encoder (Windows/Linux with AMDGPU-PRO)
# "vaapi"  - Force VA-API encoder (Intel/AMD on Linux)
# "cpu"    - Skip GPU encoding, use libx264 CPU encoder
GPU_ENCODER = os.getenv("GPU_ENCODER", "auto").lower()

# Video encoding quality settings
# NVENC_CQ: NVIDIA GPU constant quality (0-51, lower=better)
#   18 = Near-transparent (high quality)
#   23 = Good quality/size balance (default, matches pre-config encoder behavior)
#   28 = Acceptable quality (faster encoding)
NVENC_CQ = get_env_int("NVENC_CQ", 23)

# QSV_PRESET: Intel Quick Sync Video speed preset
# Options: veryfast, faster, fast, medium, slow, veryslow
# Faster presets sacrifice quality for speed.
# Default: fast (good balance for DVR recordings)
QSV_PRESET = os.getenv("QSV_PRESET", "fast")

# QSV_GLOBAL_QUALITY: Intel QSV global quality (1-51, lower=better)
#   18 = Near-transparent (high quality)
#   23 = Good quality/size balance (default)
#   28 = Acceptable quality (faster encoding)
QSV_GLOBAL_QUALITY = get_env_int("QSV_GLOBAL_QUALITY", 23)

# AMF_QUALITY: AMD AMF quality preset
# Options: speed, balanced, quality
# Default: balanced
AMF_QUALITY = os.getenv("AMF_QUALITY", "balanced")

# AMF_QP: AMD AMF quantization parameter (0-51, lower=better)
#   18 = Near-transparent quality
#   23 = Good balance (default)
#   28 = Acceptable quality
AMF_QP = get_env_int("AMF_QP", 23)

# VAAPI_QP: VA-API quantization parameter (0-51, lower=better)
# Used for VAAPI encoder on Intel/AMD Linux
VAAPI_QP = get_env_int("VAAPI_QP", 23)

# VAAPI_DEVICE: VA-API render device path (Linux only)
# Default: /dev/dri/renderD128
VAAPI_DEVICE = os.getenv("VAAPI_DEVICE", "/dev/dri/renderD128")

# X264_CRF: Constant Rate Factor for CPU encoding (0-51, lower=better)
#   18 = Near-transparent (high quality)
#   23 = Good quality/size balance (default, matches x264 standard default)
#   28 = Acceptable quality (faster encoding)
X264_CRF = get_env_int("X264_CRF", 23)

# Database file location (SQLite)
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "py_captions.db"))

# State file for tracking last processed timestamp
STATE_FILE = os.getenv("STATE_FILE", os.path.join(DATA_DIR, "state.json"))

# Channels DVR log path (DEPRECATED — log-based source was never implemented)
# Kept for backward compatibility; will be removed in a future release.
LOG_PATH = os.getenv("LOG_PATH", "/var/log/channels-dvr.log")

# Event source configuration
# DISCOVERY_MODE: unified setting for event source ("polling", "webhook", "mock")
# Default: "polling"
DISCOVERY_MODE = os.getenv("DISCOVERY_MODE", "polling")

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
