"""
Main entry point for py-captions-for-channels.

This allows running the package as a module:
    python -m py_captions_for_channels

Runs both the caption watcher and the web UI in a single process.
"""

import asyncio
import logging
import os
import subprocess
import sys
import threading

import uvicorn

from .logging_config import configure_logging
from .config import LOG_VERBOSITY, LOG_FILE
from .watcher import main as watcher_main

# Configure logging with job markers, verbosity support, and file output
configure_logging(verbosity=LOG_VERBOSITY, log_file=LOG_FILE)

logger = logging.getLogger(__name__)


def check_gpu_compatibility() -> None:
    """Check GPU/CUDA compatibility and log a clear warning if there's a mismatch.

    The container's CUDA version must be <= the maximum CUDA version supported
    by the host driver.  A mismatch causes silent CPU fallback which makes jobs
    much slower without an obvious error message.
    """
    try:
        import torch

        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            logger.info(
                "GPU ready: %s (CUDA %s, PyTorch %s)",
                device_name,
                torch.version.cuda,
                torch.__version__,
            )
            return

        # CUDA not available — check whether there's a GPU at all
        try:
            smi = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if smi.returncode == 0 and smi.stdout.strip():
                gpu_info = smi.stdout.strip().splitlines()[0]
                # Get max CUDA version the host driver supports
                smi2 = subprocess.run(
                    ["nvidia-smi", "--query-gpu=cuda_version", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                driver_cuda = (
                    smi2.stdout.strip().splitlines()[0]
                    if smi2.returncode == 0
                    else "unknown"
                )
                container_cuda = getattr(torch.version, "cuda", "unknown")
                logger.warning(
                    "GPU detected but CUDA unavailable"
                    " — likely a driver/image mismatch.\n"
                    "  GPU: %s\n"
                    "  Host driver supports CUDA: %s\n"
                    "  Container built for CUDA: %s\n"
                    "  Jobs will run on CPU (much slower).\n"
                    "  Fix: upgrade host driver to support CUDA %s, "
                    "or use an image built for CUDA %s.",
                    gpu_info,
                    driver_cuda,
                    container_cuda,
                    container_cuda,
                    driver_cuda,
                )
            else:
                logger.info("No NVIDIA GPU detected — running on CPU.")
        except FileNotFoundError:
            logger.info(
                "No NVIDIA GPU detected (nvidia-smi not found) — running on CPU."
            )
        except Exception as e:
            logger.debug("GPU check failed: %s", e)

    except ImportError:
        logger.debug("PyTorch not available — skipping GPU check")


def run_web_ui():
    """Run the FastAPI web UI using uvicorn."""
    web_port = int(os.getenv("WEB_UI_PORT", "8000"))
    logger.info(f"Starting web UI on port {web_port}")

    uvicorn.run(
        "py_captions_for_channels.web_app:app",
        host="0.0.0.0",
        port=web_port,
        log_level="warning",  # Suppress INFO-level HTTP access logs
    )


async def main():
    """Run both the watcher and web UI concurrently."""
    from .version import get_version_string

    logger.info(
        "Starting py-captions-for-channels %s (watcher + web UI)",
        get_version_string(),
    )

    check_gpu_compatibility()

    # Start web UI in a separate thread (uvicorn.run is blocking)
    web_thread = threading.Thread(target=run_web_ui, daemon=True, name="WebUI")
    web_thread.start()

    # Run the watcher in the main asyncio event loop
    await watcher_main()

    # Watcher returned (shutdown requested) — exit so Docker can restart us
    logger.info("Watcher exited — terminating process for restart")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
