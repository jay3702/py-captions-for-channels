import json
import os
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None
from fastapi import FastAPI, Request, Body, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import logging
import threading
import requests
from .config import (
    STATE_FILE,
    DRY_RUN,
    LOG_FILE,
    LOG_FILE_READ,
    CAPTION_COMMAND,
    STALE_EXECUTION_SECONDS,
    CHANNELS_API_URL,
    CHANNELS_DVR_URL,
    CHANNELWATCH_URL,
    DVR_RECORDINGS_PATH,
    LOG_VERBOSITY,
    LOG_VERBOSITY_FILE,
    USE_MOCK,
    USE_POLLING,
    DISCOVERY_MODE,
    ORPHAN_CLEANUP_ENABLED,
    ORPHAN_CLEANUP_INTERVAL_HOURS,
    ORPHAN_CLEANUP_IDLE_THRESHOLD_MINUTES,
    CHANNELS_FILES_ENABLED,
)
from .state import StateBackend
from .execution_tracker import build_manual_process_job_id, get_tracker
from .logging_config import get_verbosity, set_verbosity
from .version import VERSION, BUILD_NUMBER
from .progress_tracker import get_progress_tracker
from .whitelist import Whitelist
from .database import get_db, init_db
from .services.settings_service import SettingsService
from .services.heartbeat_service import HeartbeatService
from .shutdown_control import get_shutdown_controller
from .system_monitor import get_system_monitor, get_pipeline_timeline
from .orphan_cleanup import OrphanCleanupScheduler, run_cleanup

BASE_DIR = Path(__file__).parent
WEB_ROOT = BASE_DIR / "webui"
TEMPLATES_DIR = WEB_ROOT / "templates"
STATIC_DIR = WEB_ROOT / "static"

app = FastAPI(title="Py Captions Web GUI", version=VERSION)
state_backend = StateBackend(STATE_FILE)
logger = logging.getLogger(__name__)

# Global orphan cleanup scheduler
orphan_cleanup_scheduler = None
cleanup_task = None

# Lock to prevent concurrent filesystem scans (avoids race conditions
# where two scans quarantine the same files simultaneously)
_scan_lock = threading.Lock()

# Cancel flag for delete operations
_delete_cancel = threading.Event()

# Cancel flag for deep scan operations
_scan_cancel = threading.Event()

# Cancel flag for Channels Files audit
_audit_cancel = threading.Event()
_audit_lock = threading.Lock()


def _build_quarantine_service(db):
    """Construct a QuarantineService with distributed filesystem support.

    Registers all enabled scan paths so that quarantine operations route
    files to the quarantine directory on the same filesystem (instant rename).
    """
    from py_captions_for_channels.config import QUARANTINE_DIR
    from py_captions_for_channels.models import ScanPath
    from py_captions_for_channels.services.filesystem_service import (
        FilesystemService,
    )
    from py_captions_for_channels.services.quarantine_service import (
        QuarantineService,
    )

    fs_service = FilesystemService(fallback_quarantine_dir=QUARANTINE_DIR)
    scan_paths = db.query(ScanPath).filter(ScanPath.enabled == True).all()  # noqa: E712
    for sp in scan_paths:
        fs_service.register_path(sp.path)

    return QuarantineService(db, QUARANTINE_DIR, filesystem_service=fs_service)


@app.on_event("startup")
async def startup_event():
    """Initialize database and system monitor on application startup."""
    global orphan_cleanup_scheduler, cleanup_task

    init_db()
    # Start system monitor
    try:
        monitor = get_system_monitor()
        provider_info = monitor.get_gpu_provider_info()
        logger.info(f"System monitor GPU provider: {provider_info}")
        monitor.start()
        logger.info("System monitor started successfully")
    except Exception as e:
        logger.error(f"Failed to start system monitor: {e}", exc_info=True)

    # Start orphan cleanup scheduler if enabled
    if ORPHAN_CLEANUP_ENABLED:
        try:
            orphan_cleanup_scheduler = OrphanCleanupScheduler(
                enabled=True,
                check_interval_hours=ORPHAN_CLEANUP_INTERVAL_HOURS,
                idle_threshold_minutes=ORPHAN_CLEANUP_IDLE_THRESHOLD_MINUTES,
                dry_run=DRY_RUN,
            )
            # Start background task to check cleanup periodically
            cleanup_task = asyncio.create_task(orphan_cleanup_background_task())
            logger.info(
                f"Orphan cleanup scheduler enabled: "
                f"interval={ORPHAN_CLEANUP_INTERVAL_HOURS}h, "
                f"idle_threshold={ORPHAN_CLEANUP_IDLE_THRESHOLD_MINUTES}m"
            )
        except Exception as e:
            logger.error(
                f"Failed to start orphan cleanup scheduler: {e}", exc_info=True
            )
    else:
        logger.info("Orphan cleanup scheduler disabled")


async def orphan_cleanup_background_task():
    """Background task to periodically check and run orphan file cleanup."""
    # Check every hour
    while True:
        try:
            await asyncio.sleep(3600)  # 1 hour

            if orphan_cleanup_scheduler and orphan_cleanup_scheduler.enabled:
                result = orphan_cleanup_scheduler.run_if_needed()
                if result:
                    logger.info(f"Orphan cleanup completed: {result}")
        except asyncio.CancelledError:
            logger.info("Orphan cleanup background task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in orphan cleanup background task: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event():
    """Stop system monitor and cleanup tasks on application shutdown."""
    # Cancel cleanup task if running
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

    # Stop system monitor
    monitor = get_system_monitor()
    monitor.stop()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)
LOG = logging.getLogger(__name__)


