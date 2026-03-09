"""Version and build information for py-captions-for-channels.

Single source of truth for version numbering.  Follows semantic versioning:
    MAJOR.MINOR.BUILD

Update VERSION here before committing a release.  The Docker publish
workflow and pyproject.toml both read from this file (indirectly).
"""

import os
import subprocess
from datetime import datetime

VERSION = "1.0.2"


def _git_short_sha() -> str:
    """Return the short git commit SHA, or 'unknown' outside a repo."""
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return os.getenv("GIT_SHA", "unknown")[:7]


GIT_SHA = _git_short_sha()
BUILD_DATE = datetime.now().strftime("%Y-%m-%d")
# BUILD_NUMBER kept for backward compatibility with the web UI JS
BUILD_NUMBER = GIT_SHA


def get_version_string() -> str:
    """Get full version string, e.g. '1.0.0.abc1234'."""
    return f"{VERSION}.{GIT_SHA}"


def get_version_info() -> dict:
    """Get version information as a dictionary."""
    return {
        "version": VERSION,
        "git_sha": GIT_SHA,
        "build_number": BUILD_NUMBER,
        "build_date": BUILD_DATE,
        "full_version": get_version_string(),
    }
