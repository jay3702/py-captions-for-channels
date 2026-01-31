from fastapi import Body
from .config import WHITELIST_FILE
# --- Pipeline Settings API ---
@app.get("/api/settings")
async def get_settings() -> dict:
    """Get pipeline settings and whitelist."""
    try:
        # Read .env-driven settings
        settings = {
            "dry_run": DRY_RUN,
            "keep_original": os.getenv("KEEP_ORIGINAL", "true").lower() in ("true", "1", "yes", "on"),
            "transcode_for_firetv": os.getenv("TRANSCODE_FOR_FIRETV", "false").lower() in ("true", "1", "yes", "on"),
            "log_verbosity": LOG_VERBOSITY,
            "whisper_model": os.getenv("WHISPER_MODEL", "medium"),
        }
        # Read whitelist
        whitelist = ""
        try:
            with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
                whitelist = f.read()
        except Exception:
            whitelist = ""
        settings["whitelist"] = whitelist
        return settings
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/settings")
async def set_settings(data: dict = Body(...)) -> dict:
    """Update pipeline settings and whitelist."""
    try:
        # Only allow updating known settings
        allowed = {"dry_run", "keep_original", "transcode_for_firetv", "log_verbosity", "whisper_model", "whitelist"}
        updates = {k: v for k, v in data.items() if k in allowed}
        # Update .env file (append or replace lines)
        env_path = Path(__file__).parent.parent / ".env"
        env_lines = []
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                env_lines = f.readlines()
        env_dict = {}
        for line in env_lines:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_dict[k.strip()] = v.strip()
        # Update values
        if "dry_run" in updates:
            env_dict["DRY_RUN"] = "true" if updates["dry_run"] else "false"
        if "keep_original" in updates:
            env_dict["KEEP_ORIGINAL"] = "true" if updates["keep_original"] else "false"
        if "transcode_for_firetv" in updates:
            env_dict["TRANSCODE_FOR_FIRETV"] = "true" if updates["transcode_for_firetv"] else "false"
        if "log_verbosity" in updates:
            env_dict["LOG_VERBOSITY"] = updates["log_verbosity"].upper()
        if "whisper_model" in updates:
            env_dict["WHISPER_MODEL"] = updates["whisper_model"]
        # Write back .env
        with open(env_path, "w", encoding="utf-8") as f:
            for k, v in env_dict.items():
                f.write(f"{k}={v}\n")
        # Update whitelist file
        if "whitelist" in updates:
            with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
                f.write(updates["whitelist"])
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}
import json
import logging
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

import requests
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio

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

LOG = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
WEB_ROOT = BASE_DIR / "webui"
TEMPLATES_DIR = WEB_ROOT / "templates"
STATIC_DIR = WEB_ROOT / "static"

app = FastAPI(title="Py Captions Web GUI", version="0.8.0-dev")

# Initialize state backend for reading pipeline state
state_backend = StateBackend(STATE_FILE)

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

# --- WebSocket endpoint for real-time log streaming ---
@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint to stream new log lines in real time."""
    await websocket.accept()
    log_path = Path(LOG_FILE)
    last_size = 0
    try:
        while True:
            if log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(0, 2)  # Move to end of file
                        file_size = f.tell()
                        if file_size < last_size:
                            # Log rotated or truncated
                            last_size = 0
                        if file_size > last_size:
                            f.seek(last_size)
                            new_lines = f.read().splitlines()
                            for line in new_lines:
                                await websocket.send_text(line)
                            last_size = f.tell()
                except Exception as e:
                    await websocket.send_text(f"[Log stream error] {e}")
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        LOG.warning(f"WebSocket log stream error: {e}")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    """Render the main dashboard shell."""
    return templates.TemplateResponse("index.html", {"request": request})


def check_service_health(url: str, timeout: int = 2) -> tuple[bool, str]:
    """Check if a service is reachable.

    Returns tuple of (is_healthy, diagnostic_message).

    Args:
        url: Service URL to check (HTTP, HTTPS, or WS/WSS)
        timeout: Request timeout in seconds

    Returns:
        Tuple of (bool: healthy, str: diagnostic message)
    """
    if not url:
        return (False, "No URL configured")

    try:
        # Handle WebSocket URLs by extracting host/port and testing connectivity
        if url.startswith("ws://") or url.startswith("wss://"):
            # Extract host and port from WebSocket URL
            url_without_scheme = url.replace("wss://", "").replace("ws://", "")
            host_port = url_without_scheme.split("/")[0]

            if ":" in host_port:
                host, port_str = host_port.rsplit(":", 1)
                try:
                    port = int(port_str)
                except ValueError:
                    return (False, f"Invalid port in URL: {url}")
            else:
                host = host_port
                port = 8501

            # Test TCP connectivity
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            try:
                result = sock.connect_ex((host, port))
                if result == 0:
                    return (True, f"Connected to {host}:{port}")
                else:
                    return (False, f"Connection refused: {host}:{port}")
            finally:
                sock.close()
        else:
            # Handle HTTP/HTTPS URLs
            try:
                resp = requests.get(url, timeout=timeout, allow_redirects=False)
                if resp.status_code < 500:
                    return (True, f"HTTP {resp.status_code}")
                else:
                    return (False, f"HTTP {resp.status_code}")
            except requests.exceptions.Timeout:
                return (True, "Responding but slow (timeout)")
            except requests.exceptions.ConnectionError as e:
                return (False, f"Connection error: {str(e)[:50]}")
    except Exception as e:
        msg = str(e)[:50]
        return (True, f"Health check skipped: {msg}")


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

        return {
            "app": "py-captions-for-channels",
            "version": "0.8.0-dev",
            "status": "running",
            "dry_run": DRY_RUN,
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
