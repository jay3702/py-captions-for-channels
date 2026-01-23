from datetime import datetime
from pathlib import Path
import socket
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests

from .config import (
    STATE_FILE,
    DRY_RUN,
    LOG_FILE,
    CAPTION_COMMAND,
    STALE_EXECUTION_SECONDS,
    CHANNELS_API_URL,
    CHANNELWATCH_URL,
)
from .state import StateBackend
from .execution_tracker import get_tracker

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


def format_local(ts: str) -> str:
    """Format an ISO timestamp into server local time for display."""
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        dt_local = dt.astimezone()
        return dt_local.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
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

            # Prepare joined logs text for UI convenience
            if exec_copy.get("logs"):
                exec_copy["logs_text"] = "\n".join(
                    [
                        log.get("message", "") if isinstance(log, dict) else str(log)
                        for log in exec_copy["logs"]
                    ]
                )

            return exec_copy
        else:
            return {"error": "Execution not found", "job_id": job_id}
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

        # Add paths to reprocess queue
        for path in paths:
            state_backend.mark_for_reprocess(path)

        return {
            "added": len(paths),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "added": 0}
