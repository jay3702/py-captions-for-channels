"""Filesystem topology detection and distributed quarantine directory management.

Implements a Windows Recycle Bin–style architecture: each filesystem that
contains scan paths gets its own quarantine directory, so ``os.rename()``
is always an instant same-FS operation.

Usage::

    from py_captions_for_channels.services.filesystem_service import (
        FilesystemService,
    )

    fs = FilesystemService(fallback_quarantine_dir="/app/data/quarantine")
    fs.register_path("/tank/AllMedia/Channels")
    fs.register_path("/mnt/library2/TV")

    # Get the right quarantine dir for a file
    qdir = fs.quarantine_dir_for("/tank/AllMedia/Channels/TV/ep1/ep1.orig.mpg")
    # → "/tank/AllMedia/Channels/.py-captions-quarantine"  (same FS, instant rename)
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

LOG = logging.getLogger(__name__)

# Name for auto-created quarantine directories.
# Dot-prefixed so media apps ignore it.
QUARANTINE_DIRNAME = ".py-captions-quarantine"


@dataclass
class FilesystemInfo:
    """Information about a single filesystem (st_dev)."""

    st_dev: int
    quarantine_dir: str
    scan_paths: List[str] = field(default_factory=list)
    total_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    used_bytes: Optional[int] = None

    @property
    def free_pct(self) -> Optional[float]:
        if self.total_bytes and self.total_bytes > 0:
            return round(self.free_bytes / self.total_bytes * 100, 1)
        return None


class FilesystemService:
    """Detect filesystem topology and manage per-FS quarantine directories.

    Each registered scan path is stat'd to discover its ``st_dev``.  Paths
    that share a device get a single quarantine directory placed at the root
    of the *first* registered path on that device.

    A fallback quarantine directory (the legacy ``QUARANTINE_DIR``) is used
    for files whose device doesn't match any registered scan path.
    """

    def __init__(self, fallback_quarantine_dir: str):
        self.fallback_dir = fallback_quarantine_dir
        # st_dev → FilesystemInfo
        self._filesystems: Dict[int, FilesystemInfo] = {}
        # Ordered list of (scan_path, st_dev) for longest-prefix matching
        self._scan_paths: List[tuple] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_path(self, path: str) -> Optional[FilesystemInfo]:
        """Register a scan path and auto-discover its filesystem.

        Creates a ``.py-captions-quarantine`` directory at *path* if this
        is the first scan path registered on its device.

        Returns the FilesystemInfo, or None if the path doesn't exist.
        """
        p = Path(path)
        if not p.exists():
            LOG.warning("Scan path does not exist, skipping: %s", path)
            return None

        try:
            st = p.stat()
        except OSError as exc:
            LOG.warning("Cannot stat scan path %s: %s", path, exc)
            return None

        dev = st.st_dev

        if dev not in self._filesystems:
            # First path on this device — quarantine dir lives here
            quarantine_dir = str(p / QUARANTINE_DIRNAME)
            try:
                Path(quarantine_dir).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                LOG.error("Cannot create quarantine dir %s: %s", quarantine_dir, exc)
                quarantine_dir = self.fallback_dir

            info = FilesystemInfo(st_dev=dev, quarantine_dir=quarantine_dir)
            self._filesystems[dev] = info
            LOG.info("Filesystem st_dev=%d: quarantine dir → %s", dev, quarantine_dir)
        else:
            info = self._filesystems[dev]

        # Track this scan path
        if path not in info.scan_paths:
            info.scan_paths.append(path)
        self._scan_paths.append((path, dev))

        return info

    def register_paths(self, paths: List[str]) -> None:
        """Register multiple scan paths at once."""
        for p in paths:
            self.register_path(p)

    # ------------------------------------------------------------------
    # Quarantine directory lookup
    # ------------------------------------------------------------------

    def quarantine_dir_for(self, file_path: str) -> str:
        """Return the quarantine directory for *file_path*.

        Prefers same-device match.  Falls back to the legacy
        ``QUARANTINE_DIR`` if the file lives on an unknown device.
        """
        try:
            dev = os.stat(file_path).st_dev
        except OSError:
            # File may already be gone; try parent directory
            try:
                dev = os.stat(os.path.dirname(file_path)).st_dev
            except OSError:
                return self.fallback_dir

        info = self._filesystems.get(dev)
        if info is not None:
            return info.quarantine_dir

        LOG.debug(
            "File %s is on unknown device %d, using fallback quarantine dir",
            file_path,
            dev,
        )
        return self.fallback_dir

    # ------------------------------------------------------------------
    # Analysis / health reporting
    # ------------------------------------------------------------------

    def refresh_disk_usage(self) -> None:
        """Refresh free/used/total disk stats for each filesystem."""
        for info in self._filesystems.values():
            try:
                usage = os.statvfs(info.quarantine_dir)
                info.total_bytes = usage.f_frsize * usage.f_blocks
                info.free_bytes = usage.f_frsize * usage.f_bavail
                info.used_bytes = info.total_bytes - info.free_bytes
            except (OSError, AttributeError):
                # os.statvfs not available on Windows; skip
                try:
                    import shutil

                    total, used, free = shutil.disk_usage(info.quarantine_dir)
                    info.total_bytes = total
                    info.used_bytes = used
                    info.free_bytes = free
                except OSError:
                    pass

    def get_analysis(self) -> dict:
        """Return a full filesystem topology analysis.

        Includes per-FS info, cross-FS warnings, and quarantine dir mapping.
        """
        self.refresh_disk_usage()

        filesystems = []
        warnings = []

        for dev, info in sorted(self._filesystems.items()):
            fs_entry = {
                "st_dev": dev,
                "quarantine_dir": info.quarantine_dir,
                "scan_paths": info.scan_paths,
                "total_bytes": info.total_bytes,
                "free_bytes": info.free_bytes,
                "used_bytes": info.used_bytes,
                "free_pct": info.free_pct,
            }
            filesystems.append(fs_entry)

            # Warn if disk is >90% full
            if info.free_pct is not None and info.free_pct < 10:
                warnings.append(
                    f"Filesystem st_dev={dev} is {100 - info.free_pct:.1f}% full "
                    f"({_human_bytes(info.free_bytes)} free). "
                    f"Quarantine files may fill remaining space."
                )

        # Check if fallback dir is on a different FS than any scan path
        try:
            fallback_dev = os.stat(self.fallback_dir).st_dev
        except OSError:
            fallback_dev = None

        if fallback_dev and fallback_dev not in self._filesystems:
            warnings.append(
                f"Fallback quarantine dir ({self.fallback_dir}) is on a different "
                f"filesystem (st_dev={fallback_dev}) than all scan paths. "
                f"Files falling back to this dir will require cross-device copies."
            )

        return {
            "filesystems": filesystems,
            "fallback_quarantine_dir": self.fallback_dir,
            "fallback_st_dev": fallback_dev,
            "total_filesystems": len(filesystems),
            "total_scan_paths": sum(len(fs["scan_paths"]) for fs in filesystems),
            "warnings": warnings,
        }

    @property
    def filesystem_count(self) -> int:
        return len(self._filesystems)

    @property
    def all_quarantine_dirs(self) -> List[str]:
        """Return all quarantine directories (per-FS + fallback)."""
        dirs = [info.quarantine_dir for info in self._filesystems.values()]
        if self.fallback_dir not in dirs:
            dirs.append(self.fallback_dir)
        return dirs


def _human_bytes(n: Optional[int]) -> str:
    if n is None:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
