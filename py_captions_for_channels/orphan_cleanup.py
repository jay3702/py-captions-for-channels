"""
Automatic cleanup of orphaned caption files.

Two detection methods:
1. History-based (automated): Uses execution history (Jobs tab) to find
   orphaned files for recordings that were processed and are now missing
2. Filesystem-based (manual): Scans all files regardless of history
   (for deep scan / manual use)

The automated cleanup uses processing history to ensure safety - it only
removes .orig and .srt files for recordings that:
- Were successfully processed by this system (have an execution record)
- Have since been deleted (recording file no longer exists at the stored path)

This prevents accidental deletion of files from unprocessed recordings or
recordings that failed processing.

TODO: Future enhancement - Detect and quarantine files orphaned by Channels DVR
      Currently we only detect orphans created by our own processing pipeline.
      Channels DVR may also leave orphaned files when recordings are deleted or moved.
      Future version should:
      - Scan for .orig and .srt files without corresponding video files
      - Identify which were created by Channels DVR vs our pipeline
      - Add them to quarantine with appropriate metadata
      - Use same restore/delete workflow for all orphaned files
"""

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

LOG = logging.getLogger(__name__)


def find_orphaned_files_by_filesystem(
    recordings_path: str,
) -> Tuple[List[Path], List[Path]]:
    """Find .orig and .srt files without corresponding video files (filesystem scan).

    This method scans all files regardless of processing history.
    Kept for future manual cleanup operations where user can review before deleting.

    Args:
        recordings_path: Path to DVR recordings directory

    Returns:
        Tuple of (orphaned_orig_files, orphaned_srt_files)
    """
    if not recordings_path or not os.path.exists(recordings_path):
        LOG.warning(f"Recordings path not found: {recordings_path}")
        return ([], [])

    recordings_dir = Path(recordings_path)
    orphaned_orig = []
    orphaned_srt = []

    from py_captions_for_channels.config import MEDIA_FILE_EXTENSIONS

    # Find all .orig files (any <video>.orig pattern)
    orig_files = list(recordings_dir.rglob("*.orig"))
    srt_files = list(recordings_dir.rglob("*.srt"))

    LOG.debug(f"Scanning {len(orig_files)} .orig files and {len(srt_files)} .srt files")

    # Check .orig files
    for orig_file in orig_files:
        # Original video should be at the path without .orig
        video_path = orig_file.with_suffix("")  # Remove .orig suffix
        if not video_path.exists():
            orphaned_orig.append(orig_file)
            LOG.debug(f"Orphaned .orig: {orig_file} (missing {video_path})")

    # Check .srt files
    for srt_file in srt_files:
        # Video should be the same stem with any configured media extension
        stem = srt_file.with_suffix("")
        video_exists = any(
            stem.with_suffix(ext).exists() for ext in MEDIA_FILE_EXTENSIONS
        )
        if not video_exists:
            orphaned_srt.append(srt_file)
            LOG.debug(f"Orphaned .srt: {srt_file} (no matching video found)")

    LOG.info(
        f"Found {len(orphaned_orig)} orphaned .orig files "
        f"and {len(orphaned_srt)} orphaned .srt files"
    )

    return (orphaned_orig, orphaned_srt)


