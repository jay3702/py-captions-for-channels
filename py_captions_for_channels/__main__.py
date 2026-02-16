"""
Main entry point for py-captions-for-channels.

This allows running the package as a module:
    python -m py_captions_for_channels

Runs both the caption watcher and the web UI in a single process.
"""

import asyncio
import logging
import os
import threading

import uvicorn

from .logging_config import configure_logging
from .config import LOG_VERBOSITY, LOG_FILE
from .watcher import main as watcher_main

# Configure logging with job markers, verbosity support, and file output
configure_logging(verbosity=LOG_VERBOSITY, log_file=LOG_FILE)

logger = logging.getLogger(__name__)


def run_web_ui():
    """Run the FastAPI web UI using uvicorn."""
    web_port = int(os.getenv("WEB_UI_PORT", "8000"))
    logger.info(f"Starting web UI on port {web_port}")

    uvicorn.run(
        "py_captions_for_channels.web_app:app",
        host="0.0.0.0",
        port=web_port,
        log_level="info",
    )


async def main():
    """Run both the watcher and web UI concurrently."""
    logger.info("Starting py-captions-for-channels (watcher + web UI)")

    # Start web UI in a separate thread (uvicorn.run is blocking)
    web_thread = threading.Thread(target=run_web_ui, daemon=True, name="WebUI")
    web_thread.start()

    # Run the watcher in the main asyncio event loop
    await watcher_main()


if __name__ == "__main__":
    asyncio.run(main())
