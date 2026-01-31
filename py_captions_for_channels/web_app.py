import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None
from fastapi import FastAPI, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import logging
import threading
from .config import (
    STATE_FILE,
    DRY_RUN,
    LOG_FILE,
    CAPTION_COMMAND,
    STALE_EXECUTION_SECONDS,
    CHANNELS_API_URL,
    CHANNELWATCH_URL,
    LOG_VERBOSITY,
    LOG_VERBOSITY_FILE,
)
from .state import StateBackend
from .execution_tracker import build_reprocess_job_id, get_tracker
from .logging_config import get_verbosity, set_verbosity

BASE_DIR = Path(__file__).parent
WEB_ROOT = BASE_DIR / "webui"
TEMPLATES_DIR = WEB_ROOT / "templates"
STATIC_DIR = WEB_ROOT / "static"

app = FastAPI(title="Py Captions Web GUI", version="0.8.0-dev")
state_backend = StateBackend(STATE_FILE)

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
    return templates.TemplateResponse("index.html", {"request": request})


# --- Pipeline Settings API ---


# --- Service Health Check Helper ---
def check_service_health(url: str):
    """
    Check if a service at the given URL is reachable.
    Returns (healthy: bool, message: str).
    """
    import requests

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


def load_settings():
    # Try to load from settings.json
    if SETTINGS_PATH.exists():
        with SETTINGS_LOCK, open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
        # Always update whitelist from project root whitelist.txt
        whitelist_path = Path(__file__).parent.parent / "whitelist.txt"
        try:
            with open(whitelist_path, "r", encoding="utf-8") as f:
                settings["whitelist"] = f.read()
        except Exception:
            settings["whitelist"] = ""
        return settings
    # Fallback: initialize from .env/defaults
    env_path = Path(__file__).parent.parent / ".env"
    env_vars = {}
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.strip().startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()

    def env_bool(key, default):
        return env_vars.get(key, str(default)).lower() in ("true", "1", "yes", "on")

    settings = {
        "dry_run": env_bool("DRY_RUN", DRY_RUN),
        "keep_original": env_bool("KEEP_ORIGINAL", True),
        "transcode_for_firetv": env_bool("TRANSCODE_FOR_FIRETV", False),
        "log_verbosity": env_vars.get("LOG_VERBOSITY", LOG_VERBOSITY),
        "whisper_model": env_vars.get(
            "WHISPER_MODEL", os.getenv("WHISPER_MODEL", "medium")
        ),
        "whitelist": "",
    }
    # Always read whitelist from project root whitelist.txt
    whitelist_path = Path(__file__).parent.parent / "whitelist.txt"
    try:
        with open(whitelist_path, "r", encoding="utf-8") as f:
            settings["whitelist"] = f.read()
    except Exception:
        settings["whitelist"] = ""
    # Save to settings.json for future use
    save_settings(settings)
    return settings


def save_settings(settings: dict):
    with SETTINGS_LOCK, open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    # Also update .env as backup
    env_path = Path(__file__).parent.parent / ".env"
    log_verbosity = settings.get("log_verbosity", "NORMAL").upper()
    transcode_firetv = "true" if settings.get("transcode_for_firetv") else "false"
    env_lines = [
        f"DRY_RUN={'true' if settings.get('dry_run') else 'false'}\n",
        f"KEEP_ORIGINAL={'true' if settings.get('keep_original') else 'false'}\n",
        f"TRANSCODE_FOR_FIRETV={transcode_firetv}\n",
        f"LOG_VERBOSITY={log_verbosity}\n",
        f"WHISPER_MODEL={settings.get('whisper_model', 'medium')}\n",
    ]
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(env_lines)
    # Whitelist is managed separately
    if "whitelist" in settings:
        whitelist_path = Path(__file__).parent.parent / "whitelist.txt"
        with open(whitelist_path, "w", encoding="utf-8") as f:
            f.write(settings["whitelist"])


@app.get("/api/settings")
async def get_settings() -> dict:
    """Get pipeline settings and whitelist from settings.json."""
    try:
        return load_settings()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/settings")