def scan_filesystem_progressive(
    scan_paths: List[Dict],
    progress_callback: Optional[Callable[[Dict], None]] = None,
) -> Tuple[List[Path], List[Path]]:
    """Scan filesystem paths for orphaned files with per-folder progress.

    Walks each scan path directory-by-directory, reporting progress via
    callback so the caller can stream updates to the frontend.

    Args:
        scan_paths: List of dicts with 'path' and optional 'label' keys.
        progress_callback: Called with progress dict for each folder:
            {phase, folder, current, total, scan_path, scan_path_label,
             orphans_found}

    Returns:
        Tuple of (orphaned_orig_files, orphaned_srt_files)
    """
    from py_captions_for_channels.config import MEDIA_FILE_EXTENSIONS

    media_extensions = MEDIA_FILE_EXTENSIONS

    all_orphaned_orig: List[Path] = []
    all_orphaned_srt: List[Path] = []

    # Phase 1: enumerate all directories across all scan paths
    all_dirs: List[Tuple[str, str, str]] = []  # (dir_path, scan_path, label)
    for sp in scan_paths:
        sp_path = sp["path"]
        sp_label = sp.get("label") or sp_path
        if not os.path.exists(sp_path):
            LOG.warning(f"Scan path not found: {sp_path}")
            continue
        for dirpath, dirnames, _filenames in os.walk(sp_path):
            all_dirs.append((dirpath, sp_path, sp_label))

    total_dirs = len(all_dirs)
    if progress_callback:
        progress_callback(
            {
                "phase": "enumerating",
                "message": f"Found {total_dirs} folders to scan",
                "current": 0,
                "total": total_dirs,
            }
        )

    # Phase 2: scan each directory for orphaned files
    for idx, (dirpath, sp_path, sp_label) in enumerate(all_dirs, start=1):
        if progress_callback:
            progress_callback(
                {
                    "phase": "scanning",
                    "folder": dirpath,
                    "current": idx,
                    "total": total_dirs,
                    "scan_path": sp_path,
                    "scan_path_label": sp_label,
                    "orphans_found": len(all_orphaned_orig) + len(all_orphaned_srt),
                }
            )

        try:
            entries = os.listdir(dirpath)
        except PermissionError:
            LOG.warning(f"Permission denied: {dirpath}")
            continue

        for entry in entries:
            full = os.path.join(dirpath, entry)
            if not os.path.isfile(full):
                continue

            if entry.endswith(".orig"):
                # .orig is always <video_file>.orig — strip .orig to
                # get the expected video path
                video_path = full[: -len(".orig")]
                if not os.path.exists(video_path):
                    all_orphaned_orig.append(Path(full))

            elif entry.endswith(".srt"):
                # Check if a video file with the same stem exists
                # under any configured media extension
                stem = full[: -len(".srt")]
                video_exists = any(
                    os.path.exists(stem + ext) for ext in media_extensions
                )
                if not video_exists:
                    all_orphaned_srt.append(Path(full))

    if progress_callback:
        progress_callback(
            {
                "phase": "complete",
                "message": "Scan complete",
                "current": total_dirs,
                "total": total_dirs,
                "orphans_found": len(all_orphaned_orig) + len(all_orphaned_srt),
            }
        )

    LOG.info(
        f"Progressive scan found {len(all_orphaned_orig)} orphaned .orig "
        f"and {len(all_orphaned_srt)} orphaned .srt files "
        f"across {total_dirs} folders"
    )

    return (all_orphaned_orig, all_orphaned_srt)


def find_orphaned_files() -> Tuple[List[Path], List[Path]]:
    """Find orphaned files using processing history (safe for automated cleanup).

    Uses the execution history maintained by this system (visible on the Jobs
    tab) to identify orphaned files.  Each execution record stores the full
    absolute path of the recording that was processed.  If that recording file
    no longer exists, the associated .orig and .srt files are considered
    orphaned and returned for quarantine.

    No base "recordings path" is needed — the full paths come directly from
    the execution history.

    Returns:
        Tuple of (orphaned_orig_files, orphaned_srt_files)
    """
    # Import here to avoid circular dependency
    from py_captions_for_channels.web_app import state_backend

    orphaned_orig = []
    orphaned_srt = []

    try:
        # Get all processed recordings from history
        executions = state_backend.get_executions(limit=10000)

        processed_paths = set()
        for execution in executions:
            # Only consider successfully completed executions
            if execution.get("status") == "completed" and execution.get("success"):
                path = execution.get("path")
                if path:
                    processed_paths.add(path)

        LOG.debug(f"Found {len(processed_paths)} processed recordings in history")

        # Check each processed recording for orphaned files
        for recording_path_str in processed_paths:
            recording_path = Path(recording_path_str)

            # Check if the recording file still exists
            if recording_path.exists():
                # Recording still exists, skip
                continue

            # Recording is missing — check for orphaned backup/caption files
            # .orig is always <recording_path>.orig  (e.g. video.mpg.orig)
            orig_path = Path(str(recording_path) + ".orig")
            # .srt shares the stem but has .srt extension (e.g. video.srt)
            srt_path = recording_path.with_suffix(".srt")

            if orig_path.exists():
                orphaned_orig.append(orig_path)
                LOG.debug(
                    f"Orphaned .orig: {orig_path} "
                    f"(processed recording deleted: {recording_path})"
                )

            if srt_path.exists():
                orphaned_srt.append(srt_path)
                LOG.debug(
                    f"Orphaned .srt: {srt_path} "
                    f"(processed recording deleted: {recording_path})"
                )

        LOG.info(
            f"History-based scan found {len(orphaned_orig)} orphaned "
            f".orig files and {len(orphaned_srt)} orphaned .srt files "
            f"from {len(processed_paths)} processed recordings"
        )

    except Exception as e:
        LOG.error(f"Error scanning processing history: {e}", exc_info=True)
        return ([], [])

    return (orphaned_orig, orphaned_srt)


