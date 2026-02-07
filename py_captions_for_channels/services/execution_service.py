"""Execution service for database-backed execution tracking."""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import desc
from sqlalchemy.orm import Session
from ..models import Execution, ExecutionStep


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
    ) -> Execution:
        """Create a new execution record.

        Args:
            job_id: Unique job identifier
            title: Recording title
            path: File path (optional)
            status: Initial status (pending, running, completed)
            kind: Execution type (normal, manual_process, polling, webhook)
            started_at: Start timestamp (defaults to now)

        Returns:
            Created Execution object
        """
        if started_at is None:
            started_at = datetime.now(timezone.utc)
        elif started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        execution = Execution(
            id=job_id,
            title=title,
            path=path,
            status=status,
            kind=kind,
            started_at=started_at,
            cancel_requested=False,
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

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

    def update_status(self, job_id: str, status: str) -> bool:
        """Update execution status.

        Args:
            job_id: Job identifier
            status: New status

        Returns:
            True if execution was found and updated
        """
        execution = self.get_execution(job_id)
        if execution:
            execution.status = status
            self.db.commit()
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
            self.db.commit()
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
            self.db.commit()
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
            self.db.commit()
            return True
        return False

    def is_cancel_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job.

        Args:
            job_id: Job identifier

        Returns:
            True if cancel was requested
        """
        execution = self.get_execution(job_id)
        return bool(execution and execution.cancel_requested)

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
            self.db.commit()
            return True
        return False

    def mark_stale_executions(self, timeout_seconds: int = 7200) -> int:
        """Mark long-running executions as failed (interrupted).

        Args:
            timeout_seconds: Maximum execution time before marking as stale

        Returns:
            Number of executions marked as stale
        """
        now = datetime.now(timezone.utc)
        marked = 0

        running_execs = self.get_executions(limit=1000, status="running")
        for execution in running_execs:
            started_at = execution.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            elapsed = (now - started_at).total_seconds()

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

        if marked > 0:
            self.db.commit()

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

        self.db.commit()
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
        self.db.commit()
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
            self.db.commit()
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
        return {
            "id": execution.id,
            "title": execution.title,
            "path": execution.path,
            "status": execution.status,
            "kind": execution.kind,
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