# --- Root Route for Web UI ---
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main dashboard UI (index.html) at the root URL."""
    response = templates.TemplateResponse("index.html", {"request": request})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# --- Pipeline Settings API ---


# --- Service Health Check Helper ---
def check_service_health(url: str):
    """
    Check if a service at the given URL is reachable.
    Returns (healthy: bool, message: str).
    """
    try:
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return True, f"HTTP {resp.status_code} OK"
    except requests.exceptions.Timeout:
        return False, "Timeout"
    except requests.exceptions.ConnectionError:
        return False, "Connection error"
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP error: {e.response.status_code}"
    except Exception as e:
        return False, f"Error: {str(e)}"


SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"
SETTINGS_LOCK = threading.Lock()


def load_settings(db: Session = None) -> dict:
    """Load settings from database, migrating from JSON/env if needed."""
    # Get or create database session
    if db is None:
        db = next(get_db())
        close_db = True
    else:
        close_db = False

    try:
        settings_service = SettingsService(db)

        # Check if database is empty (first run)
        all_settings = settings_service.get_all()

        if not all_settings:
            # Migrate from settings.json or .env
            LOG.info("Migrating settings to database...")

            # Try settings.json first
            if SETTINGS_PATH.exists():
                try:
                    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                        json_settings = json.load(f)
                    settings_service.set_many(json_settings)
                    LOG.info("Migrated settings from settings.json")
                except Exception as e:
                    LOG.warning(f"Failed to migrate from settings.json: {e}")

            # Fall back to .env defaults
            else:
                env_path = Path(__file__).parent.parent / ".env"
                env_vars = {}
                if env_path.exists():
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if (
                                line.strip()
                                and not line.strip().startswith("#")
                                and "=" in line
                            ):
                                k, v = line.split("=", 1)
                                env_vars[k.strip()] = v.strip()

                def env_bool(key, default):
                    return env_vars.get(key, str(default)).lower() in (
                        "true",
                        "1",
                        "yes",
                        "on",
                    )

                defaults = {
                    "discovery_mode": (
                        "mock" if USE_MOCK else "polling" if USE_POLLING else "webhook"
                    ),
                    "dry_run": env_bool("DRY_RUN", DRY_RUN),
                    "keep_original": env_bool("KEEP_ORIGINAL", True),
                    "log_verbosity": env_vars.get("LOG_VERBOSITY", LOG_VERBOSITY),
                    "whisper_model": env_vars.get(
                        "WHISPER_MODEL", os.getenv("WHISPER_MODEL", "medium")
                    ),
                }
                settings_service.set_many(defaults)
                LOG.info("Initialized settings from .env defaults")

            # Refresh after migration
            all_settings = settings_service.get_all()

        # Get whitelist from database (or migrate from file if needed)
        whitelist_content = settings_service.get("whitelist", "")

        # If whitelist is empty in DB, try to migrate from file
        if not whitelist_content:
            whitelist_path = Path(__file__).parent.parent / "whitelist.txt"
            try:
                if whitelist_path.exists():
                    with open(whitelist_path, "r", encoding="utf-8") as f:
                        whitelist_content = f.read()
                    # Save to database for future use
                    settings_service.set("whitelist", whitelist_content)
                    LOG.info("Migrated whitelist from file to database")
            except Exception as e:
                LOG.warning("Failed to migrate whitelist from file: %s", e)

        all_settings["whitelist"] = whitelist_content

        return all_settings
    finally:
        if close_db:
            db.close()


def save_settings(settings: dict, db: Session = None):
    """Save settings to database."""
    # Get or create database session
    if db is None:
        db = next(get_db())
        close_db = True
    else:
        close_db = False

    try:
        settings_service = SettingsService(db)

        # Extract whitelist to save separately
        whitelist_content = settings.pop("whitelist", None)

        # Save non-whitelist settings to database
        settings_service.set_many(settings)

        # Save whitelist to database
        if whitelist_content is not None:
            settings_service.set("whitelist", whitelist_content)

        LOG.info("Settings saved to database")
    finally:
        if close_db:
            db.close()


# ==============================================================================
# ENV FILE SETTINGS MANAGEMENT
# ==============================================================================


def get_env_file_path() -> Path:
    """Get the .env file path."""
    return Path(__file__).parent.parent / ".env"


def _parse_env_file(file_path: Path) -> dict:
    """Parse an env file into structured settings.

    Args:
        file_path: Path to the env file to parse

    Returns:
        Dict with settings grouped by category
    """
    # Infrastructure path settings: managed via .env only,
    # hidden from the web Settings UI to avoid accidental changes.
    _SETTINGS_UI_HIDDEN = frozenset(
        {
            "DATA_DIR",
            "HOST_DATA_DIR",
            "DB_PATH",
            "STATE_FILE",
            "LOG_FILE",
            "LOG_PATH",
            "QUARANTINE_DIR",
        }
    )
    settings = {
        "channels_dvr": {},
        "channelwatch": {},
        "event_source": {},
        "polling": {},
        "webhook": {},
        "pipeline": {},
        "state_logging": {},
        "advanced": {},
    }

    current_category = None
    current_description = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line_stripped = line.strip()
            line_upper = line_stripped.upper()

            # Category headers (case-insensitive)
            if "CHANNELS DVR CONFIGURATION" in line_upper:
                current_category = "channels_dvr"
            elif "CHANNELWATCH CONFIGURATION" in line_upper:
                current_category = "channelwatch"
            elif "EVENT SOURCE CONFIGURATION" in line_upper:
                current_category = "event_source"
            elif "POLLING SOURCE CONFIGURATION" in line_upper:
                current_category = "polling"
            elif "WEBHOOK SERVER CONFIGURATION" in line_upper:
                current_category = "webhook"
            elif "CAPTION PIPELINE CONFIGURATION" in line_upper:
                current_category = "pipeline"
            elif "STATE AND LOGGING CONFIGURATION" in line_upper:
                current_category = "state_logging"
            elif "ADVANCED CONFIGURATION" in line_upper:
                current_category = "advanced"

            # Parse setting line (active or commented)
            # Check this BEFORE comment collection
            elif "=" in line_stripped and current_category:
                # Skip section dividers (lines that are just equal signs)
                stripped_no_comment = line_stripped.lstrip("#").strip()
                if stripped_no_comment.replace("=", "") == "":
                    continue

                # Handle "KEY=value" and "# KEY=value" (commented optional)
                is_commented = line_stripped.startswith("#")
                setting_line = line_stripped.lstrip("#").strip()

                if "=" in setting_line:
                    key, value = setting_line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    # Skip if key doesn't look like a valid setting name
                    # (must be uppercase/underscore, not lowercase/sentence)
                    if not key or not key.replace("_", "").isupper():
                        # This is a description line with "=", not a setting
                        # Treat it as a comment instead
                        desc = line_stripped.lstrip("# ").strip()
                        if (
                            desc
                            and not desc.startswith("Default:")
                            and not desc.startswith("Note:")
                        ):
                            current_description.append(desc)
                        continue

                    # Skip infrastructure path settings hidden from UI
                    if key in _SETTINGS_UI_HIDDEN:
                        current_description = []
                        continue

                    # Extract default from description
                    default_value = None
                    for desc_line in current_description:
                        if desc_line.startswith("Default:"):
                            default_value = desc_line.replace("Default:", "").strip()

                    settings[current_category][key] = {
                        "value": value,
                        "description": " ".join(current_description),
                        "default": default_value,
                        "optional": is_commented,
                    }
                    current_description = []

            # Collect comment lines as description (after checking for settings)
            elif line_stripped.startswith("#") and current_category:
                # Skip section dividers
                if not line_stripped.startswith("# ===="):
                    desc = line_stripped.lstrip("# ").strip()
                    if (
                        desc
                        and not desc.startswith("Default:")
                        and not desc.startswith("Note:")
                    ):
                        current_description.append(desc)

            # Empty line resets description
            elif not line_stripped:
                current_description = []

    return settings


def load_env_settings() -> dict:
    """Load all settings from .env.example (template) merged with actual .env values.

    This ensures all available settings appear in the UI, even if not in .env yet.
    Current values come from .env, descriptions/defaults come from .env.example.

    Returns:
        Dict with settings grouped by category:
        {
            "channels_dvr": {
                "CHANNELS_API_URL": {
                    "value": "...",
                    "description": "..."
                }
            },
            "event_source": {...},
            ...
        }
    """
    env_path = get_env_file_path()
    env_example_path = Path(__file__).parent.parent / ".env.example"

    try:
        # Load template from .env.example (all available settings with descriptions)
        if not env_example_path.exists():
            LOG.warning(
                f".env.example not found at {env_example_path}, "
                f"falling back to .env only"
            )
            template = {}
        else:
            LOG.debug(f"Loading template from {env_example_path}")
            template = _parse_env_file(env_example_path)
            LOG.debug(
                f"Template loaded: {sum(len(v) for v in template.values())} settings"
            )

        # Load actual values from .env
        if not env_path.exists():
            LOG.warning(
                f".env file not found at {env_path}, using .env.example defaults only"
            )
            actual = {}
        else:
            LOG.debug(f"Loading actual values from {env_path}")
            actual = _parse_env_file(env_path)
            LOG.debug(f"Actual loaded: {sum(len(v) for v in actual.values())} settings")

        # Merge: start with template, override values from actual .env
        # Get all unique categories from both template and actual
        all_categories = set(template.keys()) | set(actual.keys())

        merged = {}
        for category in all_categories:
            merged[category] = {}

            # Add all settings from template for this category
            for key, config in template.get(category, {}).items():
                merged[category][key] = config.copy()
                # Override value if present in actual .env
                if key in actual.get(category, {}):
                    merged[category][key]["value"] = actual[category][key]["value"]
                    # If it's set in actual .env, mark as not optional
                    merged[category][key]["optional"] = actual[category][key][
                        "optional"
                    ]

            # Add any settings from actual .env that aren't in template
            for key, config in actual.get(category, {}).items():
                if key not in merged[category]:
                    merged[category][key] = config.copy()

        # Inject runtime values for settings with placeholders
        # This ensures UI shows actual values being used by the system
        from py_captions_for_channels import config

        runtime_values = {
            "CHANNELS_DVR_URL": config.CHANNELS_DVR_URL,
            "CHANNELS_API_URL": config.CHANNELS_API_URL,
            "CHANNELWATCH_URL": config.CHANNELWATCH_URL,
            "DVR_RECORDINGS_PATH": config.DVR_RECORDINGS_PATH,
            "WHISPER_DEVICE": config.WHISPER_DEVICE,
        }

        # Replace placeholder values with runtime values
        for category in merged:
            for key in merged[category]:
                if key in runtime_values:
                    value = merged[category][key].get("value", "")
                    # If value contains placeholder text or is empty, use runtime value
                    if (
                        not value
                        or "<" in value
                        or ">" in value
                        or value == runtime_values[key]
                    ):
                        # Only update if runtime value differs from default
                        runtime_val = runtime_values[key]
                        if runtime_val and runtime_val != merged[category][key].get(
                            "default", ""
                        ):
                            merged[category][key]["value"] = runtime_val

        LOG.info(
            f"Loaded settings: {sum(len(v) for v in merged.values())} "
            f"settings across {len(merged)} categories"
        )
        return merged

    except Exception as e:
        LOG.error(f"Error loading .env settings: {e}", exc_info=True)
        return {"error": str(e)}


def save_env_settings(settings: dict) -> dict:
    """Save settings back to .env file, preserving structure and comments.

    Args:
        settings: Dict of settings by category and key

    Returns:
        Success/error dict
    """
    env_path = get_env_file_path()

    try:
        # Read original file to preserve structure
        with open(env_path, "r", encoding="utf-8") as f:
            original_lines = f.readlines()

        # Track which settings have been written
        written_keys = set()

        # Update values while preserving comments and structure
        new_lines = []
        for line in original_lines:
            line_stripped = line.strip()

            # Keep section headers and pure comments as-is
            if (
                line_stripped.startswith("#")
                and "=" not in line_stripped
                or not line_stripped
            ):
                new_lines.append(line)

            # Check for setting lines (commented or not)
            elif "=" in line_stripped:
                is_commented = line_stripped.startswith("#")
                setting_line = line_stripped.lstrip("#").strip()
                key = setting_line.split("=", 1)[0].strip()

                # Find this key in new settings
                found = False
                for category in settings.values():
                    if isinstance(category, dict) and key in category:
                        new_value = category[key].get("value", "")
                        # Uncomment and set value if provided
                        if new_value:
                            new_lines.append(f"{key}={new_value}\n")
                        # Keep commented if value is empty and was originally commented
                        elif is_commented:
                            new_lines.append(line)
                        # Keep as empty if was originally uncommented
                        else:
                            new_lines.append(f"{key}=\n")
                        written_keys.add(key)
                        found = True
                        break

                if not found:
                    # Keep original if not in update
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # Append any new settings that weren't in the original file
        for category_name, category in settings.items():
            if isinstance(category, dict):
                for key, config in category.items():
                    if key not in written_keys:
                        new_value = config.get("value", "")
                        if new_value:
                            new_lines.append(f"{key}={new_value}\n")
                            LOG.info(f"Adding new setting to .env: {key}={new_value}")

        # Write back to file
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        LOG.info("Settings saved to .env file")
        return {
            "success": True,
            "message": "Settings saved. Restart required to apply changes.",
        }

    except Exception as e:
        LOG.error(f"Error saving .env settings: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/env-settings")
async def get_env_settings() -> dict:
    """Get all settings from .env file."""
    return load_env_settings()


@app.post("/api/env-settings")
async def set_env_settings(data: dict = Body(...)) -> dict:
    """Update settings in .env file."""
    return save_env_settings(data)


@app.get("/api/settings")
async def get_settings(db: Session = Depends(get_db)) -> dict:
    """Get pipeline settings and whitelist from database."""
    try:
        return load_settings(db)
    except Exception as e:
        LOG.error(f"Error loading settings: {e}")
        return {"error": str(e)}


@app.post("/api/settings")
async def set_settings(data: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """Update pipeline settings and whitelist in database."""
    try:
        allowed = {
            "discovery_mode",
            "dry_run",
            "keep_original",
            "log_verbosity",
            "whisper_model",
            "whitelist",
        }
        current = load_settings(db)
        for k in allowed:
            if k in data:
                current[k] = data[k]
        save_settings(current, db)
        return {"ok": True}
    except Exception as e:
        LOG.error(f"Error saving settings: {e}")
        return {"error": str(e)}


def _get_local_tz():
    """Determine local timezone; prefer TZ/SERVER_TZ env vars if set."""
    tz_name = os.getenv("SERVER_TZ") or os.getenv("TZ")
    if tz_name and ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            LOG.warning("Invalid timezone '%s'; falling back to system", tz_name)
    # Fallback to system local tz
    try:
        return datetime.now().astimezone().tzinfo
    except Exception:
        return None


LOCAL_TZ = _get_local_tz()


def format_local(ts: str) -> str:
    """Format an ISO timestamp (assumed UTC) into server local time for display."""
    try:
        dt = datetime.fromisoformat(ts)
        # Assume UTC if naive
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)

        # Convert to configured local timezone if available
        if LOCAL_TZ is not None:
            dt_local = dt.astimezone(LOCAL_TZ)
        else:
            dt_local = dt.astimezone()

        return dt_local.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        LOG.warning("Error formatting timestamp %s: %s", ts, e)
        return ts


@app.get("/api/status")
async def status() -> dict:
    """Return pipeline status and statistics.

    Reads from state file to report:
    - Last timestamp processed
    - Manual process queue size
    - Configuration snapshot
    - Dry-run mode status
    - Service health (Channels DVR, ChannelWatch)
    """
    try:
        # Reload state to get latest
        state_backend._load()

        last_ts = state_backend.last_ts
        manual_process_queue = state_backend.get_manual_process_queue()

        # Check service health
        channels_healthy, channels_msg = check_service_health(CHANNELS_API_URL)
        channelwatch_healthy, channelwatch_msg = check_service_health(CHANNELWATCH_URL)

        # Check if whisper and ffmpeg processes are running
        # Infer from execution tracker - if any executions are running
        # Note: Without pub/sub, we assume whisper is the primary
        # process (longest running) and show ffmpeg only if processing
        # but whisper isn't detected
        whisper_running = False
        ffmpeg_running = False
        try:
            tracker = get_tracker()
            all_execs = tracker.get_executions()
            running_execs = [e for e in all_execs if e.get("status") == "running"]
            # If any execution is running, assume whisper is active (primary process)
            # This is a simplification until pub/sub is implemented
            if len(running_execs) > 0:
                whisper_running = True
                # ffmpeg runs briefly before/after whisper, so we don't show it
                # to avoid both being green simultaneously
            logging.debug(
                f"Process status check: {len(running_execs)} running, "
                f"whisper={whisper_running}, ffmpeg={ffmpeg_running}"
            )
        except Exception as e:
            logging.error(f"Error checking process status: {e}")
            pass  # If check fails, just show as not running

        settings = load_settings()

        # Check heartbeat database
        heartbeat_data = {}
        try:
            heartbeat_service = HeartbeatService(next(get_db()))
            heartbeat_data = heartbeat_service.get_all_heartbeats()
            LOG.debug(
                "Retrieved %d heartbeat(s): %s",
                len(heartbeat_data),
                list(heartbeat_data.keys()),
            )
        except Exception as e:
            LOG.warning("Error reading heartbeat: %s", e)

        # Get progress data for active processes
        progress_data = {}
        try:
            progress_tracker = get_progress_tracker()
            all_progress = progress_tracker.get_all_progress()
            tracker = get_tracker()

            # Filter to active processes (updated in last 30 seconds)
            now = datetime.now(timezone.utc)
            for job_id, prog in all_progress.items():
                updated_at_str = prog.get("updated_at")
                if not updated_at_str:
                    continue

                updated_dt = datetime.fromisoformat(updated_at_str)
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                age_seconds = (now - updated_dt).total_seconds()

                # Only include recent progress (< 30 seconds old)
                if age_seconds >= 30:
                    continue

                # Only include progress for running jobs
                exec_data = tracker.get_execution(job_id)
                if not exec_data or exec_data.get("status") not in (
                    "running",
                    "canceling",
                ):
                    continue

                progress_data[job_id] = {
                    "process_type": prog.get("process_type", "unknown"),
                    "percent": prog.get("percent", 0),
                    "message": prog.get("message", ""),
                    "age_seconds": age_seconds,
                    "job_number": exec_data.get("job_number"),
                }
        except Exception as e:
            LOG.debug("Error reading progress: %s", e)

        misc_active = any(
            prog.get("process_type") == "misc" for prog in progress_data.values()
        )

        # Build services dict, only include ChannelWatch if configured
        services = {
            "channels_dvr": {
                "name": "Channels DVR",
                "url": CHANNELS_API_URL,
                "healthy": channels_healthy,
                "status": channels_msg,
            },
        }

        # Only add ChannelWatch if in webhook mode and it's configured
        if DISCOVERY_MODE == "webhook" and CHANNELWATCH_URL:
            services["channelwatch"] = {
                "name": "ChannelWatch",
                "url": CHANNELWATCH_URL,
                "healthy": channelwatch_healthy,
                "status": channelwatch_msg,
            }

        # Add process indicators
        services["whisper"] = {
            "name": "Whisper",
            "url": None,
            "healthy": whisper_running,
            "status": "Running" if whisper_running else "Idle",
        }

        services["ffmpeg"] = {
            "name": "ffmpeg",
            "url": None,
            "healthy": ffmpeg_running,
            "status": "Running" if ffmpeg_running else "Idle",
        }

        services["misc"] = {
            "name": "File Ops",
            "url": None,
            "healthy": misc_active,
            "status": "Active" if misc_active else "Idle",
        }

        return {
            "app": "py-captions-for-channels",
            "version": VERSION,
            "build_number": BUILD_NUMBER,
            "status": "running",
            "dry_run": settings.get("dry_run", False),
            "keep_original": settings.get("keep_original", True),
            "log_verbosity": settings.get("log_verbosity", "NORMAL"),
            "whisper_model": settings.get("whisper_model", "medium"),
            "last_processed": last_ts.isoformat() if last_ts else None,
            "manual_process_queue_size": len(manual_process_queue),
            "caption_command": (
                CAPTION_COMMAND[:50] + "..."
                if len(CAPTION_COMMAND) > 50
                else CAPTION_COMMAND
            ),
            "log_file": str(LOG_FILE),
            "timezone": str(LOCAL_TZ) if LOCAL_TZ else "system-default",
            "services": services,
            "heartbeat": heartbeat_data,
            "progress": progress_data,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "app": "py-captions-for-channels",
            "version": VERSION,
            "build_number": BUILD_NUMBER,
            "status": "error",
            "error": str(e),
            "services": {
                "channels_dvr": {
                    "name": "Channels DVR",
                    "url": CHANNELS_API_URL,
                    "healthy": False,
                    "status": "Error loading status",
                },
                "channelwatch": {
                    "name": "ChannelWatch",
                    "url": CHANNELWATCH_URL,
                    "healthy": False,
                    "status": "Error loading status",
                },
            },
            "timestamp": datetime.now().isoformat(),
        }


@app.get("/api/logs")
async def logs_endpoint(lines: int = 100) -> dict:
    """Return recent log lines from the application log file.

    Args:
        lines: Number of recent lines to return (default 100)

    Returns:
        Dict with log items and metadata
    """
    items = []

    # Return log file path and info
    log_path = Path(LOG_FILE_READ)

    if log_path.exists():
        try:
            # Read last N lines from log file
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                # Get last N lines
                recent_lines = (
                    all_lines[-lines:] if len(all_lines) > lines else all_lines
                )
                items = [line.rstrip() for line in recent_lines]
        except Exception as e:
            items = [f"Error reading logs: {str(e)}"]
    else:
        items = [f"Log file not found: {LOG_FILE_READ}"]

    return {
        "items": items,
        "count": len(items),
        "log_file": str(LOG_FILE_READ),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/glances/{path:path}")
async def glances_proxy(path: str = ""):
    """Proxy requests to Glances web interface running on port 61208.

    Args:
        path: Path to proxy to Glances

    Returns:
        Response from Glances
    """
    from fastapi.responses import Response
    import httpx

    # Connect to Glances running in the main container via host IP
    glances_url = f"http://192.168.3.150:61208/{path}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(glances_url)
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
    except Exception as e:
        return Response(
            content=f"Error connecting to Glances: {str(e)}",
            status_code=503,
        )


@app.get("/api/executions")
async def get_executions(limit: int = 50) -> dict:
    """Get recent pipeline executions.

    Args:
        limit: Maximum number of executions to return

    Returns:
        Dict with execution list and metadata
    """
    try:
        tracker = get_tracker()
        tracker.mark_stale_executions(timeout_seconds=STALE_EXECUTION_SECONDS)
        executions = tracker.get_executions(limit=limit)

        # Add local time formatting to each execution
        for exec in executions:
            if exec.get("started_at"):
                exec["started_local"] = format_local(exec["started_at"])
            if exec.get("completed_at"):
                exec["completed_local"] = format_local(exec["completed_at"])

        status_rank = {
            "running": 0,
            "pending": 1,
            "discovered": 2,
        }

        def sort_key(item: dict) -> tuple:
            rank = status_rank.get(item.get("status"), 99)
            job_number = item.get("job_number")
            job_number = job_number if isinstance(job_number, int) else -1
            started_at = item.get("started_at")
            started_key = 0.0
            if isinstance(started_at, str):
                try:
                    started_key = -datetime.fromisoformat(started_at).timestamp()
                except ValueError:
                    started_key = 0.0
            return (
                rank,
                -job_number,
                started_key,
            )

        executions = sorted(executions, key=sort_key)

        return {
            "executions": executions,
            "count": len(executions),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "executions": [],
            "count": 0,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@app.post("/api/executions/clear_list")
async def clear_list_executions(cancel_pending: bool = False) -> dict:
    """Clear list intelligently based on status.

    Removes:
    - Failed executions (completed with success=False)
    - Cancelled executions (status="cancelled")
    - Dry-run executions (status="dry_run")
    - Discovered executions (status="discovered")
    - Stale pending executions (not in manual process queue AND older than 60 minutes)

    Stale pending executions are those that will never be processed:
    - Created more than 60 minutes ago
    - No longer in the manual process queue
    - Not actively being processed

    If there are legitimate pending executions (in queue and recent),
    returns them for confirmation before clearing.

    Args:
        cancel_pending: If True, also cancel and remove legitimate pending executions

    Returns:
        Dict with removed_ids, pending_count, and optionally pending_ids
    """
    try:
        tracker = get_tracker()
        executions = tracker.get_executions(limit=10000)
        manual_queue = set(state_backend.get_manual_process_queue())
        now = datetime.now(timezone.utc)

        removed_ids = []
        pending_ids = []

        for exec_data in executions:
            job_id = exec_data.get("id")
            status = exec_data.get("status")
            path = exec_data.get("path", "")
            started_at = exec_data.get("started_at")

            # NEVER remove running executions - they are actively processing
            if status == "running":
                continue

            # Remove failed executions
            if status == "completed" and exec_data.get("success") is False:
                if job_id and tracker.remove_execution(job_id):
                    removed_ids.append(job_id)

            # Remove cancelled executions
            elif status == "cancelled":
                if job_id and tracker.remove_execution(job_id):
                    removed_ids.append(job_id)

            # Remove dry-run executions
            elif status == "dry_run":
                if job_id and tracker.remove_execution(job_id):
                    removed_ids.append(job_id)

            # Remove discovered executions (backlog that hasn't been queued yet)
            elif status == "discovered":
                if job_id and tracker.remove_execution(job_id):
                    removed_ids.append(job_id)

            # Handle pending executions
            elif status == "pending":
                # Check if this is in the manual queue (legitimate)
                in_queue = any(
                    path.endswith(q) or q.endswith(path) for q in manual_queue
                )

                # Check if pending is stale (older than 60 minutes)
                is_stale = False
                if started_at:
                    try:
                        dt = datetime.fromisoformat(started_at)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        age_minutes = (now - dt).total_seconds() / 60.0
                        is_stale = age_minutes > 60
                    except Exception:
                        is_stale = True

                # Remove invalid pending (not in queue AND stale)
                # Recent pending items might be legitimately processing
                if not in_queue and is_stale:
                    if job_id and tracker.remove_execution(job_id):
                        removed_ids.append(job_id)
                # Collect legitimate pending that need confirmation
                elif cancel_pending:
                    # User confirmed cancellation of pending jobs
                    if job_id and tracker.remove_execution(job_id):
                        removed_ids.append(job_id)
                else:
                    # Keep track of pending jobs requiring confirmation
                    pending_ids.append(
                        {
                            "id": job_id,
                            "path": path,
                            "title": exec_data.get("title", ""),
                        }
                    )

        return {
            "removed": len(removed_ids),
            "removed_ids": removed_ids,
            "pending_count": len(pending_ids),
            "pending_ids": pending_ids if pending_ids and not cancel_pending else [],
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "removed": 0,
            "pending_count": 0,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@app.post("/api/executions/clear_failed")
async def clear_failed_executions() -> dict:
    """Legacy endpoint - redirect to clear_list for backward compatibility."""
    return await clear_list_executions()


@app.post("/api/executions/clear_pending")
async def clear_pending_executions(max_age_minutes: int = 60) -> dict:
    """DEPRECATED: Use clear_list endpoint instead.

    This endpoint is retained for backward compatibility but redirect to clear_list.
    The clear_list endpoint now handles stale pending executions automatically.
    """
    return await clear_list_executions()


@app.post("/api/polling-cache/clear")
async def clear_polling_cache() -> dict:
    """Clear all polling cache entries.

    This allows previously processed recordings to be picked up again
    on the next poll. Useful for reprocessing failed recordings.
    """
    try:
        from .services.polling_cache_service import PollingCacheService

        db = next(get_db())
        cache_service = PollingCacheService(db)
        count = cache_service.clear_all()
        return {
            "cleared": count,
            "message": f"Cleared {count} polling cache entries",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "cleared": 0,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@app.post("/api/processes/cleanup")
async def cleanup_orphaned_processes() -> dict:
    """Kill orphaned whisper and ffmpeg processes.

    This is useful when processes are left running after container
    restarts or job failures. Only kills processes within this container.
    """
    try:
        import subprocess

        killed = []
        errors = []

        # Find all whisper processes
        try:
            result = subprocess.run(
                ["pgrep", "-f", "whisper"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    try:
                        subprocess.run(["kill", "-9", pid], check=True, timeout=5)
                        killed.append({"type": "whisper", "pid": int(pid)})
                    except Exception as e:
                        errors.append(
                            {"type": "whisper", "pid": int(pid), "error": str(e)}
                        )
        except subprocess.TimeoutExpired:
            errors.append({"type": "whisper", "error": "pgrep timeout"})
        except Exception as e:
            errors.append({"type": "whisper", "error": str(e)})

        # Find all ffmpeg processes
        try:
            result = subprocess.run(
                ["pgrep", "-f", "ffmpeg"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    try:
                        subprocess.run(["kill", "-9", pid], check=True, timeout=5)
                        killed.append({"type": "ffmpeg", "pid": int(pid)})
                    except Exception as e:
                        errors.append(
                            {"type": "ffmpeg", "pid": int(pid), "error": str(e)}
                        )
        except subprocess.TimeoutExpired:
            errors.append({"type": "ffmpeg", "error": "pgrep timeout"})
        except Exception as e:
            errors.append({"type": "ffmpeg", "error": str(e)})

        return {
            "killed": len(killed),
            "processes": killed,
            "errors": errors,
            "message": f"Killed {len(killed)} orphaned processes",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "killed": 0,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@app.post("/api/orphan-cleanup/run")
async def run_orphan_cleanup(dry_run: bool = False) -> dict:
    """Manually trigger orphan file cleanup.

    Args:
        dry_run: If true, only report what would be deleted without deleting

    Returns:
        Cleanup result with statistics
    """
    try:
        logger.info(f"Manual orphan cleanup triggered (dry_run={dry_run})")
        result = run_cleanup(dry_run=dry_run)
        return result
    except Exception as e:
        logger.error(f"Manual orphan cleanup failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


@app.get("/api/orphan-cleanup/status")
async def get_orphan_cleanup_status() -> dict:
    """Get orphan cleanup scheduler status.

    Returns:
        Status information including enabled state and last cleanup time
    """
    if orphan_cleanup_scheduler:
        return {
            "enabled": orphan_cleanup_scheduler.enabled,
            "check_interval_hours": orphan_cleanup_scheduler.check_interval_hours,
            "idle_threshold_minutes": orphan_cleanup_scheduler.idle_threshold_minutes,
            "last_check_time": (
                orphan_cleanup_scheduler.last_check_time.isoformat() + "Z"
                if orphan_cleanup_scheduler.last_check_time
                else None
            ),
            "last_cleanup_time": (
                orphan_cleanup_scheduler.last_cleanup_time.isoformat() + "Z"
                if orphan_cleanup_scheduler.last_cleanup_time
                else None
            ),
        }
    else:
        return {
            "enabled": False,
            "message": "Orphan cleanup scheduler not initialized",
        }


@app.get("/api/scan-paths")
async def get_scan_paths() -> dict:
    """Get all configured scan paths for manual orphan detection.

    Returns:
        List of scan path configurations
    """
    try:
        from py_captions_for_channels.models import ScanPath

        db = next(get_db())
        paths = db.query(ScanPath).order_by(ScanPath.created_at).all()

        return {
            "paths": [
                {
                    "id": p.id,
                    "path": p.path,
                    "label": p.label,
                    "enabled": p.enabled,
                    "created_at": (
                        p.created_at.isoformat() + "Z" if p.created_at else None
                    ),
                    "last_scanned_at": (
                        p.last_scanned_at.isoformat() + "Z"
                        if p.last_scanned_at
                        else None
                    ),
                }
                for p in paths
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get scan paths: {e}", exc_info=True)
        return {"error": str(e), "paths": []}


@app.post("/api/scan-paths")
async def add_scan_path(
    path: str = Body(..., embed=True),
    label: str = Body(None, embed=True),
) -> dict:
    """Add a new scan path for manual orphan detection.

    Args:
        path: Folder path to scan
        label: Optional user-friendly label

    Returns:
        Created scan path info
    """
    try:
        from py_captions_for_channels.models import ScanPath

        # Validate path exists (on the server/container)
        if not os.path.exists(path):
            return {
                "error": (
                    f"Path does not exist on server: {path}. "
                    f"Ensure the path is mounted in the container."
                ),
                "success": False,
            }

        db = next(get_db())

        # Check for duplicates
        existing = db.query(ScanPath).filter(ScanPath.path == path).first()
        if existing:
            return {
                "error": f"Path already exists: {path}",
                "success": False,
            }

        # Create new scan path
        scan_path = ScanPath(path=path, label=label, enabled=True)
        db.add(scan_path)
        db.commit()
        db.refresh(scan_path)

        logger.info(f"Added scan path: {path} (label: {label})")

        return {
            "success": True,
            "path": {
                "id": scan_path.id,
                "path": scan_path.path,
                "label": scan_path.label,
                "enabled": scan_path.enabled,
                "created_at": (
                    scan_path.created_at.isoformat() + "Z"
                    if scan_path.created_at
                    else None
                ),
            },
        }
    except Exception as e:
        logger.error(f"Failed to add scan path: {e}", exc_info=True)
        return {"error": str(e), "success": False}


@app.put("/api/scan-paths/{path_id}")
async def update_scan_path(
    path_id: int,
    path: str = Body(None, embed=True),
    label: str = Body(None, embed=True),
    enabled: bool = Body(None, embed=True),
) -> dict:
    """Update an existing scan path.

    Args:
        path_id: Scan path ID
        path: New folder path (optional)
        label: New label (optional)
        enabled: Enable/disable (optional)

    Returns:
        Updated scan path info
    """
    try:
        from py_captions_for_channels.models import ScanPath

        db = next(get_db())
        scan_path = db.query(ScanPath).filter(ScanPath.id == path_id).first()

        if not scan_path:
            return {"error": f"Scan path not found: {path_id}", "success": False}

        # Update fields if provided
        if path is not None:
            if not os.path.exists(path):
                return {"error": f"Path does not exist: {path}", "success": False}
            scan_path.path = path

        if label is not None:
            scan_path.label = label

        if enabled is not None:
            scan_path.enabled = enabled

        db.commit()
        db.refresh(scan_path)

        logger.info(f"Updated scan path {path_id}: {scan_path.path}")

        return {
            "success": True,
            "path": {
                "id": scan_path.id,
                "path": scan_path.path,
                "label": scan_path.label,
                "enabled": scan_path.enabled,
            },
        }
    except Exception as e:
        logger.error(f"Failed to update scan path: {e}", exc_info=True)
        return {"error": str(e), "success": False}


@app.delete("/api/scan-paths/{path_id}")
async def delete_scan_path(path_id: int) -> dict:
    """Delete a scan path.

    Args:
        path_id: Scan path ID

    Returns:
        Success status
    """
    try:
        from py_captions_for_channels.models import ScanPath

        db = next(get_db())
        scan_path = db.query(ScanPath).filter(ScanPath.id == path_id).first()

        if not scan_path:
            return {"error": f"Scan path not found: {path_id}", "success": False}

        path_str = scan_path.path
        db.delete(scan_path)
        db.commit()

        logger.info(f"Deleted scan path {path_id}: {path_str}")

        return {"success": True, "message": f"Deleted scan path: {path_str}"}
    except Exception as e:
        logger.error(f"Failed to delete scan path: {e}", exc_info=True)
        return {"error": str(e), "success": False}


@app.post("/api/orphan-cleanup/scan-filesystem")
async def scan_filesystem_for_orphans(dry_run: bool = False) -> dict:
    """Scan configured filesystem paths for orphaned files (deep scan).

    Uses filesystem-based detection across all configured scan paths,
    finding orphans regardless of processing history.

    Args:
        dry_run: If true, only report what would be quarantined

    Returns:
        Scan results with quarantined file counts
    """
    # Acquire scan lock — refuse if another scan is already running
    if not _scan_lock.acquire(blocking=False):
        return {
            "success": False,
            "error": (
                "A scan is already in progress. " "Please wait for it to finish."
            ),
            "orig_quarantined": 0,
            "srt_quarantined": 0,
        }

    try:
        from py_captions_for_channels.models import ScanPath
        from py_captions_for_channels.orphan_cleanup import (
            find_orphaned_files_by_filesystem,
            quarantine_orphaned_files,
        )

        db = next(get_db())

        # Get all enabled scan paths
        scan_paths = (
            db.query(ScanPath).filter(ScanPath.enabled == True).all()  # noqa: E712
        )

        if not scan_paths:
            return {
                "success": False,
                "error": ("No scan paths configured. " "Add scan paths in settings."),
                "orig_quarantined": 0,
                "srt_quarantined": 0,
            }

        all_orphaned_orig = []
        all_orphaned_srt = []

        # Scan each path
        for scan_path in scan_paths:
            label_txt = scan_path.label or "unlabeled"
            logger.info(
                f"Scanning path for orphans: " f"{scan_path.path} ({label_txt})"
            )
            files = find_orphaned_files_by_filesystem(scan_path.path)
            orig_files, srt_files = files
            all_orphaned_orig.extend(orig_files)
            all_orphaned_srt.extend(srt_files)

            # Update last scanned timestamp
            scan_path.last_scanned_at = datetime.now(timezone.utc)

        db.commit()

        # Quarantine the found orphans
        orig_count, srt_count, _skipped = quarantine_orphaned_files(
            all_orphaned_orig, all_orphaned_srt, dry_run=dry_run
        )

        logger.info(
            f"Filesystem scan complete: "
            f"{orig_count} .orig, {srt_count} .srt quarantined"
        )

        return {
            "success": True,
            "orig_quarantined": orig_count,
            "srt_quarantined": srt_count,
            "scanned_paths": len(scan_paths),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    except Exception as e:
        logger.error(f"Filesystem orphan scan failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    finally:
        _scan_lock.release()


@app.get("/api/orphan-cleanup/scan-filesystem/stream")
async def scan_filesystem_stream(dry_run: bool = False):
    """Stream deep scan progress via Server-Sent Events.

    Sends real-time progress events as each folder is scanned,
    including current folder name, folder number, and total count.
    Uses a lock to prevent concurrent scans from racing.
    Supports cancellation via /api/orphan-cleanup/scan-filesystem/cancel.
    """
    import queue as thread_queue

    from py_captions_for_channels.models import ScanPath
    from py_captions_for_channels.orphan_cleanup import (
        quarantine_orphaned_files,
        scan_filesystem_progressive,
    )

    _scan_cancel.clear()

    def generate():
        # Acquire scan lock — refuse if another scan is already running
        if not _scan_lock.acquire(blocking=False):
            evt = json.dumps(
                {
                    "phase": "error",
                    "message": (
                        "A scan is already in progress. "
                        "Please wait for it to finish."
                    ),
                }
            )
            yield f"data: {evt}\n\n"
            return

        try:
            db = next(get_db())

            scan_paths = (
                db.query(ScanPath).filter(ScanPath.enabled == True).all()  # noqa: E712
            )

            if not scan_paths:
                evt = json.dumps(
                    {
                        "phase": "error",
                        "message": (
                            "No scan paths configured. " "Add scan paths in settings."
                        ),
                    }
                )
                yield f"data: {evt}\n\n"
                return

            path_dicts = [{"path": sp.path, "label": sp.label} for sp in scan_paths]

            progress_q: thread_queue.Queue = thread_queue.Queue()

            def on_progress(info):
                progress_q.put(info)

            def is_cancelled():
                return _scan_cancel.is_set()

            # Run the scan in a background thread
            import concurrent.futures

            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                scan_filesystem_progressive,
                path_dicts,
                on_progress,
                cancel_check=is_cancelled,
            )

            # Drain progress events while scan runs
            while not future.done():
                try:
                    info = progress_q.get(timeout=0.1)
                    yield f"data: {json.dumps(info)}\n\n"
                except thread_queue.Empty:
                    continue

            # Drain remaining events
            while not progress_q.empty():
                info = progress_q.get_nowait()
                yield f"data: {json.dumps(info)}\n\n"

            # Get scan results
            try:
                all_orphaned_orig, all_orphaned_srt = future.result()
            except Exception as exc:
                evt = json.dumps({"phase": "error", "message": str(exc)})
                yield f"data: {evt}\n\n"
                executor.shutdown(wait=False)
                return

            executor.shutdown(wait=False)

            # If cancelled during scan, return partial results
            if _scan_cancel.is_set():
                result = {
                    "phase": "done",
                    "success": True,
                    "cancelled": True,
                    "orig_found": len(all_orphaned_orig),
                    "srt_found": len(all_orphaned_srt),
                    "total_found": len(all_orphaned_orig) + len(all_orphaned_srt),
                    "orig_quarantined": 0,
                    "srt_quarantined": 0,
                    "skipped": 0,
                    "scanned_paths": len(scan_paths),
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
                yield f"data: {json.dumps(result)}\n\n"
                return

            # Update last scanned timestamps
            for sp in scan_paths:
                sp.last_scanned_at = datetime.now(timezone.utc)
            db.commit()

            # Quarantine found orphans, with progress events streamed to client
            total_found = len(all_orphaned_orig) + len(all_orphaned_srt)

            # Run quarantine in a thread so we can stream progress
            quarantine_q: thread_queue.Queue = thread_queue.Queue()

            def quarantine_with_progress():
                return quarantine_orphaned_files(
                    all_orphaned_orig,
                    all_orphaned_srt,
                    dry_run=dry_run,
                    progress_callback=lambda info: quarantine_q.put(info),
                    cancel_check=is_cancelled,
                )

            q_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            q_future = q_executor.submit(quarantine_with_progress)

            # Drain quarantine progress events
            while not q_future.done():
                try:
                    info = quarantine_q.get(timeout=0.5)
                    yield f"data: {json.dumps(info)}\n\n"
                except thread_queue.Empty:
                    continue

            # Drain remaining quarantine events
            while not quarantine_q.empty():
                info = quarantine_q.get_nowait()
                yield f"data: {json.dumps(info)}\n\n"

            try:
                orig_count, srt_count, skipped_count = q_future.result()
            except Exception as exc:
                evt = json.dumps({"phase": "error", "message": str(exc)})
                yield f"data: {evt}\n\n"
                q_executor.shutdown(wait=False)
                return

            q_executor.shutdown(wait=False)

            result = {
                "phase": "done",
                "success": True,
                "cancelled": _scan_cancel.is_set(),
                "orig_found": len(all_orphaned_orig),
                "srt_found": len(all_orphaned_srt),
                "total_found": total_found,
                "orig_quarantined": orig_count,
                "srt_quarantined": srt_count,
                "skipped": skipped_count,
                "scanned_paths": len(scan_paths),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            yield f"data: {json.dumps(result)}\n\n"

        finally:
            _scan_lock.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/orphan-cleanup/scan-filesystem/cancel")
async def cancel_scan() -> dict:
    """Cancel an in-progress deep scan operation."""
    _scan_cancel.set()
    logger.info("Deep scan cancellation requested")
    return {"success": True, "message": "Cancel signal sent"}


@app.get("/api/quarantine")
async def get_quarantined_files() -> dict:
    """Get list of all files in quarantine.

    Returns:
        List of quarantined files with metadata
    """
    try:
        db = next(get_db())
        service = _build_quarantine_service(db)
        items = service.get_quarantined_files()
        stats = service.get_quarantine_stats()

        return {
            "items": [
                {
                    "id": item.id,
                    "original_path": item.original_path,
                    "quarantine_path": item.quarantine_path,
                    "file_type": item.file_type,
                    "recording_path": item.recording_path,
                    "file_size_bytes": item.file_size_bytes,
                    "reason": item.reason,
                    "status": item.status,
                    "created_at": item.created_at.isoformat() + "Z",
                    "expires_at": item.expires_at.isoformat() + "Z",
                    "is_expired": item.expires_at <= datetime.utcnow(),
                }
                for item in items
            ],
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Failed to get quarantined files: {e}", exc_info=True)
        return {"error": str(e), "items": [], "stats": {}}


@app.post("/api/quarantine/restore")
async def restore_quarantined_files(item_ids: list[int]) -> dict:
    """Restore selected files from quarantine to their original locations.

    Args:
        item_ids: List of QuarantineItem IDs to restore

    Returns:
        Result with counts of restored and failed items
    """
    try:
        db = next(get_db())
        service = _build_quarantine_service(db)

        restored = 0
        failed = 0
        errors = []

        for item_id in item_ids:
            try:
                if service.restore_file(item_id):
                    restored += 1
                else:
                    failed += 1
                    errors.append(f"Failed to restore item {item_id}")
            except Exception as e:
                failed += 1
                errors.append(f"Item {item_id}: {str(e)}")

        logger.info(f"Restored {restored} items from quarantine, {failed} failed")

        return {
            "success": True,
            "restored": restored,
            "failed": failed,
            "errors": errors if errors else None,
        }
    except Exception as e:
        logger.error(f"Failed to restore quarantined files: {e}", exc_info=True)
        return {"success": False, "error": str(e), "restored": 0, "failed": 0}


@app.post("/api/quarantine/delete")
async def delete_quarantined_files(item_ids: list[int]) -> dict:
    """Permanently delete selected files from quarantine (streaming SSE).

    Streams progress events so the UI can show real-time feedback
    and supports cancellation via /api/quarantine/delete/cancel.

    Args:
        item_ids: List of QuarantineItem IDs to delete

    Returns:
        SSE stream with progress and final result
    """
    _delete_cancel.clear()

    def generate():
        try:
            db = next(get_db())
            service = _build_quarantine_service(db)

            def cancel_check():
                return _delete_cancel.is_set()

            last_progress = None
            for (
                current,
                total,
                deleted,
                failed,
                cancelled,
            ) in service.delete_files_batch(
                item_ids,
                batch_size=200,
                cancel_check=cancel_check,
            ):
                last_progress = (current, total, deleted, failed, cancelled)
                event = {
                    "phase": "deleting",
                    "current": current,
                    "total": total,
                    "deleted": deleted,
                    "failed": failed,
                }
                yield f"data: {json.dumps(event)}\n\n"

            # Final result
            if last_progress:
                current, total, deleted, failed, cancelled = last_progress
            else:
                deleted, failed, cancelled = 0, 0, False

            done_event = {
                "phase": "done",
                "success": True,
                "deleted": deleted,
                "failed": failed,
                "cancelled": cancelled,
                "total": len(item_ids),
            }
            yield f"data: {json.dumps(done_event)}\n\n"

            logger.info(
                "Delete batch: deleted=%d, failed=%d, cancelled=%s",
                deleted,
                failed,
                cancelled,
            )

        except Exception as e:
            logger.error(f"Failed to delete quarantined files: {e}", exc_info=True)
            error_event = {"phase": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/quarantine/delete/cancel")
async def cancel_delete() -> dict:
    """Cancel an in-progress delete operation."""
    _delete_cancel.set()
    logger.info("Delete cancellation requested")
    return {"success": True, "message": "Cancel signal sent"}


@app.post("/api/quarantine/dedup")
async def dedup_quarantine() -> dict:
    """Remove duplicate quarantine entries.

    Returns:
        Deduplication results
    """
    try:
        db = next(get_db())
        service = _build_quarantine_service(db)
        result = service.deduplicate()
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Failed to deduplicate quarantine: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@app.get("/api/quarantine/stats")
async def get_quarantine_stats() -> dict:
    """Get quarantine statistics.

    Returns:
        Statistics about quarantined files
    """
    try:
        db = next(get_db())
        service = _build_quarantine_service(db)
        return service.get_quarantine_stats()
    except Exception as e:
        logger.error(f"Failed to get quarantine stats: {e}", exc_info=True)
        return {"error": str(e)}


@app.get("/api/config/filesystem-analysis")
async def get_filesystem_analysis() -> dict:
    """Analyse filesystem topology for quarantine performance.

    Returns per-filesystem info, quarantine directory mapping,
    disk usage, and warnings about cross-filesystem risks.
    """
    try:
        from py_captions_for_channels.config import QUARANTINE_DIR
        from py_captions_for_channels.models import ScanPath
        from py_captions_for_channels.services.filesystem_service import (
            FilesystemService,
        )

        db = next(get_db())
        fs_service = FilesystemService(fallback_quarantine_dir=QUARANTINE_DIR)

        scan_paths = (
            db.query(ScanPath).filter(ScanPath.enabled == True).all()  # noqa: E712
        )
        for sp in scan_paths:
            fs_service.register_path(sp.path)

        analysis = fs_service.get_analysis()
        analysis["success"] = True
        return analysis
    except Exception as e:
        logger.error(f"Filesystem analysis failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@app.get("/api/execution-history/info")
async def get_execution_history_info() -> dict:
    """Get information about execution history for cleanup decisions.

    Returns:
        Dict with execution count, oldest date, and cleanup history
    """
    try:
        from py_captions_for_channels.models import OrphanCleanupHistory

        tracker = get_tracker()
        executions = tracker.get_executions(limit=10000)

        oldest_date = None
        newest_date = None
        if executions:
            # Find oldest and newest
            dates = [e.get("started_at") for e in executions if e.get("started_at")]
            if dates:
                oldest_date = min(dates)
                newest_date = max(dates)

        # Get orphan cleanup history
        db = next(get_db())
        cleanup_records = (
            db.query(OrphanCleanupHistory)
            .order_by(OrphanCleanupHistory.cleanup_timestamp.desc())
            .limit(10)
            .all()
        )

        cleanup_history = []
        for record in cleanup_records:
            cleanup_history.append(
                {
                    "timestamp": record.cleanup_timestamp.isoformat() + "Z",
                    "orig_files_deleted": record.orig_files_deleted,
                    "srt_files_deleted": record.srt_files_deleted,
                }
            )

        oldest_cleanup = (
            db.query(OrphanCleanupHistory)
            .order_by(OrphanCleanupHistory.cleanup_timestamp.asc())
            .first()
        )

        return {
            "total_executions": len(executions),
            "oldest_execution": oldest_date,
            "newest_execution": newest_date,
            "cleanup_history": cleanup_history,
            "oldest_cleanup_date": (
                oldest_cleanup.cleanup_timestamp.isoformat() + "Z"
                if oldest_cleanup
                else None
            ),
        }
    except Exception as e:
        logger.error(f"Failed to get execution history info: {e}", exc_info=True)
        return {"error": str(e)}


@app.post("/api/execution-history/cleanup")
async def cleanup_execution_history(cutoff_date: str = None) -> dict:
    """Clean up execution history older than a specified date.

    Args:
        cutoff_date: ISO format date string (optional). If not provided,
            uses oldest cleanup date.

    Returns:
        Cleanup result with number of executions removed
    """
    try:
        from py_captions_for_channels.models import OrphanCleanupHistory

        tracker = get_tracker()

        if cutoff_date:
            # Parse user-provided date
            cutoff = datetime.fromisoformat(cutoff_date.replace("Z", "+00:00"))
            logger.info(
                f"Manual execution history cleanup requested with cutoff: {cutoff}"
            )
        else:
            # Use oldest cleanup date
            db = next(get_db())
            oldest_cleanup = (
                db.query(OrphanCleanupHistory)
                .order_by(OrphanCleanupHistory.cleanup_timestamp.asc())
                .first()
            )

            if oldest_cleanup:
                cutoff = oldest_cleanup.cleanup_timestamp
                logger.info(f"Using oldest cleanup date as cutoff: {cutoff}")
            else:
                # Fallback to 30 days ago
                cutoff = datetime.utcnow() - timedelta(days=30)
                logger.info(f"No cleanup history found, using 30-day default: {cutoff}")

        removed = tracker.clear_executions_before_date(cutoff)

        return {
            "success": True,
            "executions_removed": removed,
            "cutoff_date": cutoff.isoformat() + "Z",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        logger.error(f"Failed to clean execution history: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


def get_job_logs_from_file(job_id: str, max_lines: int = 500) -> list:
    """Extract log lines for a specific job from the main log file.

    Args:
        job_id: Job identifier to search for in log lines
        max_lines: Maximum number of log lines to return

    Returns:
        List of log lines matching the job_id
    """
    from collections import deque
    import json as json_module

    job_logs = deque(maxlen=max_lines)
    log_path = Path(LOG_FILE_READ)

    if not log_path.exists():
        return []

    try:
        # Read the log file and find lines containing job_id
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                # Try JSON format first (structured logger)
                if line.strip().startswith("{"):
                    try:
                        log_entry = json_module.loads(line.strip())
                        if log_entry.get("job_id") == job_id:
                            # Format as readable text: [timestamp] LEVEL: message
                            timestamp = log_entry.get("timestamp", "")[
                                :19
                            ]  # Remove timezone
                            level = log_entry.get("level", "INFO")
                            msg = log_entry.get("msg", "")
                            formatted = f"[{timestamp}] {level}: {msg}"
                            job_logs.append(formatted)
                    except json_module.JSONDecodeError:
                        # Not valid JSON, skip
                        pass
                # Also check traditional format [job_id] for backward compatibility
                elif f"[{job_id}]" in line:
                    job_logs.append(line.rstrip())
    except Exception as e:
        LOG.error("Error extracting job logs: %s", e)

    return list(job_logs)


@app.get("/api/executions/{job_id:path}")
async def get_execution_detail(job_id: str) -> dict:
    """Get detailed execution information including full logs.

    Args:
        job_id: Job identifier

    Returns:
        Execution detail dict
    """
    try:
        tracker = get_tracker()
        tracker.mark_stale_executions(timeout_seconds=STALE_EXECUTION_SECONDS)
        execution = tracker.get_execution(job_id)

        if execution:
            exec_copy = execution.copy()
            # Pre-format local times for display
            if exec_copy.get("started_at"):
                exec_copy["started_local"] = format_local(exec_copy["started_at"])
            if exec_copy.get("completed_at"):
                exec_copy["completed_local"] = format_local(exec_copy["completed_at"])

            # Extract job-specific logs from main log file
            job_logs = get_job_logs_from_file(job_id)
            if job_logs:
                exec_copy["logs_text"] = "\n".join(job_logs)
            else:
                exec_copy["logs_text"] = "No logs found for this job"

            return exec_copy
        else:
            return {"error": "Execution not found", "job_id": job_id}
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


@app.post("/api/executions/{job_id:path}/cancel")
async def cancel_execution(job_id: str) -> dict:
    """Request cancellation of a running execution."""
    try:
        tracker = get_tracker()
        execution = tracker.get_execution(job_id)
        ok = tracker.request_cancel(job_id)
        if not ok:
            return {"error": "Execution not found", "job_id": job_id}
        if (
            execution
            and execution.get("kind") == "manual_process"
            and execution.get("path")
        ):
            state_backend.clear_manual_process_request(execution["path"])
        return {"ok": True, "job_id": job_id}
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


@app.get("/api/recordings")
async def get_recordings() -> dict:
    """Get list of recordings from Channels DVR API.

    Fetches all recordings from the Channels DVR /api/v1/all endpoint
    sorted by date_added (most recent first).

    Returns:
        JSON with recordings list containing path, title, date_added, etc.
    """
    try:
        resp = requests.get(
            f"{CHANNELS_API_URL}/api/v1/all",
            params={"sort": "date_added", "order": "desc", "source": "recordings"},
            timeout=10,
        )
        resp.raise_for_status()
        recordings = resp.json()

        # Debug: Log field names only
        if recordings and len(recordings) > 0:
            LOG.debug(f"Received {len(recordings)} recordings from Channels DVR")
            LOG.debug(f"First recording keys: {list(recordings[0].keys())}")

        # Load whitelist from database for checking
        db = next(get_db())
        try:
            settings_service = SettingsService(db)
            whitelist_content = settings_service.get("whitelist", "")
            whitelist = Whitelist(content=whitelist_content)
        finally:
            db.close()

        # Get execution tracker to check processed status
        tracker = get_tracker()
        all_executions = tracker.get_executions(limit=1000)

        # Extract relevant fields for UI
        formatted_recordings = []
        for rec in recordings:
            if not rec.get("path"):
                continue

            path = rec.get("path", "")
            title = rec.get("title", "Unknown")
            episode_title = rec.get("episode_title", "")

            # Get recording start time from created_at (milliseconds timestamp)
            created_at = rec.get("created_at", 0)
            start_time = (
                datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
                if created_at
                else None
            )

            # Check whitelist (requires both title and start time)
            passes_whitelist = whitelist.is_allowed(title, start_time)

            # Check if processed (look for execution with this path)
            processed_exec = next(
                (e for e in all_executions if e.get("path") == path), None
            )
            processed_status = None
            if processed_exec:
                if processed_exec.get("status") == "completed":
                    processed_status = (
                        "success" if processed_exec.get("success") else "failed"
                    )

            # Check if .cc4chan.orig or legacy .orig backup file exists
            from pathlib import Path as FilePath

            has_orig = (
                FilePath(str(path) + ".cc4chan.orig").exists()
                or FilePath(str(path) + ".orig").exists()
            )

            formatted_recordings.append(
                {
                    "path": path,
                    "title": title,
                    "episode_title": episode_title,
                    "summary": rec.get("summary", ""),
                    "created_at": rec.get(
                        "created_at", 0
                    ),  # Unix timestamp in milliseconds
                    "original_air_date": rec.get("original_air_date", ""),
                    "duration": rec.get("duration", 0),
                    "completed": rec.get("completed", False),
                    "inprogress": rec.get(
                        "inprogress", False
                    ),  # Only true for actively recording
                    "passes_whitelist": passes_whitelist,
                    "processed": processed_status,  # None, 'success', or 'failed'
                    "has_orig": has_orig,  # Whether .orig backup file exists
                }
            )

        LOG.debug(f"Formatted {len(formatted_recordings)} recordings for UI")

        return {
            "recordings": formatted_recordings,
            "count": len(formatted_recordings),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        LOG.error(f"Error fetching recordings from Channels DVR API: {e}")
        return {
            "recordings": [],
            "count": 0,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@app.get("/api/manual-process/candidates")
async def get_manual_process_candidates() -> dict:
    """Get list of recordings that can be manually processed.

    Returns completed executions (both successful and failed).
    """
    try:
        tracker = get_tracker()
        all_executions = tracker.get_executions(limit=200)

        # Only show completed executions as candidates
        candidates = [
            {
                "path": exec["path"],
                "title": exec["title"],
                "started_at": exec["started_at"],
                "success": exec.get("success"),
                "error": exec.get("error"),
            }
            for exec in all_executions
            if exec.get("status") == "completed"
        ]

        return {
            "candidates": candidates,
            "count": len(candidates),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "candidates": [],
            "count": 0,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@app.post("/api/manual-process/add")
async def add_to_manual_process_queue(request: Request) -> dict:
    """Add paths to the manual process queue.

    Expects JSON body:
    {"paths": ["path1", ...], "skip_caption_generation": bool,
    "log_verbosity": str}
    """
    try:
        data = await request.json()
        paths = data.get("paths", [])
        skip_caption_generation = data.get("skip_caption_generation", False)
        log_verbosity = data.get("log_verbosity", "NORMAL")

        if not paths:
            return {"error": "No paths provided", "added": 0}

        tracker = get_tracker()

        # Add paths to manual process queue with settings
        for path in paths:
            state_backend.mark_for_manual_process(
                path, skip_caption_generation, log_verbosity
            )
            filename = path.split("/")[-1]
            title = f"Manual: {filename}"
            job_id = build_manual_process_job_id(path)
            existing = tracker.get_execution(job_id)
            # Only create pending execution if no active execution exists
            # Terminal states: completed, failed, cancelled, dry_run
            if not existing or existing.get("status") in (
                "completed",
                "failed",
                "cancelled",
                "dry_run",
            ):
                tracker.start_execution(
                    job_id,
                    title,
                    path,
                    datetime.now(timezone.utc).isoformat(),
                    status="pending",
                    kind="manual_process",
                )

        # Note: Web container does not process queue directly.
        # The main container polls the queue every ~5 seconds and processes items.
        # Items added here will be picked up automatically by the main container.

        return {
            "added": len(paths),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "added": 0}


@app.post("/api/manual-process/restore")
async def restore_recordings_from_backup(request: Request) -> dict:
    """Restore recordings from .orig backup files.

    This will:
    - Delete the processed video file (.mpg)
    - Rename the .orig file to .mpg (restore original)
    - Delete the caption file (.srt)

    Args:
        request: Contains paths array of recordings to restore

    Returns:
        Dict with restore statistics
    """
    try:
        data = await request.json()
        paths = data.get("paths", [])

        if not paths:
            return {"error": "No paths provided", "restored": 0}

        restored_count = 0
        errors = []

        for path in paths:
            try:
                from pathlib import Path as FilePath

                video_path = FilePath(path)
                orig_path = FilePath(str(path) + ".cc4chan.orig")
                legacy_orig_path = FilePath(str(path) + ".orig")
                srt_path = video_path.with_suffix(".srt")

                # Check for .cc4chan.orig first, then legacy .orig
                actual_orig = None
                if orig_path.exists():
                    actual_orig = orig_path
                elif legacy_orig_path.exists():
                    actual_orig = legacy_orig_path

                if not actual_orig:
                    errors.append(f"{path}: No backup file found")
                    continue

                # Delete the processed video file
                if video_path.exists():
                    video_path.unlink()
                    logger.info(f"Deleted processed file: {video_path}")

                # Restore backup to .mpg
                actual_orig.rename(video_path)
                logger.info(f"Restored backup {actual_orig} to {video_path}")

                # Delete .srt file if it exists
                if srt_path.exists():
                    srt_path.unlink()
                    logger.info(f"Deleted caption file: {srt_path}")

                restored_count += 1

            except Exception as e:
                error_msg = f"{path}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"Failed to restore {path}: {e}", exc_info=True)

        result = {
            "restored": restored_count,
            "total": len(paths),
            "errors": errors,
            "timestamp": datetime.now().isoformat(),
        }

        if errors:
            result["message"] = (
                f"Restored {restored_count}/{len(paths)} recordings "
                f"with {len(errors)} errors"
            )
        else:
            result["message"] = f"Successfully restored {restored_count} recording(s)"

        return result

    except Exception as e:
        logger.error(f"Restore recordings failed: {e}", exc_info=True)
        return {"error": str(e), "restored": 0}


@app.post("/api/manual-process/remove")
async def remove_from_manual_process_queue(request: Request) -> dict:
    """Remove a path from the manual process queue.

    Expects JSON body: {"path": "path/to/file.mpg"}
    """
    try:
        data = await request.json()
        path = data.get("path")

        if not path:
            return {"error": "No path provided", "removed": False}

        # Clear from state backend
        state_backend.clear_manual_process_request(path)

        # Remove execution if pending (completely delete it)
        tracker = get_tracker()
        job_id = build_manual_process_job_id(path)
        execution = tracker.get_execution(job_id)
        if execution and execution.get("status") == "pending":
            tracker.remove_execution(job_id)

        return {
            "removed": True,
            "path": path,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "removed": False}


@app.get("/api/logging/verbosity")
async def get_logging_verbosity() -> dict:
    """Get current logging verbosity setting."""
    try:
        verbosity = None
        path = Path(LOG_VERBOSITY_FILE)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                verbosity = data.get("verbosity")
        if not verbosity:
            verbosity = get_verbosity() or LOG_VERBOSITY
        return {"verbosity": str(verbosity).upper()}
    except Exception as e:
        return {"verbosity": LOG_VERBOSITY, "error": str(e)}


@app.post("/api/logging/verbosity")
async def set_logging_verbosity(request: Request) -> dict:
    """Update logging verbosity setting (shared across containers)."""
    try:
        data = await request.json()
        verbosity = str(data.get("verbosity", "")).upper()
        if verbosity not in ("MINIMAL", "NORMAL", "VERBOSE"):
            return {
                "error": "Invalid verbosity",
                "allowed": ["MINIMAL", "NORMAL", "VERBOSE"],
            }

        # Update web process logging
        set_verbosity(verbosity)

        # Persist to shared file for watcher to read
        path = Path(LOG_VERBOSITY_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"verbosity": verbosity}, f)

        return {"verbosity": verbosity}
    except Exception as e:
        return {"error": str(e)}


# --- System Monitor ---


@app.get("/api/monitor/latest")
async def get_monitor_latest() -> dict:
    """Get the most recent system metrics sample."""
    monitor = get_system_monitor()
    latest = monitor.get_latest()
    pipeline = get_pipeline_timeline()
    pipeline_status = pipeline.get_status()

    return {
        "metrics": latest,
        "pipeline": pipeline_status,
        "gpu_provider": monitor.get_gpu_provider_info(),
    }


@app.get("/api/monitor/window")
async def get_monitor_window(seconds: int = 300) -> dict:
    """Get system metrics for the last N seconds.

    Args:
        seconds: Number of seconds to retrieve (default 300 = 5 minutes)
    """
    monitor = get_system_monitor()
    window = monitor.get_window(seconds)

    return {"metrics": window, "gpu_provider": monitor.get_gpu_provider_info()}


# --- Shutdown Control ---


@app.post("/api/shutdown/immediate")
async def shutdown_immediate() -> dict:
    """Request immediate shutdown (kill switch).

    Stops all processing immediately and exits the application.
    Use for emergency shutdown.
    """
    try:
        shutdown_controller = get_shutdown_controller()
        shutdown_controller.request_immediate_shutdown(initiated_by="web_api")
        return {
            "status": "shutdown_requested",
            "type": "immediate",
            "message": "Immediate shutdown initiated. Application will exit now.",
        }
    except Exception as e:
        LOG.error("Error requesting immediate shutdown: %s", e, exc_info=True)
        return {"error": str(e)}


@app.post("/api/shutdown/graceful")
async def shutdown_graceful() -> dict:
    """Request graceful shutdown.

    Waits for currently running job to complete, then exits the application.
    No new jobs will be started after this is called.
    """
    try:
        shutdown_controller = get_shutdown_controller()
        shutdown_controller.request_graceful_shutdown(initiated_by="web_api")

        # Get current execution status to inform the user
        tracker = get_tracker()
        all_executions = tracker.get_executions(limit=1000)
        running = [e for e in all_executions if e.get("status") == "running"]

        message = "Graceful shutdown initiated. "
        if running:
            current_job = running[0].get("title", "Unknown")
            message += f"Will exit after completing: {current_job}"
        else:
            message += "No jobs currently running, will exit shortly."

        return {
            "status": "shutdown_requested",
            "type": "graceful",
            "message": message,
            "current_running_jobs": len(running),
        }
    except Exception as e:
        LOG.error("Error requesting graceful shutdown: %s", e, exc_info=True)
        return {"error": str(e)}


@app.get("/api/shutdown/status")
async def shutdown_status() -> dict:
    """Get current shutdown status."""
    try:
        shutdown_controller = get_shutdown_controller()
        return shutdown_controller.get_state()
    except Exception as e:
        LOG.error("Error getting shutdown status: %s", e, exc_info=True)
        return {"error": str(e)}


# =========================================================================
# Channels Files Audit (Experimental)
# =========================================================================


@app.get("/api/channels-files/enabled")
async def channels_files_enabled() -> dict:
    """Return whether the Channels Files audit feature is enabled."""
    return {"enabled": CHANNELS_FILES_ENABLED}


@app.get("/api/channels-files/audit/stream")
async def channels_files_audit_stream():
    """Stream Channels Files audit progress via Server-Sent Events.

    Fetches all file records from the Channels DVR API, then cross-
    references them with the filesystem to find missing and orphaned
    files.  Progress events are streamed in real time.
    """
    import concurrent.futures
    import queue as thread_queue

    from py_captions_for_channels.services.channels_files_service import (
        audit_files,
        fetch_deleted_files,
        fetch_dvr_files,
    )

    if not CHANNELS_FILES_ENABLED:

        def _disabled():
            evt = json.dumps(
                {
                    "phase": "error",
                    "message": "Channels Files feature is not "
                    "enabled. Set CHANNELS_FILES_ENABLED=true.",
                }
            )
            yield f"data: {evt}\n\n"

        return StreamingResponse(_disabled(), media_type="text/event-stream")

    _audit_cancel.clear()

    def generate():
        if not _audit_lock.acquire(blocking=False):
            evt = json.dumps(
                {
                    "phase": "error",
                    "message": "An audit is already in progress."
                    " Please wait for it to finish.",
                }
            )
            yield f"data: {evt}\n\n"
            return

        try:
            # Phase 0 — fetch file list from Channels DVR API
            msg = json.dumps(
                {
                    "phase": "fetching",
                    "message": "Fetching file list from " "Channels DVR API...",
                }
            )
            yield f"data: {msg}\n\n"

            try:
                dvr_files = fetch_dvr_files(CHANNELS_DVR_URL, timeout=60)
            except Exception as exc:
                evt = json.dumps(
                    {
                        "phase": "error",
                        "message": f"Failed to fetch DVR files: {exc}",
                    }
                )
                yield f"data: {evt}\n\n"
                return

            count = len(dvr_files)
            msg = json.dumps(
                {
                    "phase": "fetching",
                    "message": f"Retrieved {count} file records from API",
                }
            )
            yield f"data: {msg}\n\n"

            # Also fetch deleted/trashed files so they aren't
            # flagged as orphans while still on disk.
            deleted_files: list = []
            try:
                deleted_files = fetch_deleted_files(CHANNELS_DVR_URL, timeout=60)
            except Exception as exc:
                LOG.warning("Could not fetch deleted files: %s", exc)
            if deleted_files:
                msg = json.dumps(
                    {
                        "phase": "fetching",
                        "message": (
                            f"Retrieved {len(deleted_files)} deleted/"
                            f"trashed file records from API"
                        ),
                    }
                )
                yield f"data: {msg}\n\n"

            if _audit_cancel.is_set():
                done = json.dumps(
                    {
                        "phase": "done",
                        "success": True,
                        "cancelled": True,
                    }
                )
                yield f"data: {done}\n\n"
                return

            # Run audit in background thread with progress streaming
            progress_q: thread_queue.Queue = thread_queue.Queue()

            def on_progress(info):
                progress_q.put(info)

            def is_cancelled():
                return _audit_cancel.is_set()

            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                audit_files,
                dvr_files,
                DVR_RECORDINGS_PATH,
                deleted_files=deleted_files,
                progress_callback=on_progress,
                cancel_check=is_cancelled,
            )

            # Drain progress events while audit runs
            while not future.done():
                try:
                    info = progress_q.get(timeout=0.1)
                    yield f"data: {json.dumps(info)}\n\n"
                except thread_queue.Empty:
                    continue

            # Drain remaining events
            while not progress_q.empty():
                info = progress_q.get_nowait()
                yield f"data: {json.dumps(info)}\n\n"

            # Get final result
            try:
                result = future.result()
            except Exception as exc:
                evt = json.dumps({"phase": "error", "message": str(exc)})
                yield f"data: {evt}\n\n"
                executor.shutdown(wait=False)
                return

            executor.shutdown(wait=False)

            # Stream final result
            result["phase"] = "done"
            yield f"data: {json.dumps(result)}\n\n"

        finally:
            _audit_lock.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/channels-files/audit/cancel")
async def cancel_channels_files_audit() -> dict:
    """Cancel an in-progress Channels Files audit."""
    _audit_cancel.set()
    logger.info("Channels Files audit cancellation requested")
    return {"success": True, "message": "Cancel signal sent"}
