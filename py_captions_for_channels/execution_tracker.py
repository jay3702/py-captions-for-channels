"""
Execution tracker for pipeline runs.

Tracks active and completed pipeline executions for display in the web UI.
Now uses database backend via ExecutionService.
"""

import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .database import get_db
from .services.execution_service import ExecutionService

LOG = logging.getLogger(__name__)


def build_manual_process_job_id(path: str) -> str:
    """Build a stable job ID for manual process executions."""
    return f"manual_process::{path}"


class ExecutionTracker:
    """Thread-safe tracker for pipeline executions using database backend."""

    def __init__(self, storage_path: str = "/app/data/executions.json"):
        self.storage_path = Path(storage_path)
        self.lock = threading.Lock()
        self.execution_counter: int = 0
        self._migrated = False
        self._migrate_from_json()

    @contextmanager
    def _get_service(self):
        """Get ExecutionService with properly managed database session.

        Usage:
            with self._get_service() as service:
                service.create_execution(...)
        """
        db_gen = get_db()
        try:
            db = next(db_gen)
            yield ExecutionService(db)
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass  # Generator cleanup completed

    def _migrate_from_json(self):
        """Migrate existing executions from JSON file to database (one-time)."""
        if self._migrated:
            return

        if not self.storage_path.exists():
            self._migrated = True
            return

        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)
                executions = data.get("executions", {})
                self.execution_counter = data.get("execution_counter", 0)

            if not executions:
                self._migrated = True
                return

            LOG.info(f"Migrating {len(executions)} executions from JSON to database...")
            with self._get_service() as service:
                migrated_count = 0

                for exec_id, exec_data in executions.items():
                    # Check if already exists in database
                    existing = service.get_execution(exec_id)
                    if existing:
                        continue

                    # Create execution in database
                    try:
                        started_at = None
                        if exec_data.get("started_at"):
                            started_at = datetime.fromisoformat(exec_data["started_at"])

                        service.create_execution(
                            job_id=exec_id,
                            title=exec_data.get("title", "Unknown"),
                            path=exec_data.get("path"),
                            status=exec_data.get("status", "completed"),
                            kind=exec_data.get("kind", "normal"),
                            started_at=started_at,
                        )

                        # Update with completion data if completed
                        if exec_data.get("completed_at"):
                            service.update_execution(
                                exec_id,
                                completed_at=datetime.fromisoformat(
                                    exec_data["completed_at"]
                                ),
                                success=exec_data.get("success"),
                                elapsed_seconds=exec_data.get("elapsed_seconds", 0.0),
                                error_message=exec_data.get("error"),
                            )

                        migrated_count += 1
                    except Exception as e:
                        LOG.warning(f"Failed to migrate execution {exec_id}: {e}")

                LOG.info(f"Migrated {migrated_count} executions to database")

            # Rename JSON file to indicate migration complete
            backup_path = self.storage_path.with_suffix(".json.migrated")
            self.storage_path.rename(backup_path)
            LOG.info(f"Backed up JSON file to {backup_path}")

            self._migrated = True

        except Exception as e:
            LOG.error(f"Failed to migrate executions from JSON: {e}")
            self._migrated = True  # Don't retry on every call

    def _load(self):
        """Legacy method for compatibility - no-op now (database auto-loads)."""
        pass

    def _save(self):
        """Legacy method for compatibility - no-op now (database auto-saves)."""
        pass

    def start_execution(
        self,
        job_id: str,
        title: str,
        path: str,
        timestamp: Optional[str] = None,
        status: str = "running",
        kind: str = "normal",
    ) -> str:
        """Register a new pipeline execution.

        Args:
            job_id: Unique job identifier
            title: Recording title
            path: File path
            timestamp: ISO timestamp (defaults to now)
            status: Initial status (pending, running)
            kind: Execution type (normal, manual_process)

        Returns:
            Execution ID
        """
        with self.lock:
            with self._get_service() as service:
                exec_id = job_id

                # Check if execution already exists
                existing = service.get_execution(job_id)
                if existing:
                    # If completed/failed, create new unique ID for reprocessing
                    if existing.status in ("completed", "failed"):
                        # Use microsecond-precision timestamp for uniqueness
                        now_ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
                        exec_id = f"{job_id}::{now_ts}"

                        LOG.info(
                            "Reprocessing existing execution - new ID: %s -> %s",
                            job_id,
                            exec_id,
                        )
                    else:
                        # Execution already exists with active status, don't recreate
                        LOG.debug(
                            "Execution already exists: %s [%s]",
                            job_id,
                            existing.status,
                        )
                        return job_id

                # Increment execution counter for unique tracking
                self.execution_counter += 1

                # Parse started_at timestamp
                if timestamp:
                    dt = datetime.fromisoformat(timestamp)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    started_at = dt
                else:
                    started_at = datetime.now(timezone.utc)

                # Create execution in database
                execution = service.create_execution(
                    job_id=exec_id,
                    title=title,
                    path=path,
                    status=status,
                    kind=kind,
                    started_at=started_at,
                )

                LOG.info(
                    "Started tracking execution #%d (seq #%s): %s [%s]",
                    self.execution_counter,
                    execution.job_sequence,
                    exec_id,
                    status,
                )
                return exec_id

    def update_status(self, job_id: str, status: str):
        """Update the status of an execution.

        Args:
            job_id: Job identifier
            status: New status (pending, running, completed)
        """
        with self.lock:
            with self._get_service() as service:
                if service.update_status(job_id, status):
                    LOG.info("Updated execution status: %s -> %s", job_id, status)
                else:
                    LOG.warning(
                        "Failed to update execution status (not found): %s -> %s",
                        job_id,
                        status,
                    )

    def update_execution(self, job_id: str, **kwargs):
        """Update execution fields.

        Args:
            job_id: Job identifier
            **kwargs: Fields to update (status, started_at, etc.)
                     DateTime fields (started_at, completed_at) can be
                     datetime objects or ISO strings
        """
        with self.lock:
            # Parse datetime fields if they're ISO strings
            datetime_fields = ["started_at", "completed_at"]
            for field in datetime_fields:
                if field in kwargs and isinstance(kwargs[field], str):
                    dt = datetime.fromisoformat(kwargs[field])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    kwargs[field] = dt

            with self._get_service() as service:
                if service.update_execution(job_id, **kwargs):
                    LOG.debug("Updated execution %s: %s", job_id, kwargs)

    def request_cancel(self, job_id: str) -> bool:
        """Request cancellation of a running execution.

        Returns True if the job exists and was marked for cancel.
        """
        with self.lock:
            with self._get_service() as service:
                if service.request_cancel(job_id):
                    LOG.info("Cancel requested for execution: %s", job_id)
                    return True
                return False

    def is_cancel_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job."""
        with self.lock:
            with self._get_service() as service:
                return service.is_cancel_requested(job_id)

    def remove_execution(self, job_id: str) -> bool:
        """Remove an execution from the tracker.

        Returns True if the job existed and was removed.
        """
        with self.lock:
            with self._get_service() as service:
                if service.remove_execution(job_id):
                    LOG.info("Removed execution from tracker: %s", job_id)
                    return True
                return False

    def add_log(self, job_id: str, log_line: str):
        """Add a log line to an execution (legacy - now no-op).

        Logs are now stored in the main log file, not per-execution.

        Args:
            job_id: Job identifier
            log_line: Log line to append
        """
        # Logs are now in main log file with [job_id] prefix
        # This method kept for backward compatibility
        pass

    def complete_execution(
        self,
        job_id: str,
        success: bool,
        elapsed_seconds: float,
        error: Optional[str] = None,
    ):
        """Mark an execution as completed.

        Args:
            job_id: Job identifier
            success: Whether execution succeeded
            elapsed_seconds: Total execution time
            error: Error message if failed
        """
        with self.lock:
            with self._get_service() as service:
                if service.complete_execution(job_id, success, elapsed_seconds, error):
                    LOG.info(
                        "Completed execution: %s (success=%s, elapsed=%.1fs)",
                        job_id,
                        success,
                        elapsed_seconds,
                    )
                else:
                    LOG.warning("Attempted to complete unknown execution: %s", job_id)

    def get_executions(self, limit: int = 50) -> List[dict]:
        """Get recent executions, most recent first.

        Args:
            limit: Maximum number of executions to return

        Returns:
            List of execution dicts
        """
        with self._get_service() as service:
            executions = service.get_executions(limit=limit)
            return [service.to_dict(exec) for exec in executions]

    def get_execution(self, job_id: str) -> Optional[dict]:
        """Get a specific execution by ID.

        Args:
            job_id: Job identifier

        Returns:
            Execution dict or None
        """
        with self._get_service() as service:
            execution = service.get_execution(job_id)
            return service.to_dict(execution) if execution else None

    def mark_stale_executions(self, timeout_seconds: int = 7200) -> int:
        """Mark long-running executions as failed (interrupted).

        Args:
            timeout_seconds: Maximum execution time before marking as stale

        Returns:
            Number of executions marked as stale
        """
        LOG.info(
            f"ExecutionTracker.mark_stale_executions called "
            f"(timeout={timeout_seconds}s)"
        )
        with self._get_service() as service:
            marked = service.mark_stale_executions(timeout_seconds)
            if marked > 0:
                LOG.warning("Marked %d stale execution(s) as failed/cancelled", marked)
            else:
                LOG.info("No stale executions found")
            return marked

    def get_interrupted_paths(self) -> list[str]:
        """Get file paths from recently interrupted executions.

        Returns:
            List of file paths that were interrupted
        """
        with self._get_service() as service:
            executions = service.get_executions(limit=1000)
            paths = []
            for execution in executions:
                if (
                    execution.status == "completed"
                    and not execution.success
                    and execution.error_message
                    and "interrupted" in execution.error_message.lower()
                ):
                    if execution.path:
                        paths.append(execution.path)
            return paths

    def clear_old_executions(self, keep_count: int = 100):
        """Remove old executions, keeping only the most recent.

        Args:
            keep_count: Number of executions to keep
        """
        with self._get_service() as service:
            removed = service.clear_old_executions(keep_count)
            if removed > 0:
                LOG.info("Removed %d old execution(s)", removed)


# Global instance
_tracker: Optional[ExecutionTracker] = None


def get_tracker() -> ExecutionTracker:
    """Get or create the global execution tracker."""
    global _tracker
    if _tracker is None:
        _tracker = ExecutionTracker()
    return _tracker