async def set_settings(data: dict = Body(...)) -> dict:
    """Update pipeline settings and whitelist in settings.json and .env."""
    try:
        allowed = {
            "dry_run",
            "keep_original",
            "transcode_for_firetv",
            "log_verbosity",
            "whisper_model",
            "whitelist",
        }
        current = load_settings()
        for k in allowed:
            if k in data:
                current[k] = data[k]
        save_settings(current)
        return {"ok": True}
    except Exception as e:
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
    - Reprocess queue size
    - Configuration snapshot
    - Dry-run mode status
    - Service health (Channels DVR, ChannelWatch)
    """
    try:
        # Reload state to get latest
        state_backend._load()

        last_ts = state_backend.last_ts
        reprocess_queue = state_backend.get_reprocess_queue()

        # Check service health
        channels_healthy, channels_msg = check_service_health(CHANNELS_API_URL)
        channelwatch_healthy, channelwatch_msg = check_service_health(CHANNELWATCH_URL)

        settings = load_settings()
        return {
            "app": "py-captions-for-channels",
            "version": "0.8.0-dev",
            "status": "running",
            "dry_run": settings.get("dry_run", False),
            "keep_original": settings.get("keep_original", True),
            "transcode_for_firetv": settings.get("transcode_for_firetv", False),
            "log_verbosity": settings.get("log_verbosity", "NORMAL"),
            "whisper_model": settings.get("whisper_model", "medium"),
            "last_processed": last_ts.isoformat() if last_ts else None,
            "reprocess_queue_size": len(reprocess_queue),
            "caption_command": (
                CAPTION_COMMAND[:50] + "..."
                if len(CAPTION_COMMAND) > 50
                else CAPTION_COMMAND
            ),
            "log_file": str(LOG_FILE),
            "timezone": str(LOCAL_TZ) if LOCAL_TZ else "system-default",
            "services": {
                "channels_dvr": {
                    "name": "Channels DVR",
                    "url": CHANNELS_API_URL,
                    "healthy": channels_healthy,
                    "status": channels_msg,
                },
                "channelwatch": {
                    "name": "ChannelWatch",
                    "url": CHANNELWATCH_URL,
                    "healthy": channelwatch_healthy,
                    "status": channelwatch_msg,
                },
            },
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "app": "py-captions-for-channels",
            "version": "0.8.0-dev",
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
    log_path = Path(LOG_FILE)

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
        items = [f"Log file not found: {LOG_FILE}"]

    return {
        "items": items,
        "count": len(items),
        "log_file": str(LOG_FILE),
        "timestamp": datetime.now().isoformat(),
    }


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


def get_job_logs_from_file(job_id: str, max_lines: int = 500) -> list:
    """Extract log lines for a specific job from the main log file.

    Args:
        job_id: Job identifier to search for in log lines
        max_lines: Maximum number of log lines to return

    Returns:
        List of log lines matching the job_id
    """
    from collections import deque

    job_logs = deque(maxlen=max_lines)
    log_path = Path(LOG_FILE)

    if not log_path.exists():
        return []

    try:
        # Read the log file and find lines containing [job_id]
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if f"[{job_id}]" in line:
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
        if execution and execution.get("kind") == "reprocess" and execution.get("path"):
            state_backend.clear_reprocess_request(execution["path"])
        return {"ok": True, "job_id": job_id}
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


@app.get("/api/reprocess/candidates")
async def get_reprocess_candidates() -> dict:
    """Get list of recordings that can be reprocessed.

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


@app.post("/api/reprocess/add")
async def add_to_reprocess_queue(request: Request) -> dict:
    """Add paths to the reprocess queue.

    Expects JSON body: {"paths": ["path1", "path2", ...]}
    """
    try:
        data = await request.json()
        paths = data.get("paths", [])

        if not paths:
            return {"error": "No paths provided", "added": 0}

        tracker = get_tracker()

        # Add paths to reprocess queue
        for path in paths:
            state_backend.mark_for_reprocess(path)
            filename = path.split("/")[-1]
            title = f"Reprocess: {filename}"
            job_id = build_reprocess_job_id(path)
            existing = tracker.get_execution(job_id)
            if not existing or existing.get("status") != "running":
                tracker.start_execution(
                    job_id,
                    title,
                    path,
                    datetime.now(timezone.utc).isoformat(),
                    status="pending",
                    kind="reprocess",
                )

        # Optionally trigger reprocess queue immediately (if running in main process)
        try:
            from py_captions_for_channels import watcher
            from py_captions_for_channels.pipeline import Pipeline
            from py_captions_for_channels.parser import Parser
            from py_captions_for_channels.channels_api import ChannelsAPI
            from py_captions_for_channels.config import (
                CAPTION_COMMAND,
                DRY_RUN,
                CHANNELS_API_URL,
            )
            import asyncio

            # Initialize required objects
            pipeline = Pipeline(CAPTION_COMMAND, dry_run=DRY_RUN)
            parser = Parser()
            api = ChannelsAPI(CHANNELS_API_URL)

            # Fire and forget (non-blocking)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(
                    watcher.process_reprocess_queue(
                        state_backend, pipeline, api, parser
                    )
                )
        except Exception as e:
            LOG.warning(f"Could not auto-trigger reprocess queue: {e}")

        return {
            "added": len(paths),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "added": 0}


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
