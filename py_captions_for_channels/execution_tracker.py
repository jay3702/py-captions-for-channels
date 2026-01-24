"""
Execution tracker for pipeline runs.

Tracks active and completed pipeline executions for display in the web UI.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

LOG = logging.getLogger(__name__)


def build_reprocess_job_id(path: str) -> str:
    """Build a stable job ID for reprocess executions."""
    return f"reprocess::{path}"


class ExecutionTracker:
    """Thread-safe tracker for pipeline executions."""

    def __init__(self, storage_path: str = "/app/data/executions.json"):
        self.storage_path = Path(storage_path)
        self.lock = threading.Lock()
        self.executions: Dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load executions from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    self.executions = data.get("executions", {})
                    # Backfill missing IDs for older records
                    for key, val in list(self.executions.items()):
                        if isinstance(val, dict) and "id" not in val:
                            val["id"] = key
            except Exception as e:
                LOG.warning("Failed to load executions: %s", e)
                self.executions = {}

    def _save(self):
        """Save executions to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w") as f:
                json.dump({"executions": self.executions}, f, indent=2)
        except Exception as e:
            LOG.error("Failed to save executions: %s", e)

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

        Returns:
            Execution ID
        """
        with self.lock:
            exec_id = job_id  # Use job_id as execution ID
            self.executions[exec_id] = {
                "id": exec_id,
                "title": title,
                "path": path,
                "kind": kind,
                "status": status,
                "started_at": timestamp or datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
                "success": None,
                "elapsed_seconds": 0.0,
                "logs": [],
                "error": None,
            }
            self._save()
            LOG.info(
                "Started tracking execution: %s [%s] (total: %d)",
                exec_id,
                status,
                len(self.executions),
            )
            return exec_id

    def update_status(self, job_id: str, status: str):
        """Update the status of an execution.

        Args:
            job_id: Job identifier
            status: New status (pending, running, completed)
        """
        with self.lock:
            if job_id in self.executions:
                self.executions[job_id]["status"] = status
                self._save()
                LOG.debug("Updated execution status: %s -> %s", job_id, status)

    def add_log(self, job_id: str, log_line: str):
        """Add a log line to an execution.

        Args:
            job_id: Job identifier
            log_line: Log line to append
        """
        with self.lock:
            if job_id in self.executions:
                self.executions[job_id]["logs"].append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": log_line,
                    }
                )
                # Keep only last 500 log lines per execution
                self.executions[job_id]["logs"] = self.executions[job_id]["logs"][-500:]

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
            if job_id in self.executions:
                self.executions[job_id].update(
                    {
                        "status": "completed",
                        "success": success,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "elapsed_seconds": elapsed_seconds,
                        "error": error,
                    }
                )
                self._save()
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
        self._load()
        with self.lock:
            # Sort by started_at descending
            sorted_execs = sorted(
                self.executions.values(),
                key=lambda x: x.get("started_at", ""),
                reverse=True,
            )
            return sorted_execs[:limit]

    def get_execution(self, job_id: str) -> Optional[dict]:
        """Get a specific execution by ID.

        Args:
            job_id: Job identifier

        Returns:
            Execution dict or None
        """
        self._load()
        with self.lock:
            return self.executions.get(job_id)

    def mark_stale_executions(self, timeout_seconds: int = 7200) -> int:
        """Mark long-running executions as failed (interrupted).

        Args:
            timeout_seconds: Maximum execution time before marking as stale

        Returns:
            Number of executions marked as stale
        """
        marked = 0
        now = datetime.now(timezone.utc)

        with self.lock:
            for exec_id, exec_data in self.executions.items():
                if exec_data.get("status") != "running":
                    continue

                started_at = datetime.fromisoformat(exec_data["started_at"])
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed = (now - started_at).total_seconds()

                if elapsed > timeout_seconds:
                    exec_data.update(
                        {
                            "status": "completed",
                            "success": False,
                            "completed_at": now.isoformat(),
                            "elapsed_seconds": elapsed,
                            "error": (
                                f"Execution interrupted or timed out "
                                f"(exceeded {timeout_seconds}s)"
                            ),
                        }
                    )
                    marked += 1
                    LOG.warning(
                        "Marked stale execution as failed: %s (elapsed: %.1fs)",
                        exec_id,
                        elapsed,
                    )

            if marked > 0:
                self._save()

        return marked

    def get_interrupted_paths(self) -> list[str]:
        """Get file paths from recently interrupted executions.

        Returns:
            List of file paths that were interrupted
        """
        paths = []
        with self.lock:
            for exec_data in self.executions.values():
                if (
                    exec_data.get("status") == "completed"
                    and not exec_data.get("success")
                    and "interrupted" in exec_data.get("error", "").lower()
                ):
                    paths.append(exec_data.get("path"))
        return paths

    def clear_old_executions(self, keep_count: int = 100):
        """Remove old executions, keeping only the most recent.

        Args:
            keep_count: Number of executions to keep
        """
        with self.lock:
            sorted_execs = sorted(
                self.executions.items(),
                key=lambda x: x[1].get("started_at", ""),
                reverse=True,
            )
            # Keep only the most recent
            self.executions = dict(sorted_execs[:keep_count])
            self._save()


# Global instance
_tracker: Optional[ExecutionTracker] = None


def get_tracker() -> ExecutionTracker:
    """Get or create the global execution tracker."""
    global _tracker
    if _tracker is None:
        _tracker = ExecutionTracker()
    return _tracker
