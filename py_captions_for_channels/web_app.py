from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import STATE_FILE, DRY_RUN, LOG_FILE, CAPTION_COMMAND
from .state import StateBackend
from .execution_tracker import get_tracker

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


@app.get("/api/status")
async def status() -> dict:
    """Return pipeline status and statistics.

    Reads from state file to report:
    - Last timestamp processed
    - Reprocess queue size
    - Configuration snapshot
    - Dry-run mode status
    """
    try:
        # Reload state to get latest
        state_backend._load()

        last_ts = state_backend.last_ts
        reprocess_queue = state_backend.get_reprocess_queue()

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
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "app": "py-captions-for-channels",
            "version": "0.8.0-dev",
            "status": "error",
            "error": str(e),
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
            execution = tracker.get_execution(job_id)

            if execution:
                return execution
            else:
                return {"error": "Execution not found", "job_id": job_id}
        except Exception as e:
            return {"error": str(e), "job_id": job_id}
