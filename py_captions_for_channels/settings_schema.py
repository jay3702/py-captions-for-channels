"""
Declarative schema for the web UI Settings modal.

This is the single source of truth for how `.env` settings are organized in
the UI: which of the service's major functions a setting belongs to, and
whether it's a simple/frequently-touched ("basic") or a rarely-touched
("advanced") knob within that function.

Previously this grouping lived in two disconnected places — a Python
function that inferred categories by matching hardcoded substrings against
`.env.example` section-header comments, and five separate hardcoded arrays
in `main.js` classifying field types by key name. A new setting (e.g. the
`WATCHDOG_*` block) could fall through both silently: no error, just a
setting that lands in the wrong bucket or renders with the wrong control.
Adding an entry here is now the only step required.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Ordered (key, title) — this is also the render order in the UI.
GROUPS: List[Tuple[str, str]] = [
    ("event_source", "Event Source"),
    ("transcription", "Transcription"),
    ("encoding", "Caption Output & Encoding"),
    ("processing", "Processing Rules"),
    ("watchdog", "Reliability & Watchdog"),
    ("storage", "Storage & Paths"),
    ("logging", "Logging & Diagnostics"),
]

BASIC = "basic"
ADVANCED = "advanced"


@dataclass
class SettingSpec:
    group: str
    tier: str = BASIC
    type: str = (
        "text"  # text | number | checkbox | select | textarea | password | timezone
    )
    options: Optional[List[str]] = None
    label: Optional[str] = None
    # Set for the handful of fields rendered by a bespoke widget instead of
    # the generic per-field loop (e.g. the per-vendor encoder quality knobs,
    # which only show the section matching the active encoder).
    render: Optional[str] = None
    # Only meaningful in "webhook" discovery mode; the UI hides these when
    # DISCOVERY_MODE is "polling" (and vice versa for "polling"-only fields).
    visible_when_discovery_mode: Optional[str] = None


SETTINGS_SCHEMA: Dict[str, SettingSpec] = {
    # ---------------------------------------------------------------- Event Source
    "DISCOVERY_MODE": SettingSpec(
        "event_source", BASIC, "select", options=["polling", "webhook", "mock"]
    ),
    "CHANNELS_DVR_URL": SettingSpec("event_source", BASIC, "text"),
    "CHANNELS_API_URL": SettingSpec("event_source", ADVANCED, "text"),
    "CHANNELWATCH_URL": SettingSpec(
        "event_source", ADVANCED, "text", visible_when_discovery_mode="webhook"
    ),
    "POLL_INTERVAL_SECONDS": SettingSpec(
        "event_source", ADVANCED, "number", visible_when_discovery_mode="polling"
    ),
    "POLL_LIMIT": SettingSpec(
        "event_source", ADVANCED, "number", visible_when_discovery_mode="polling"
    ),
    "WEBHOOK_HOST": SettingSpec(
        "event_source", ADVANCED, "text", visible_when_discovery_mode="webhook"
    ),
    "WEBHOOK_PORT": SettingSpec(
        "event_source", ADVANCED, "number", visible_when_discovery_mode="webhook"
    ),
    # ---------------------------------------------------------------- Transcription
    "WHISPER_ENGINE": SettingSpec(
        "transcription",
        BASIC,
        "select",
        options=["local", "groq"],
        label="Transcription Source (Local / Cloud)",
    ),
    "WHISPER_MODEL": SettingSpec(
        "transcription",
        BASIC,
        "select",
        options=[
            "tiny",
            "tiny.en",
            "base",
            "base.en",
            "small",
            "small.en",
            "medium",
            "medium.en",
            "large-v2",
            "large-v3",
            "large-v3-turbo",
            "distil-large-v3",
            "distil-large-v2",
        ],
    ),
    "WHISPER_DEVICE": SettingSpec(
        "transcription",
        BASIC,
        "select",
        options=["auto", "nvidia", "amd", "intel", "none"],
        label="GPU",
    ),
    "AUDIO_LANGUAGE": SettingSpec("transcription", BASIC, "text"),
    "WHISPER_LOCAL_ENGINE": SettingSpec(
        "transcription",
        ADVANCED,
        "select",
        options=["faster-whisper", "parakeet"],
        label="Local Transcription Engine",
    ),
    "PARAKEET_DEVICE": SettingSpec(
        "transcription", ADVANCED, "select", options=["cpu"]
    ),
    "OPTIMIZATION_MODE": SettingSpec(
        "transcription", ADVANCED, "select", options=["standard", "automatic"]
    ),
    "SUBTITLE_LANGUAGE": SettingSpec("transcription", ADVANCED, "text"),
    "LANGUAGE_FALLBACK": SettingSpec(
        "transcription", ADVANCED, "select", options=["first", "skip"]
    ),
    "GROQ_API_KEY": SettingSpec("transcription", ADVANCED, "password"),
    "GROQ_MODEL": SettingSpec("transcription", ADVANCED, "text"),
    "GROQ_TIER": SettingSpec(
        "transcription", ADVANCED, "select", options=["free", "dev"]
    ),
    "GROQ_MAX_AUDIO_MINUTES": SettingSpec("transcription", ADVANCED, "number"),
    "GROQ_MAX_OVERRUN_MINUTES": SettingSpec("transcription", ADVANCED, "number"),
    "GROQ_DEV_MAX_FILE_MB": SettingSpec("transcription", ADVANCED, "number"),
    "GROQ_DEV_RPM": SettingSpec("transcription", ADVANCED, "number"),
    "GROQ_DEV_RPD": SettingSpec("transcription", ADVANCED, "number"),
    "GROQ_DEV_ASH": SettingSpec("transcription", ADVANCED, "number"),
    "GROQ_DEV_ASD": SettingSpec("transcription", ADVANCED, "number"),
    # ----------------------------------------------- Caption Output & Encoding
    "EMBED_CAPTIONS": SettingSpec(
        "encoding", BASIC, "select", options=["auto", "remux", "h264", "srt_only"]
    ),
    "KEEP_ORIGINAL": SettingSpec("encoding", BASIC, "checkbox"),
    "CAPTION_DELAY_MS": SettingSpec("encoding", ADVANCED, "number"),
    "PRESERVE_ALL_AUDIO_TRACKS": SettingSpec("encoding", ADVANCED, "checkbox"),
    "AUDIO_CODEC": SettingSpec(
        "encoding", ADVANCED, "select", options=["auto", "copy", "aac"]
    ),
    "HWACCEL_DECODE": SettingSpec(
        "encoding",
        ADVANCED,
        "select",
        options=["auto", "cuda", "qsv", "vaapi", "off"],
    ),
    "GPU_ENCODER": SettingSpec(
        "encoding",
        ADVANCED,
        "select",
        options=["auto", "nvenc", "qsv", "amf", "vaapi", "cpu"],
    ),
    "NVENC_CQ": SettingSpec("encoding", ADVANCED, "number", render="encoder_quality"),
    "QSV_PRESET": SettingSpec("encoding", ADVANCED, "text", render="encoder_quality"),
    "QSV_GLOBAL_QUALITY": SettingSpec(
        "encoding", ADVANCED, "number", render="encoder_quality"
    ),
    "AMF_QUALITY": SettingSpec("encoding", ADVANCED, "text", render="encoder_quality"),
    "AMF_QP": SettingSpec("encoding", ADVANCED, "number", render="encoder_quality"),
    "VAAPI_QP": SettingSpec("encoding", ADVANCED, "number", render="encoder_quality"),
    "VAAPI_DEVICE": SettingSpec("encoding", ADVANCED, "text", render="encoder_quality"),
    "X264_CRF": SettingSpec("encoding", ADVANCED, "number", render="encoder_quality"),
    # ---------------------------------------------------------------- Processing Rules
    "PROCESSING_ENABLED": SettingSpec("processing", BASIC, "checkbox"),
    "WHITELIST_REQUIRED": SettingSpec("processing", ADVANCED, "checkbox"),
    "DRY_RUN": SettingSpec("processing", ADVANCED, "checkbox"),
    "PIPELINE_TIMEOUT": SettingSpec("processing", ADVANCED, "number"),
    "STALE_EXECUTION_SECONDS": SettingSpec("processing", ADVANCED, "number"),
    # ------------------------------------------- Reliability & Watchdog
    "WATCHDOG_ENABLED": SettingSpec("watchdog", BASIC, "checkbox"),
    "WATCHDOG_AUTO_RESTART": SettingSpec("watchdog", BASIC, "checkbox"),
    "WATCHDOG_ALERT_WEBHOOK_URL": SettingSpec("watchdog", BASIC, "text"),
    "WATCHDOG_CHECK_INTERVAL_SECONDS": SettingSpec("watchdog", ADVANCED, "number"),
    "WATCHDOG_HEARTBEAT_STALE_SECONDS": SettingSpec("watchdog", ADVANCED, "number"),
    "WATCHDOG_PROGRESS_FRESH_SECONDS": SettingSpec("watchdog", ADVANCED, "number"),
    "WATCHDOG_RESTART_AFTER_SECONDS": SettingSpec("watchdog", ADVANCED, "number"),
    "WATCHDOG_MAX_RESTARTS_PER_DAY": SettingSpec("watchdog", ADVANCED, "number"),
    "WATCHDOG_MIN_RESTART_INTERVAL_SECONDS": SettingSpec(
        "watchdog", ADVANCED, "number"
    ),
    "WATCHDOG_ALERT_REPEAT_SECONDS": SettingSpec("watchdog", ADVANCED, "number"),
    "WATCHDOG_LOOP_FREEZE_SECONDS": SettingSpec("watchdog", ADVANCED, "number"),
    # ---------------------------------------------------------------- Storage & Paths
    "LIBRARY_HOST_PATH": SettingSpec(
        "storage", BASIC, "text", label="Library Host Path (host machine)"
    ),
    "LIBRARY_CONTAINER_PATH": SettingSpec(
        "storage", BASIC, "text", label="Library Container Mount Path"
    ),
    "LIBRARY_HOST_PATH_2": SettingSpec("storage", ADVANCED, "text"),
    "LIBRARY_CONTAINER_PATH_2": SettingSpec("storage", ADVANCED, "text"),
    "LIBRARY_HOST_PATH_3": SettingSpec("storage", ADVANCED, "text"),
    "LIBRARY_CONTAINER_PATH_3": SettingSpec("storage", ADVANCED, "text"),
    "DVR_PATH_PREFIX": SettingSpec(
        "storage", ADVANCED, "text", label="DVR Media Folder Path"
    ),
    "DVR_MEDIA_MOUNT": SettingSpec(
        "storage", ADVANCED, "text", label="Container Mount Path"
    ),
    "DVR_MEDIA_TYPE": SettingSpec("storage", ADVANCED, "text"),
    "DVR_MEDIA_DEVICE": SettingSpec("storage", ADVANCED, "text"),
    "DVR_MEDIA_OPTS": SettingSpec("storage", ADVANCED, "text"),
    "DVR_MEDIA_HOST_PATH": SettingSpec("storage", ADVANCED, "text"),
    "DOCKER_RUNTIME": SettingSpec(
        "storage", ADVANCED, "select", options=["runc", "nvidia"]
    ),
    "NVIDIA_VISIBLE_DEVICES": SettingSpec("storage", ADVANCED, "text"),
    "MEDIA_FILE_EXTENSIONS": SettingSpec("storage", ADVANCED, "text"),
    "ORPHAN_CLEANUP_ENABLED": SettingSpec("storage", ADVANCED, "checkbox"),
    "ORPHAN_CLEANUP_INTERVAL_HOURS": SettingSpec("storage", ADVANCED, "number"),
    "ORPHAN_CLEANUP_IDLE_THRESHOLD_MINUTES": SettingSpec("storage", ADVANCED, "number"),
    "QUARANTINE_EXPIRATION_DAYS": SettingSpec("storage", ADVANCED, "number"),
    # --------------------------------------------- Logging & Diagnostics
    "LOG_LEVEL": SettingSpec(
        "logging",
        BASIC,
        "select",
        options=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    ),
    "SERVER_TZ": SettingSpec("logging", BASIC, "timezone"),
    "API_TIMEOUT": SettingSpec("logging", ADVANCED, "number"),
}

# Keys intentionally never shown in the generic Settings UI: pure
# infrastructure (paths managed via .env/docker-compose only), dev-only
# escape hatches, or legacy aliases superseded by a newer setting.
HIDDEN_KEYS = frozenset(
    {
        "DATA_DIR",
        "HOST_DATA_DIR",
        "DB_PATH",
        "STATE_FILE",
        "LOG_FILE",
        "LOG_PATH",
        "QUARANTINE_DIR",
        "LOCAL_TEST_DIR",  # development only
        "DVR_RECORDINGS_PATH",  # mirrors DVR_MEDIA_MOUNT, kept in sync automatically
        "LOCAL_PATH_PREFIX",  # always kept equal to DVR_MEDIA_MOUNT automatically
        "CAPTION_COMMAND",  # power-user override; edit .env directly if needed
        "USE_MOCK",
        "USE_POLLING",
        "USE_WEBHOOK",  # legacy flags superseded by DISCOVERY_MODE
        "TRANSCODE_FOR_FIRETV",  # legacy alias superseded by EMBED_CAPTIONS
        "WSL_LIB_PATH",  # written by scripts/setup-wsl.sh; docker-compose only
    }
)


def group_title(group_key: str) -> str:
    for key, title in GROUPS:
        if key == group_key:
            return title
    return group_key
