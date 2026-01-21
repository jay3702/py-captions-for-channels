from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
WEB_ROOT = BASE_DIR / "webui"
TEMPLATES_DIR = WEB_ROOT / "templates"
STATIC_DIR = WEB_ROOT / "static"

app = FastAPI(title="Py Captions Web GUI", version="0.8.0-dev")

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
    """Simple placeholder status endpoint.

    TODO: Wire to real pipeline state (queue depth, last run, GPU availability, etc.).
    """
    return {
        "app": "py-captions-for-channels",
        "version": "0.8.0-dev",
        "status": "ok",
        "notes": "Replace with live pipeline stats",
    }


@app.get("/api/logs")
async def logs_stub() -> dict:
    """Placeholder for log streaming endpoint.

    Future: switch to Server-Sent Events or WebSockets for live logs.
    """
    return {"items": ["Log streaming not yet implemented"]}
