"""
Startup health checks for py-captions-for-channels.

Verifies that all required services and dependencies are available before
starting the main watcher loop.
"""

import logging
import shutil
from pathlib import Path

from .channels_api import ChannelsAPI
from .config import (
    CHANNELS_API_URL,
    LOG_FILE,
    STATE_FILE,
)

LOG = logging.getLogger(__name__)


async def check_channels_dvr(api: ChannelsAPI) -> bool:
    """Check if Channels DVR API is reachable.

    Returns True if API responds, False otherwise.
    """
    try:
        LOG.info("Checking Channels DVR API: %s", CHANNELS_API_URL)
        # Try a simple HTTP request to the API endpoint
        import requests

        response = requests.get(
            f"{api.base_url}/api/v1/all",
            params={"sort": "date_added", "order": "desc", "source": "recordings"},
            timeout=5.0,
        )
        response.raise_for_status()
        LOG.info("✓ Channels DVR API is reachable")
        return True
    except requests.exceptions.Timeout:
        LOG.error(
            "✗ Channels DVR API timeout - check CHANNELS_API_URL: %s",
            CHANNELS_API_URL,
        )
        return False
    except requests.exceptions.RequestException as e:
        LOG.error(
            "✗ Channels DVR API unreachable: %s - check CHANNELS_API_URL: %s",
            str(e),
            CHANNELS_API_URL,
        )
        return False
    except Exception as e:
        LOG.error(
            "✗ Channels DVR API error: %s - check CHANNELS_API_URL: %s",
            str(e),
            CHANNELS_API_URL,
        )
        return False


def check_state_file() -> bool:
    """Check if state file is readable and writable.

    Returns True if state file is accessible, False otherwise.
    """
    try:
        LOG.info("Checking state file: %s", STATE_FILE)
        path = Path(STATE_FILE)

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Try to read (will create empty file if doesn't exist)
        if path.exists():
            with open(path, "r") as f:
                f.read()
            LOG.info("✓ State file is readable")
        else:
            LOG.info("  State file doesn't exist yet (will be created on first run)")

        # Try to write a test
        path.touch()

        LOG.info("✓ State file is writable")
        return True
    except Exception as e:
        LOG.error("✗ State file access issue: %s", str(e))
        return False


def check_log_file() -> bool:
    """Check if log file directory is writable.

    Returns True if log file can be written, False otherwise.
    """
    try:
        LOG.info("Checking log file path: %s", LOG_FILE)
        path = Path(LOG_FILE)

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Try to write
        path.touch()

        LOG.info("✓ Log file is writable")
        return True
    except Exception as e:
        LOG.error("✗ Log file write issue: %s", str(e))
        return False





def check_ffprobe() -> bool:
    """Check if ffprobe is available (used for media duration probing).

    Returns True if ffprobe exists, False otherwise.
    """
    try:
        if shutil.which("ffprobe"):
            LOG.info("✓ ffprobe is available")
            return True

        LOG.warning("✗ ffprobe not found in PATH (media probing will fail)")
        return False
    except Exception:
        LOG.warning("  Could not verify ffprobe")
        return False


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available (used for transcoding).

    Returns True if ffmpeg exists, False otherwise.
    """
    try:
        if shutil.which("ffmpeg"):
            LOG.info("✓ ffmpeg is available")
            return True

        LOG.warning("✗ ffmpeg not found in PATH (transcoding will fail)")
        return False
    except Exception:
        LOG.warning("  Could not verify ffmpeg")
        return False


async def run_health_checks(api: ChannelsAPI) -> bool:
    """Run all health checks.

    Returns True if all critical checks pass, False if any fail.
    """
    LOG.info("=" * 60)
    LOG.info("Running startup health checks...")
    LOG.info("=" * 60)

    checks = [
        ("Channels DVR API", await check_channels_dvr(api)),
        ("State file", check_state_file()),
        ("Log file", check_log_file()),

        ("ffprobe", check_ffprobe()),
        ("ffmpeg", check_ffmpeg()),
    ]

    passed = sum(1 for _, result in checks if result)
    total = len(checks)

    LOG.info("=" * 60)
    LOG.info("Health checks: %d/%d passed", passed, total)

    if passed < total:
        LOG.warning("Some checks failed - service may not work correctly")

    # Critical checks: Channels DVR API must be reachable
    critical_checks = [result for name, result in checks if "Channels DVR" in name]
    if critical_checks and not critical_checks[0]:
        LOG.error("Critical: Channels DVR API is unreachable. Aborting startup.")
        return False

    LOG.info("=" * 60)
    return True
