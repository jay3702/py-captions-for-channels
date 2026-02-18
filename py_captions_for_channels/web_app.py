import json
import os
from datetime import datetime, timezone
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
    CHANNELWATCH_URL,
    LOG_VERBOSITY,
    LOG_VERBOSITY_FILE,
    USE_MOCK,
    USE_POLLING,
    DISCOVERY_MODE,
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

BASE_DIR = Path(__file__).parent
WEB_ROOT = BASE_DIR / "webui"
TEMPLATES_DIR = WEB_ROOT / "templates"
STATIC_DIR = WEB_ROOT / "static"

app = FastAPI(title="Py Captions Web GUI", version=VERSION)
state_backend = StateBackend(STATE_FILE)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_event():
    """Initialize database and system monitor on application startup."""
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


@app.on_event("shutdown")
async def shutdown_event():
    """Stop system monitor on application shutdown."""
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

        # Always read whitelist from file (not stored in DB)
        whitelist_path = Path(__file__).parent.parent / "whitelist.txt"
        try:
            with open(whitelist_path, "r", encoding="utf-8") as f:
                all_settings["whitelist"] = f.read()
        except Exception:
            all_settings["whitelist"] = ""

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

        # Extract whitelist before saving (stored separately in file)
        whitelist_content = settings.pop("whitelist", None)

        # Save non-whitelist settings to database
        settings_service.set_many(settings)

        # Save whitelist to file
        if whitelist_content is not None:
            whitelist_path = Path(__file__).parent.parent / "whitelist.txt"
            with open(whitelist_path, "w", encoding="utf-8") as f:
                f.write(whitelist_content)

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

            # Collect comment lines as description
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

            # Parse setting line (active or commented)
            elif "=" in line_stripped and current_category:
                # Handle "KEY=value" and "# KEY=value" (commented optional)
                is_commented = line_stripped.startswith("#")
                setting_line = line_stripped.lstrip("#").strip()

                if "=" in setting_line:
                    key, value = setting_line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

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
                f".env.example not found at {env_example_path}, falling back to .env only"
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
            LOG.debug(
                f"Actual loaded: {sum(len(v) for v in actual.values())} settings"
            )

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

        LOG.info(
            f"Loaded settings: {sum(len(v) for v in merged.values())} settings across {len(merged)} categories"
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
                        found = True
                        break

                if not found:
                    # Keep original if not in update
                    new_lines.append(line)
            else:
                new_lines.append(line)

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
            LOG.info(f"Received {len(recordings)} recordings from Channels DVR")
            LOG.info(f"First recording keys: {list(recordings[0].keys())}")

        # Load whitelist for checking
        whitelist_path = Path(__file__).parent.parent / "whitelist.txt"
        whitelist = Whitelist(str(whitelist_path) if whitelist_path.exists() else None)

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
                    "passes_whitelist": passes_whitelist,
                    "processed": processed_status,  # None, 'success', or 'failed'
                }
            )

        LOG.info(f"Formatted {len(formatted_recordings)} recordings for UI")

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