def quarantine_orphaned_files(
    orig_files: List[Path], srt_files: List[Path], dry_run: bool = False
) -> Tuple[int, int]:
    """Quarantine orphaned .orig and .srt files instead of deleting them.

    Files are moved to quarantine with an expiration date, allowing restore if needed.

    Args:
        orig_files: List of orphaned .orig files to quarantine
        srt_files: List of orphaned .srt files to quarantine
        dry_run: If True, only log what would be quarantined without moving files

    Returns:
        Tuple of (orig_quarantined_count, srt_quarantined_count)
    """
    from py_captions_for_channels.config import (
        QUARANTINE_DIR,
        QUARANTINE_EXPIRATION_DAYS,
    )
    from py_captions_for_channels.database import get_db
    from py_captions_for_channels.services.quarantine_service import QuarantineService

    orig_quarantined = 0
    srt_quarantined = 0

    if not dry_run:
        db = next(get_db())
        service = QuarantineService(db, QUARANTINE_DIR)

    orig_failed = 0
    srt_failed = 0

    # Quarantine .orig files
    for orig_file in orig_files:
        try:
            if dry_run:
                LOG.info(f"[DRY RUN] Would quarantine orphaned .orig: {orig_file}")
            else:
                # Try to find associated recording path
                recording_path = None
                if orig_file.parent.parent.is_dir():
                    # Parent dir is likely the recording directory
                    recording_path = str(orig_file.parent)

                service.quarantine_file(
                    original_path=str(orig_file),
                    file_type="orig",
                    recording_path=recording_path,
                    reason="orphaned_by_pipeline",
                    expiration_days=QUARANTINE_EXPIRATION_DAYS,
                )
                LOG.info(f"Quarantined orphaned .orig: {orig_file}")
            orig_quarantined += 1
        except Exception as e:
            orig_failed += 1
            LOG.error(f"Failed to quarantine {orig_file}: {e}")

    # Quarantine .srt files
    for srt_file in srt_files:
        try:
            if dry_run:
                LOG.info(f"[DRY RUN] Would quarantine orphaned .srt: {srt_file}")
            else:
                # Try to find associated recording path
                recording_path = None
                if srt_file.parent.is_dir():
                    # Parent dir is the recording directory
                    recording_path = str(srt_file.parent)

                service.quarantine_file(
                    original_path=str(srt_file),
                    file_type="srt",
                    recording_path=recording_path,
                    reason="orphaned_by_pipeline",
                    expiration_days=QUARANTINE_EXPIRATION_DAYS,
                )
                LOG.info(f"Quarantined orphaned .srt: {srt_file}")
            srt_quarantined += 1
        except Exception as e:
            srt_failed += 1
            LOG.error(f"Failed to quarantine {srt_file}: {e}")

    if orig_failed or srt_failed:
        LOG.warning(f"Quarantine failures: {orig_failed} .orig, {srt_failed} .srt")

    return (orig_quarantined, srt_quarantined)


