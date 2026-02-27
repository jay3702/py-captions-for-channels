"""Channels Files audit service.

Cross-references the Channels DVR ``/dvr/files`` API with the actual
filesystem to detect discrepancies:

* **Missing files** — API says a file exists but it's not on disk.
* **Orphaned files** — files on disk inside DVR recording folders that
  the API doesn't know about.
* **Empty folders** — recording folders with no media files.

This is an *experimental* feature gated behind ``CHANNELS_FILES_ENABLED``.
"""

import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

import requests

LOG = logging.getLogger(__name__)

# Top-level Channels DVR folders to scan for orphaned files.
# These are the standard content directories under the recordings root.
SCAN_ROOTS = ("Imports", "Movies", "TV", "Video")


def fetch_dvr_files(dvr_url: str, timeout: int = 30) -> List[dict]:
    """Fetch every file record from ``GET /dvr/files``.

    Args:
        dvr_url: Channels DVR base URL (e.g. ``http://localhost:8089``)
        timeout: HTTP request timeout in seconds

    Returns:
        List of file dicts straight from the API.
    """
    url = f"{dvr_url.rstrip('/')}/dvr/files"
    LOG.info("Fetching Channels DVR files from %s", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    files = resp.json()
    LOG.info("Channels DVR returned %d file records", len(files))
    return files


def fetch_deleted_files(dvr_url: str, timeout: int = 30) -> List[dict]:
    """Fetch deleted/trashed file records from ``GET /dvr/files?deleted=true``.

    These are files the DVR has soft-deleted but may still exist on disk.
    Their paths should be treated as "known" to avoid false-positive orphans.

    Args:
        dvr_url: Channels DVR base URL (e.g. ``http://localhost:8089``)
        timeout: HTTP request timeout in seconds

    Returns:
        List of deleted file dicts from the API.
    """
    url = f"{dvr_url.rstrip('/')}/dvr/files?deleted=true"
    LOG.info("Fetching deleted/trashed DVR files from %s", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    files = resp.json()
    LOG.info("Channels DVR returned %d deleted file records", len(files))
    return files


def audit_files(
    dvr_files: List[dict],
    recordings_path: str,
    *,
    deleted_files: Optional[List[dict]] = None,
    progress_callback: Optional[Callable[[dict], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """Cross-reference DVR file records with the filesystem.

    Args:
        dvr_files: List of file dicts from ``/dvr/files``
        recordings_path: Absolute path to the DVR recordings root
        deleted_files: Optional list of deleted/trashed file dicts from
            ``/dvr/files?deleted=true``.  Their paths are added to the
            "known" set so they are **not** flagged as orphans.
        progress_callback: Optional callback receiving progress dicts
        cancel_check: Optional callable; return True to abort early

    Returns:
        Audit result dict with ``missing_files``, ``orphaned_files``,
        ``empty_folders``, ``summary``, and per-file details.
    """
    recordings_root = Path(recordings_path)

    # ------------------------------------------------------------------
    # Phase 1 — Index API files
    # ------------------------------------------------------------------
    # Build a set of absolute paths the API says should exist,
    # and a map of folder → set of filenames the API tracks.
    api_paths: Set[str] = set()
    api_folders: Dict[str, Set[str]] = defaultdict(set)
    api_records: Dict[str, dict] = {}  # abs path → API record summary

    total = len(dvr_files)
    for i, rec in enumerate(dvr_files):
        if cancel_check and cancel_check():
            return _cancelled_result(i, total)

        rel_path = rec.get("Path", "")
        if not rel_path:
            continue
        # Normalize Windows-style backslashes from older API records
        rel_path = rel_path.replace("\\", "/")

        # Imported files store their folder prefix separately
        import_prefix = rec.get("ImportPath", "")
        if import_prefix:
            import_prefix = import_prefix.replace("\\", "/").rstrip("/")
            rel_path = import_prefix + "/" + rel_path

        abs_path = str(recordings_root / rel_path)
        api_paths.add(abs_path)
        folder = str(Path(abs_path).parent)
        api_folders[folder].add(Path(abs_path).name)

        api_records[abs_path] = {
            "id": rec.get("ID"),
            "path": rel_path,
            "abs_path": abs_path,
            "title": _extract_title(rec),
            "created_at": rec.get("CreatedAt"),
            "duration": rec.get("Duration"),
        }

        if progress_callback and (i + 1) % 200 == 0:
            progress_callback(
                {
                    "phase": "indexing",
                    "current": i + 1,
                    "total": total,
                    "message": f"Indexing API records: {i + 1} / {total}",
                }
            )

    if progress_callback:
        progress_callback(
            {
                "phase": "indexing",
                "current": total,
                "total": total,
                "message": (
                    f"Indexed {total} API records" f" across {len(api_folders)} folders"
                ),
            }
        )

    # ------------------------------------------------------------------
    # Phase 1b — Index deleted/trashed files
    # ------------------------------------------------------------------
    # Build a *separate* index for deleted files so we can tag them as
    # "trash" in the orphan list instead of silently hiding them.
    deleted_folders: Dict[str, Set[str]] = defaultdict(set)
    deleted_count = 0
    for rec in deleted_files or []:
        rel_path = rec.get("Path", "")
        if not rel_path:
            continue
        rel_path = rel_path.replace("\\", "/")

        # Imported files store their folder prefix separately
        import_prefix = rec.get("ImportPath", "")
        if import_prefix:
            import_prefix = import_prefix.replace("\\", "/").rstrip("/")
            rel_path = import_prefix + "/" + rel_path

        abs_path = str(recordings_root / rel_path)
        folder = str(Path(abs_path).parent)
        deleted_folders[folder].add(Path(abs_path).name)
        # Also register the folder so Phase 3 walks it even if no
        # active API files live there.
        if folder not in api_folders:
            api_folders[folder]  # touch to ensure defaultdict creates it
        deleted_count += 1

    if deleted_count:
        LOG.info("Indexed %d deleted/trashed file paths into trash set", deleted_count)

    # ------------------------------------------------------------------
    # Phase 2 — Check API files exist on disk
    # ------------------------------------------------------------------
    missing_files: List[dict] = []
    checked = 0

    for abs_path, info in api_records.items():
        if cancel_check and cancel_check():
            return _cancelled_result(checked, total)
        checked += 1

        if not Path(abs_path).exists():
            missing_files.append(info)

        if progress_callback and checked % 200 == 0:
            progress_callback(
                {
                    "phase": "checking_missing",
                    "current": checked,
                    "total": len(api_records),
                    "missing": len(missing_files),
                    "message": f"Checking existence: {checked} / {len(api_records)}",
                }
            )

    if progress_callback:
        progress_callback(
            {
                "phase": "checking_missing",
                "current": len(api_records),
                "total": len(api_records),
                "missing": len(missing_files),
                "message": f"Found {len(missing_files)} missing file(s)",
            }
        )

    # ------------------------------------------------------------------
    # Phase 3 — Walk folders for orphaned (extra) files
    # ------------------------------------------------------------------
    orphaned_files: List[dict] = []
    empty_folders: List[str] = []
    folders_checked = 0
    total_folders = len(api_folders)

    for folder, api_filenames in api_folders.items():
        if cancel_check and cancel_check():
            return _cancelled_result(folders_checked, total_folders)
        folders_checked += 1

        folder_path = Path(folder)
        if not folder_path.exists():
            # Entire folder missing — already captured via missing_files
            continue

        try:
            disk_files = set(f.name for f in folder_path.iterdir() if f.is_file())
        except OSError as exc:
            LOG.warning("Cannot list folder %s: %s", folder, exc)
            continue

        # Files on disk but NOT in the active API set
        deleted_filenames = deleted_folders.get(folder, set())
        extra = disk_files - api_filenames
        for name in sorted(extra):
            # Skip companion files (.srt, .orig, .cc4chan.*) whose
            # parent recording IS tracked by the API in this folder.
            if _is_companion_of_api_file(name, api_filenames):
                continue

            # Determine if this file (or its parent recording) is in
            # the DVR trash — we still list it, but flag it.
            is_trash = name in deleted_filenames or _is_companion_of_api_file(
                name, deleted_filenames
            )

            full = str(folder_path / name)
            try:
                size = os.path.getsize(full)
            except OSError:
                size = None
            orphaned_files.append(
                {
                    "path": full,
                    "rel_path": _make_relative(full, recordings_root),
                    "folder": folder,
                    "filename": name,
                    "size_bytes": size,
                    "trash": is_trash,
                }
            )

        # Check for empty folder (no media files left)
        remaining_media = disk_files & api_filenames
        if not remaining_media and not extra:
            empty_folders.append(folder)

        if progress_callback and folders_checked % 50 == 0:
            progress_callback(
                {
                    "phase": "checking_orphans",
                    "current": folders_checked,
                    "total": total_folders,
                    "orphans": len(orphaned_files),
                    "message": f"Scanning folders: {folders_checked} / {total_folders}",
                }
            )

    if progress_callback:
        progress_callback(
            {
                "phase": "checking_orphans",
                "current": total_folders,
                "total": total_folders,
                "orphans": len(orphaned_files),
                "message": (
                    f"Found {len(orphaned_files)} orphaned"
                    f" file(s) in {total_folders} API folders"
                ),
            }
        )

    # ------------------------------------------------------------------
    # Phase 3b — Walk top-level roots for unreferenced folders
    # ------------------------------------------------------------------
    # Phase 3 only visits folders that contain API-tracked files.
    # Walk all known Channels DVR content roots to catch orphans in
    # folders the API has no record of.
    extra_folders_checked = 0
    for root_name in SCAN_ROOTS:
        root_dir = recordings_root / root_name
        if not root_dir.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(str(root_dir)):
            if cancel_check and cancel_check():
                return _cancelled_result(
                    total_folders + extra_folders_checked, total_folders
                )
            folder = str(Path(dirpath))
            if folder in api_folders:
                continue  # already processed in Phase 3

            extra_folders_checked += 1
            if not filenames:
                # Track empty folders inside the roots too
                empty_folders.append(folder)
                continue

            deleted_filenames_extra = deleted_folders.get(folder, set())
            for name in sorted(filenames):
                is_trash = name in deleted_filenames_extra or _is_companion_of_api_file(
                    name, deleted_filenames_extra
                )
                full = os.path.join(folder, name)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = None
                orphaned_files.append(
                    {
                        "path": full,
                        "rel_path": _make_relative(full, recordings_root),
                        "folder": folder,
                        "filename": name,
                        "size_bytes": size,
                        "trash": is_trash,
                    }
                )

            if progress_callback and extra_folders_checked % 50 == 0:
                progress_callback(
                    {
                        "phase": "scanning_roots",
                        "current": extra_folders_checked,
                        "total": extra_folders_checked,
                        "orphans": len(orphaned_files),
                        "message": (
                            f"Scanning content roots:"
                            f" {extra_folders_checked} extra folders"
                        ),
                    }
                )

    if extra_folders_checked and progress_callback:
        progress_callback(
            {
                "phase": "scanning_roots",
                "current": extra_folders_checked,
                "total": extra_folders_checked,
                "orphans": len(orphaned_files),
                "message": (
                    f"Scanned {extra_folders_checked} extra folders"
                    f" outside API scope — {len(orphaned_files)} total orphans"
                ),
            }
        )

    # ------------------------------------------------------------------
    # Build summary
    # ------------------------------------------------------------------
    total_orphan_bytes = sum(
        f["size_bytes"] for f in orphaned_files if f["size_bytes"] is not None
    )
    trashed = [f for f in orphaned_files if f.get("trash")]
    trashed_bytes = sum(f["size_bytes"] for f in trashed if f["size_bytes"] is not None)

    result = {
        "success": True,
        "cancelled": False,
        "summary": {
            "api_file_count": len(api_records),
            "api_folder_count": len(api_folders) + extra_folders_checked,
            "deleted_file_count": deleted_count,
            "missing_count": len(missing_files),
            "orphaned_count": len(orphaned_files),
            "orphaned_total_bytes": total_orphan_bytes,
            "trashed_count": len(trashed),
            "trashed_total_bytes": trashed_bytes,
            "empty_folder_count": len(empty_folders),
        },
        "missing_files": missing_files,
        "orphaned_files": orphaned_files,
        "empty_folders": empty_folders,
    }

    LOG.info(
        "Channels Files audit complete: %d API files, %d deleted, %d missing, "
        "%d orphaned (%d extra root folders), %d empty folders",
        len(api_records),
        deleted_count,
        len(missing_files),
        len(orphaned_files),
        extra_folders_checked,
        len(empty_folders),
    )

    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

# Suffixes appended to recording filenames by py-captions-for-channels.
# Longest first so we strip the most specific match.
_COMPANION_SUFFIXES = (
    ".cc4chan.orig.tmp",
    ".cc4chan.muxed.mp4",
    ".cc4chan.temp.wav",
    ".cc4chan.av.mp4",
    ".cc4chan.orig",
    ".srt.cc4chan.tmp",
    ".srt",
    ".orig.tmp",
    ".orig",
)


def _is_companion_of_api_file(filename: str, api_filenames: Set[str]) -> bool:
    """Return True if *filename* is a sidecar of an API-tracked file.

    Strips known companion suffixes (.srt, .orig, .cc4chan.*) and checks
    whether the resulting base name is in *api_filenames*.
    """
    for suffix in _COMPANION_SUFFIXES:
        if filename.endswith(suffix):
            base = filename[: -len(suffix)]
            # base must be non-empty and match a real API file
            if base and any(af.startswith(base) and af == base for af in api_filenames):
                return True
            # Also check with common media extensions appended
            # e.g. "recording.mpg.srt" → base="recording.mpg"
            # which is already the full filename — covered above.
            # But "recording.srt" → base="recording" which needs
            # an extension to match "recording.mpg"
            if base:
                for af in api_filenames:
                    if af.startswith(base + "."):
                        return True
    # Catch-all for .cc4chan. in the name (temp files)
    if ".cc4chan." in filename:
        # Extract everything before .cc4chan.
        base = filename.split(".cc4chan.")[0]
        if base and base in api_filenames:
            return True
        if base:
            for af in api_filenames:
                if af.startswith(base + "."):
                    return True
    return False


def _extract_title(rec: dict) -> str:
    """Extract a human-readable title from a DVR file record."""
    airing = rec.get("Airing") or {}
    title = airing.get("Title", "")
    if not title:
        # Fall back to filename stem
        path = rec.get("Path", "")
        title = Path(path).stem if path else f"ID {rec.get('ID', '?')}"
    return title


def _make_relative(abs_path: str, root: Path) -> str:
    """Make an absolute path relative to *root*, or return as-is."""
    try:
        return str(Path(abs_path).relative_to(root))
    except ValueError:
        return abs_path


def _cancelled_result(current: int, total: int) -> dict:
    return {
        "success": True,
        "cancelled": True,
        "summary": {
            "api_file_count": 0,
            "api_folder_count": 0,
            "missing_count": 0,
            "orphaned_count": 0,
            "orphaned_total_bytes": 0,
            "empty_folder_count": 0,
            "cancelled_at": f"{current}/{total}",
        },
        "missing_files": [],
        "orphaned_files": [],
        "empty_folders": [],
    }
