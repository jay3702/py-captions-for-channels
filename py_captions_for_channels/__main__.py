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
import time

import uvicorn

from .logging_config import configure_logging
from .config import LOG_VERBOSITY, LOG_FILE
from .watcher import main as watcher_main

# Configure logging with job markers, verbosity support, and file output
configure_logging(verbosity=LOG_VERBOSITY, log_file=LOG_FILE)

logger = logging.getLogger(__name__)


def _host_has_nvidia_gpu() -> bool:
    """/proc/driver/nvidia exists on the host when the NVIDIA kernel module is
    loaded.  It is readable from inside a standard Docker container (shared
    /proc namespace) even when the container runtime is plain runc with no GPU
    passthrough.  Returns True when the host GPU is present but the container
    was started without GPU access.
    """
    import os as _os

    return _os.path.isdir("/proc/driver/nvidia")


def _log_gpu_upgrade_hint() -> None:
    """Warn once that a host GPU exists but the container is in CPU mode."""
    whisper_device = os.getenv("WHISPER_DEVICE", "cpu").lower()
    nvidia_visible = os.getenv("NVIDIA_VISIBLE_DEVICES", "")
    if whisper_device != "cpu" or nvidia_visible:
        return  # Already configured (or mid-transition) — don't spam
    logger.warning(
        "Host has an NVIDIA GPU available but this container is running in CPU mode.\n"
        "  To enable GPU acceleration update .env and restart:\n"
        "    DOCKER_RUNTIME=nvidia\n"
        "    NVIDIA_VISIBLE_DEVICES=all\n"
        "    WHISPER_DEVICE=cuda\n"
        "  Then: docker compose down && docker compose up -d\n"
        "  Or re-run the installer: bash scripts/setup-linux.sh"
    )


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
                if _host_has_nvidia_gpu():
                    _log_gpu_upgrade_hint()
        except FileNotFoundError:
            logger.info(
                "No NVIDIA GPU detected (nvidia-smi not found) — running on CPU."
            )
            if _host_has_nvidia_gpu():
                _log_gpu_upgrade_hint()
        except Exception as e:
            logger.debug("GPU check failed: %s", e)

    except ImportError:
        logger.debug("PyTorch not available — skipping GPU check")


def check_media_mount() -> None:
    """Check that the recordings mount is accessible at startup.

    Probes LOCAL_PATH_PREFIX with a timeout so stale/hung mounts are caught
    (os.path.exists on a dead SMB mount can block indefinitely).
    Logs clear, actionable guidance referencing the specific host path when
    DVR_MEDIA_HOST_PATH is available.

    If the directory exists but is empty (0 entries), retries up to 3 times
    with a short delay — the bind mount may need a moment to propagate when
    the CIFS share was mounted just before the container started.
    """
    from .config import LOCAL_PATH_PREFIX

    mount_path = LOCAL_PATH_PREFIX
    if not mount_path:
        return  # No prefix mapping — same-machine deployment, nothing to check

    result: dict = {"ok": False, "entries": 0, "error": None}

    def _probe():
        try:
            result["entries"] = len(os.listdir(mount_path))
            result["ok"] = True
        except Exception as exc:
            result["error"] = str(exc)

    t = threading.Thread(target=_probe, daemon=True, name="MountCheck")
    t.start()
    t.join(timeout=5)

    if t.is_alive():
        # Mount exists but is hung — classic stale SMB/NFS symptom
        logger.error(
            "Recordings mount is not responding (hung after 5 s): %s\n"
            "  The path exists but cannot be read — this usually means the\n"
            "  underlying network share has disconnected.\n"
            "  %s\n"
            "  After remapping, restart: docker compose restart",
            mount_path,
            _remap_hint(),
        )
        return

    if result["ok"]:
        # If 0 entries, the bind mount may have been snapshotted before the
        # CIFS share finished mounting on the host.  Retry a few times.
        if result["entries"] == 0:
            for _retry in range(3):
                time.sleep(3)
                result["entries"] = 0
                r2: dict = {"ok": False, "entries": 0, "error": None}

                def _probe2():
                    try:
                        r2["entries"] = len(os.listdir(mount_path))
                        r2["ok"] = True
                    except Exception as exc:
                        r2["error"] = str(exc)

                t2 = threading.Thread(target=_probe2, daemon=True, name="MountCheck")
                t2.start()
                t2.join(timeout=5)
                if r2["ok"] and r2["entries"] > 0:
                    result["entries"] = r2["entries"]
                    break
            if result["entries"] == 0:
                logger.warning(
                    "Recordings mount is empty after retries: %s\n"
                    "  The CIFS share may not have finished mounting.\n"
                    "  Jobs will fail until the mount is available.\n"
                    "  Fix: ensure the share is mounted, then run:\n"
                    "    docker compose restart",
                    mount_path,
                )
                return
        logger.info(
            "Recordings mount OK: %s (%d entries visible)",
            mount_path,
            result["entries"],
        )
        return

    # Path missing or permission denied
    logger.error(
        "Recordings mount is not accessible: %s\n"
        "  Error: %s\n"
        "  %s\n"
        "  Recordings will not be found until this is resolved.\n"
        "  After remapping, restart: docker compose down -v && docker compose up -d",
        mount_path,
        result["error"],
        _remap_hint(),
    )


def _remap_hint() -> str:
    """Return an actionable remap hint using the configured host path if available."""
    from .config import DVR_MEDIA_HOST_PATH

    host_path = DVR_MEDIA_HOST_PATH or ""
    if not host_path:
        # Generic hint for Linux / non-Windows deployments
        return (
            "Check that the network share is mounted and accessible on the host,\n"
            "  then restart the container."
        )
    # Derive drive letter if the host path looks like a drive (e.g. Z:/ or Z:)
    drive = host_path.split(":")[0].upper() + ":" if ":" in host_path else host_path
    return (
        f"The Windows drive mapping for '{host_path}' appears to be missing.\n"
        f"  To check current mappings, run in PowerShell on the host:\n"
        f"    net use\n"
        f"  To remap (replace Z: with the correct drive letter):\n"
        f"    net use {drive}\\ \\\\SERVER\\SHARE"
        f" /user:USERNAME PASSWORD /persistent:yes\n"
        f"  Then update DVR_MEDIA_HOST_PATH in .env if the drive letter changed."
    )


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
    check_media_mount()

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