def is_system_idle(threshold_minutes: int = 15) -> bool:
    """Check if the system is idle (no active pipeline executions).

    Args:
        threshold_minutes: Minutes of inactivity to consider system idle

    Returns:
        True if system is idle, False otherwise
    """
    # Import here to avoid circular dependency
    from py_captions_for_channels.web_app import state_backend

    try:
        # Check if there are any active executions
        executions = state_backend.get_executions(limit=10)

        # If there are any running executions, not idle
        for execution in executions:
            if execution.get("status") == "running":
                LOG.debug("System not idle: active execution found")
                return False

        # Check when the last execution completed
        if executions:
            last_execution = executions[0]
            ended_at = last_execution.get("ended_at")
            if ended_at:
                # Parse ISO timestamp
                ended_time = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
                idle_duration = datetime.now(ended_time.tzinfo) - ended_time

                is_idle = idle_duration > timedelta(minutes=threshold_minutes)
                if not is_idle:
                    LOG.debug(
                        f"System not idle: last execution ended "
                        f"{idle_duration.total_seconds() / 60:.1f} minutes ago"
                    )
                return is_idle

        # No recent executions, consider idle
        LOG.debug("System idle: no recent executions")
        return True

    except Exception as e:
        LOG.warning(f"Error checking system idle status: {e}")
        # Assume not idle on error (safer)
        return False


