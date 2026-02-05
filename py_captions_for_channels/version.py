"""Version and build information for py-captions-for-channels."""

from datetime import datetime

VERSION = "0.9.0"
BUILD_DATE = datetime.now().strftime("%Y-%m-%d")
BUILD_NUMBER = "2026-02-04+build14"  # Fix DRY_RUN default to false


def get_version_string():
    """Get full version string with build info."""
    return f"{VERSION}+{BUILD_NUMBER}"


def get_version_info():
    """Get version information as a dictionary."""
    return {
        "version": VERSION,
        "build_number": BUILD_NUMBER,
        "build_date": BUILD_DATE,
        "full_version": get_version_string(),
    }
