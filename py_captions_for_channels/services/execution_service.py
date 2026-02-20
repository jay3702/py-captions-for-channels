"""Execution service for database-backed execution tracking."""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session
from ..models import Execution, ExecutionStep, JobSequence

LOG = logging.getLogger(__name__)


class ExecutionService:
    """Service for managing pipeline executions in the database.

    Provides CRUD operations for Execution and ExecutionStep models.
    Replaces: JSON file storage in execution_tracker.py
    """

    def __init__(self, db: Session):
        self.db = db

    def create_execution(
        self,
        job_id: str,
        title: str,
        path: str = None,
        status: str = "running",
        kind: str = "normal",
        started_at: datetime = None,
        job_number: int = None,
        job_sequence: int = None,
    ) -> Execution:
        """Create a new execution record.

        Args:
            job_id: Unique job identifier
            title: Recording title
            path: File path (optional)
            status: Initial status (pending, running, completed)
            kind: Execution type (normal, manual_process, polling, webhook)
            started_at: Start timestamp (defaults to now)
            job_number: Sequential job number (optional)
            job_sequence: Autoincrement sequence number (optional)

        Returns:
            Created Execution object
        """
        if started_at is None:
            started_at = datetime.now(timezone.utc)
        elif started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        if job_sequence is None:
            job_sequence = self._allocate_job_sequence_id()

        execution = Execution(
            id=job_id,
            title=title,
            path=path,
            status=status,
            kind=kind,
            job_number=job_number,
            job_sequence=job_sequence,
            started_at=started_at,
            cancel_requested=False,
        )
        self.db.add(execution)
        try:
            self.db.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                pass
            else:
                try:
                    self.db.rollback()
                except Exception:
                    pass  # Rollback itself may fail if no transaction
                raise
        self.db.refresh(execution)
        return execution

    def _allocate_job_sequence_id(self) -> int:
        """Allocate a new autoincrement job sequence ID."""
        seq = JobSequence()
        self.db.add(seq)
        self.db.flush()
        return seq.id

    def get_execution(self, job_id: str) -> Optional[Execution]:
        """Get an execution by ID.

        Args:
            job_id: Job identifier

        Returns:
            Execution object or None
        """
        return self.db.query(Execution).filter(Execution.id == job_id).first()

    def get_executions(self, limit: int = 50, status: str = None) -> List[Execution]:
        """Get recent executions, most recent first.

        Args:
            limit: Maximum number of executions to return
            status: Filter by status (optional)

        Returns:
            List of Execution objects
        """
        query = self.db.query(Execution)
        if status:
            query = query.filter(Execution.status == status)
        return query.order_by(desc(Execution.started_at)).limit(limit).all()

    def get_daily_job_number(self, execution: Execution) -> Optional[int]:
        """Get the execution's number within its local day (1-indexed)."""
        if not execution.started_at:
            return None

        local_dt = execution.started_at.astimezone()
        day_start_local = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end_local = day_start_local + timedelta(days=1)

        day_start_utc = day_start_local.astimezone(timezone.utc)
        day_end_utc = day_end_local.astimezone(timezone.utc)

        day_execs = (
            self.db.query(Execution)
            .filter(Execution.started_at >= day_start_utc)
            .filter(Execution.started_at < day_end_utc)
            .order_by(
                asc(Execution.started_at),
                asc(Execution.job_sequence),
                asc(Execution.id),
            )
            .all()
        )

        for index, exec_item in enumerate(day_execs, start=1):
            if exec_item.id == execution.id:
                return index

        return None

    def update_status(self, job_id: str, status: str) -> bool:
        """Update execution status.

        When transitioning to 'running', also updates started_at to current time.
        This ensures elapsed time is calculated from actual processing start,
        not from initial discovery time.

        Args:
            job_id: Job identifier
            status: New status

        Returns:
            True if execution was found and updated
        """
        execution = self.get_execution(job_id)
        if execution:
            execution.status = status
            # Reset started_at when transitioning to running state
            # This ensures elapsed time is calculated from actual processing start,
            # not from discovery/pending time
            if status == "running":
                from datetime import datetime, timezone

                execution.started_at = datetime.now(timezone.utc)
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return True
        return False

    def update_execution(self, job_id: str, **kwargs) -> bool:
        """Update execution fields.

        Args:
            job_id: Job identifier
            **kwargs: Fields to update

        Returns:
            True if execution was found and updated
        """
        execution = self.get_execution(job_id)
        if execution:
            for key, value in kwargs.items():
                if hasattr(execution, key):
                    setattr(execution, key, value)
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return True
        return False

    def complete_execution(
        self,
        job_id: str,
        success: bool,
        elapsed_seconds: float,
        error_message: str = None,
    ) -> bool:
        """Mark an execution as completed.

        Args:
            job_id: Job identifier
            success: Whether execution succeeded
            elapsed_seconds: Total execution time
            error_message: Error message if failed

        Returns:
            True if execution was found and completed
        """
        execution = self.get_execution(job_id)
        if execution:
            execution.status = "completed"
            execution.success = success
            execution.completed_at = datetime.now(timezone.utc)
            execution.elapsed_seconds = elapsed_seconds
            execution.error_message = error_message
            execution.cancel_requested = False
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return True
        return False

    def request_cancel(self, job_id: str) -> bool:
        """Request cancellation of a running execution.

        Args:
            job_id: Job identifier

        Returns:
            True if execution was found and marked for cancel
        """
        execution = self.get_execution(job_id)
        if execution:
            execution.cancel_requested = True
            if execution.status == "running":
                execution.status = "canceling"
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return True
        return False

    def is_cancel_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job.

        Args:
            job_id: Job identifier

        Returns:
            True if cancel was requested
        """
        try:
            execution = self.get_execution(job_id)
            return bool(execution and execution.cancel_requested)
        except Exception as e:
            # If we can't check the database (connection closed, etc.),
            # assume not canceled so the process can continue
            LOG.warning(
                "Failed to check cancel status for %s: %s (assuming not canceled)",
                job_id,
                e,
            )
            return False

    def remove_execution(self, job_id: str) -> bool:
        """Remove an execution from the database.

        Args:
            job_id: Job identifier

        Returns:
            True if execution was found and removed
        """
        execution = self.get_execution(job_id)
        if execution:
            self.db.delete(execution)
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return True
        return False

    def mark_stale_executions(self, timeout_seconds: int = 7200) -> int:
        """Mark long-running and stuck executions as failed/cancelled.

        Handles:
        - Running executions that exceeded timeout -> mark as failed
        - Canceling executions (stuck from previous run) -> mark as cancelled

        Args:
            timeout_seconds: Maximum execution time before marking as stale

        Returns:
            Number of executions marked as stale
        """
        now = datetime.now(timezone.utc)
        marked = 0

        # Handle stuck "running" executions
        running_execs = self.get_executions(limit=1000, status="running")
        LOG.debug(f"Checking {len(running_execs)} running executions for staleness")
        for execution in running_execs:
            started_at = execution.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            elapsed = (now - started_at).total_seconds()
            LOG.debug(
                f"Running execution {execution.id}: elapsed={elapsed}s, "
                f"timeout={timeout_seconds}s"
            )

            if elapsed > timeout_seconds:
                execution.status = "completed"
                execution.success = False
                execution.completed_at = now
                execution.elapsed_seconds = elapsed
                execution.error_message = (
                    f"Execution interrupted or timed out "
                    f"(exceeded {timeout_seconds}s)"
                )
                marked += 1
                LOG.info(f"Marked running execution as failed: {execution.id}")

        # Handle stuck "canceling" executions from previous run
        canceling_execs = self.get_executions(limit=1000, status="canceling")
        LOG.debug(
            f"Checking {len(canceling_execs)} canceling executions from "
            f"previous run"
        )
        for execution in canceling_execs:
            execution.status = "cancelled"
            execution.success = False
            execution.completed_at = now
            started_at = execution.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            execution.elapsed_seconds = (now - started_at).total_seconds()
            execution.error_message = "Execution was canceling when service restarted"
            marked += 1
            LOG.info(f"Marked canceling execution as cancelled: {execution.id}")

        # Cleanup duplicate timestamped executions (bug fix from earlier versions)
        # Find executions with ::YYYYmmdd-HHMMSS pattern
        import re

        all_execs = self.db.query(Execution).all()
        duplicates_removed = 0
        timestamp_pattern = re.compile(r"::\d{8}-\d{6}$")

        for execution in all_execs:
            # Check if this is a timestamped duplicate
            if timestamp_pattern.search(execution.id):
                # Extract base ID (everything before ::timestamp)
                base_id = execution.id.rsplit("::", 1)[0]

                # Check if base execution exists
                base_exec = (
                    self.db.query(Execution).filter(Execution.id == base_id).first()
                )

                # Only delete timestamped duplicate if:
                # 1. It's in pending/cancelled status (not running/completed)
                # 2. Base execution exists
                if base_exec and execution.status in ("pending", "cancelled"):
                    LOG.info(
                        f"Removing duplicate timestamped execution: {execution.id} "
                        f"(base exists as {base_exec.status})"
                    )
                    self.db.delete(execution)
                    duplicates_removed += 1

        if duplicates_removed > 0:
            LOG.info(f"Removed {duplicates_removed} duplicate timestamped executions")
            marked += duplicates_removed

        if marked > 0:
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            LOG.debug(f"Committed {marked} stale execution updates to database")

        return marked

    def clear_old_executions(self, keep_count: int = 100) -> int:
        """Remove old executions, keeping only the most recent.

        Args:
            keep_count: Number of executions to keep

        Returns:
            Number of executions removed
        """
        # Get all executions sorted by started_at
        all_execs = self.db.query(Execution).order_by(desc(Execution.started_at)).all()

        if len(all_execs) <= keep_count:
            return 0

        # Delete old ones
        to_delete = all_execs[keep_count:]
        removed = len(to_delete)
        for execution in to_delete:
            self.db.delete(execution)

        try:
            self.db.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                pass
            else:
                try:
                    self.db.rollback()
                except Exception:
                    pass  # Rollback itself may fail if no transaction
                raise
        return removed

    def clear_executions_before_date(self, cutoff_date: datetime) -> int:
        """Remove executions older than a specific date.

        Args:
            cutoff_date: Delete executions with started_at before this date

        Returns:
            Number of executions removed
        """
        # Ensure cutoff_date is timezone-aware
        if cutoff_date.tzinfo is None:
            cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)

        # Find all executions before cutoff
        old_execs = (
            self.db.query(Execution).filter(Execution.started_at < cutoff_date).all()
        )

        if not old_execs:
            return 0

        removed = len(old_execs)
        for execution in old_execs:
            self.db.delete(execution)

        try:
            self.db.commit()
            LOG.info(f"Deleted {removed} executions older than {cutoff_date}")
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                pass
            else:
                try:
                    self.db.rollback()
                except Exception:
                    pass
                raise

        return removed

    # ExecutionStep methods

    def add_step(
        self,
        execution_id: str,
        step_name: str,
        status: str = "pending",
        input_path: str = None,
        output_path: str = None,
    ) -> Optional[ExecutionStep]:
        """Add a step to an execution.

        Args:
            execution_id: Execution ID
            step_name: Step identifier (wait_stable, create_temp, etc.)
            status: Step status (pending, running, completed, failed, skipped)
            input_path: Input file path
            output_path: Output file path

        Returns:
            Created ExecutionStep object or None if execution not found
        """
        execution = self.get_execution(execution_id)
        if not execution:
            return None

        step = ExecutionStep(
            execution_id=execution_id,
            step_name=step_name,
            status=status,
            input_path=input_path,
            output_path=output_path,
        )
        self.db.add(step)
        try:
            self.db.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                pass
            else:
                try:
                    self.db.rollback()
                except Exception:
                    pass  # Rollback itself may fail if no transaction
                raise
        self.db.refresh(step)
        return step

    def update_step_status(
        self, execution_id: str, step_name: str, status: str
    ) -> bool:
        """Update the status of a step.

        Args:
            execution_id: Execution ID
            step_name: Step identifier
            status: New status

        Returns:
            True if step was found and updated
        """
        step = (
            self.db.query(ExecutionStep)
            .filter(
                ExecutionStep.execution_id == execution_id,
                ExecutionStep.step_name == step_name,
            )
            .first()
        )
        if step:
            step.status = status
            if status == "running":
                step.started_at = datetime.now(timezone.utc)
            elif status in ("completed", "failed"):
                step.completed_at = datetime.now(timezone.utc)
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return True
        return False

    def get_steps(self, execution_id: str) -> List[ExecutionStep]:
        """Get all steps for an execution.

        Args:
            execution_id: Execution ID

        Returns:
            List of ExecutionStep objects
        """
        return (
            self.db.query(ExecutionStep)
            .filter(ExecutionStep.execution_id == execution_id)
            .all()
        )

    def to_dict(self, execution: Execution) -> dict:
        """Convert Execution object to dict (for API compatibility).

        Args:
            execution: Execution object

        Returns:
            Dictionary representation
        """
        job_number = self.get_daily_job_number(execution) if execution else None
        return {
            "id": execution.id,
            "title": execution.title,
            "path": execution.path,
            "status": execution.status,
            "kind": execution.kind,
            "job_number": job_number,
            "job_sequence": execution.job_sequence,
            "cancel_requested": execution.cancel_requested,
            "started_at": (
                execution.started_at.isoformat() if execution.started_at else None
            ),
            "completed_at": (
                execution.completed_at.isoformat() if execution.completed_at else None
            ),
            "success": execution.success,
            "elapsed_seconds": execution.elapsed_seconds,
            "error": execution.error_message,
            # Legacy fields for backward compatibility
            "logs": [],  # Logs now in main log file, not stored per-execution
        }