def run_cleanup(dry_run: bool = False, cleanup_history: bool = True) -> dict:
    """Perform orphan file cleanup.

    Args:
        dry_run: If True, only log what would be deleted
        cleanup_history: If True, also clean up old execution history

    Returns:
        Dict with cleanup statistics
    """
    from py_captions_for_channels.database import get_db
    from py_captions_for_channels.models import OrphanCleanupHistory
    from py_captions_for_channels.services.execution_service import ExecutionService

    LOG.info("Starting orphan file cleanup")
    start_time = time.time()

    try:
        # Find orphaned files using execution history (no base path needed)
        orig_files, srt_files = find_orphaned_files()

        # Quarantine them (move to quarantine instead of immediate deletion)
        orig_quarantined, srt_quarantined = quarantine_orphaned_files(
            orig_files, srt_files, dry_run=dry_run
        )

        elapsed = time.time() - start_time
        cleanup_timestamp = datetime.utcnow()

        result = {
            "success": True,
            "orig_found": len(orig_files),
            "srt_found": len(srt_files),
            "orig_quarantined": orig_quarantined,
            "srt_quarantined": srt_quarantined,
            # Legacy fields for compatibility
            "orig_deleted": orig_quarantined,
            "srt_deleted": srt_quarantined,
            "elapsed_seconds": round(elapsed, 2),
            "dry_run": dry_run,
            "timestamp": cleanup_timestamp.isoformat() + "Z",
        }

        # Record successful cleanup in database (unless dry run)
        if not dry_run and (orig_quarantined > 0 or srt_quarantined > 0):
            try:
                db = next(get_db())
                cleanup_record = OrphanCleanupHistory(
                    cleanup_timestamp=cleanup_timestamp,
                    orig_files_deleted=orig_quarantined,
                    srt_files_deleted=srt_quarantined,
                )
                db.add(cleanup_record)
                db.commit()
                LOG.info(f"Recorded orphan cleanup in database at {cleanup_timestamp}")
            except Exception as e:
                LOG.warning(f"Failed to record cleanup history: {e}")

        # Clean up old execution history if requested
        if cleanup_history and not dry_run:
            try:
                db = next(get_db())
                service = ExecutionService(db)

                # Get the oldest orphan cleanup date (or use 30 days ago as fallback)
                oldest_cleanup = (
                    db.query(OrphanCleanupHistory)
                    .order_by(OrphanCleanupHistory.cleanup_timestamp.asc())
                    .first()
                )

                if oldest_cleanup:
                    cutoff_date = oldest_cleanup.cleanup_timestamp
                    LOG.info(
                        f"Cleaning execution history older than "
                        f"{cutoff_date} (oldest cleanup date)"
                    )
                else:
                    # No cleanup history yet, use 30 days as default
                    cutoff_date = datetime.utcnow() - timedelta(days=30)
                    LOG.info(
                        f"No cleanup history found, using 30-day "
                        f"default cutoff: {cutoff_date}"
                    )

                executions_removed = service.clear_executions_before_date(cutoff_date)
                result["executions_cleaned"] = executions_removed

                if executions_removed > 0:
                    LOG.info(
                        f"Cleaned up {executions_removed} execution "
                        f"records older than {cutoff_date}"
                    )

            except Exception as e:
                LOG.warning(f"Failed to clean up execution history: {e}")
                result["execution_cleanup_error"] = str(e)

        LOG.info(
            f"Cleanup completed in {elapsed:.1f}s: "
            f"quarantined {orig_quarantined} .orig and {srt_quarantined} .srt files"
            + (" (DRY RUN)" if dry_run else "")
        )

        return result

    except Exception as e:
        LOG.error(f"Orphan cleanup failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


def run_manual_cleanup(dry_run: bool = True) -> dict:
    """Perform manual orphan file cleanup using filesystem scan.

    This uses the filesystem-based detection method which scans all files
    regardless of processing history. Intended for manual operations where
    user can review results before deletion.

    TODO: Add UI button to trigger this function
    TODO: Add restore capability for manual cleanup

    Args:
        dry_run: If True, only report what would be deleted (default: True for safety)

    Returns:
        Dict with cleanup statistics including file lists for review
    """
    from py_captions_for_channels.config import DVR_RECORDINGS_PATH

    LOG.info("Starting manual orphan file scan (filesystem-based)")
    start_time = time.time()

    try:
        # Find orphaned files using filesystem scan
        orig_files, srt_files = find_orphaned_files_by_filesystem(DVR_RECORDINGS_PATH)

        # For manual cleanup, always return full file lists for user review
        result = {
            "success": True,
            "orig_found": len(orig_files),
            "srt_found": len(srt_files),
            "orig_files": [str(f) for f in orig_files],
            "srt_files": [str(f) for f in srt_files],
            "elapsed_seconds": round(time.time() - start_time, 2),
            "dry_run": dry_run,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        # If not dry run, actually quarantine the files
        if not dry_run:
            orig_quarantined, srt_quarantined = quarantine_orphaned_files(
                orig_files, srt_files, dry_run=False
            )
            result["orig_quarantined"] = orig_quarantined
            result["srt_quarantined"] = srt_quarantined
            # Legacy fields for compatibility
            result["orig_deleted"] = orig_quarantined
            result["srt_deleted"] = srt_quarantined
            LOG.info(
                f"Manual cleanup quarantined {orig_quarantined} .orig "
                f"and {srt_quarantined} .srt files"
            )
        else:
            LOG.info(
                f"Manual scan found {len(orig_files)} .orig "
                f"and {len(srt_files)} .srt orphaned files (dry run)"
            )

        return result

    except Exception as e:
        LOG.error(f"Manual orphan cleanup failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


class OrphanCleanupScheduler:
    """Scheduler for automatic orphan file cleanup."""

    def __init__(
        self,
        enabled: bool = True,
        check_interval_hours: int = 1,
        idle_threshold_minutes: int = 15,
        dry_run: bool = False,
    ):
        """Initialize the cleanup scheduler.

        Args:
            enabled: Whether cleanup is enabled
            check_interval_hours: Hours between cleanup checks
            idle_threshold_minutes: Minutes of idle time before running cleanup
            dry_run: If True, log what would be deleted without deleting
        """
        self.enabled = enabled
        self.check_interval_hours = check_interval_hours
        self.idle_threshold_minutes = idle_threshold_minutes
        self.dry_run = dry_run
        self.last_cleanup_time = None
        self.last_check_time = None

    def should_run_cleanup(self) -> bool:
        """Check if cleanup should run now.

        Returns:
            True if cleanup should run, False otherwise
        """
        if not self.enabled:
            return False

        now = datetime.utcnow()

        # Check if it's been long enough since last cleanup
        if self.last_cleanup_time is not None:
            time_since_last = now - self.last_cleanup_time
            if time_since_last < timedelta(hours=self.check_interval_hours):
                return False

        # Check if system is idle
        if not is_system_idle(self.idle_threshold_minutes):
            return False

        return True

    def run_if_needed(self) -> dict | None:
        """Run cleanup if conditions are met.

        Returns:
            Cleanup result dict if cleanup ran, None otherwise
        """
        self.last_check_time = datetime.utcnow()

        if not self.should_run_cleanup():
            return None

        LOG.info("Conditions met for orphan cleanup, running...")
        result = run_cleanup(dry_run=self.dry_run)

        if result.get("success"):
            self.last_cleanup_time = datetime.utcnow()

        return result
