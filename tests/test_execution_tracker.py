"""Tests for ExecutionTracker — thread-safe wrapper around ExecutionService."""

import pytest

from py_captions_for_channels.execution_tracker import (
    ExecutionTracker,
    build_manual_process_job_id,
)


@pytest.fixture
def tracker(tmp_path):
    """Provide a fresh ExecutionTracker backed by isolated DB."""
    return ExecutionTracker(storage_path=str(tmp_path / "executions.json"))


class TestBuildManualProcessJobId:
    def test_format(self):
        result = build_manual_process_job_id("/rec/show.mpg")
        assert result == "manual_process::/rec/show.mpg"


class TestStartExecution:
    def test_start_returns_job_id(self, tracker):
        exec_id = tracker.start_execution(
            job_id="job-1", title="Test Show", path="/rec/test.mpg"
        )
        assert exec_id == "job-1"

    def test_start_duplicate_completed_gets_new_id(self, tracker):
        tracker.start_execution(job_id="job-dup", title="Show", path="/rec/test.mpg")
        tracker.complete_execution("job-dup", success=True, elapsed_seconds=60.0)

        # Starting again should give a new unique ID (for reprocessing)
        exec_id = tracker.start_execution(
            job_id="job-dup", title="Show", path="/rec/test.mpg"
        )
        assert exec_id != "job-dup"
        assert exec_id.startswith("job-dup::")

    def test_start_duplicate_running_returns_same_id(self, tracker):
        tracker.start_execution(job_id="job-active", title="Show", path="/rec/test.mpg")
        # Still running → should return same ID, not create duplicate
        exec_id = tracker.start_execution(
            job_id="job-active", title="Show", path="/rec/test.mpg"
        )
        assert exec_id == "job-active"


class TestUpdateStatus:
    def test_update_existing(self, tracker):
        tracker.start_execution(job_id="s-1", title="Show", path="/p")
        tracker.update_status("s-1", "pending")

        ex = tracker.get_execution("s-1")
        assert ex["status"] == "pending"


class TestCompleteExecution:
    def test_complete_success(self, tracker):
        tracker.start_execution(job_id="c-1", title="Show", path="/p")
        tracker.complete_execution("c-1", success=True, elapsed_seconds=120.0)

        ex = tracker.get_execution("c-1")
        assert ex["success"] is True
        assert ex["elapsed_seconds"] == 120.0

    def test_complete_failure_with_error(self, tracker):
        tracker.start_execution(job_id="c-2", title="Show", path="/p")
        tracker.complete_execution(
            "c-2", success=False, elapsed_seconds=5.0, error="Crashed"
        )

        ex = tracker.get_execution("c-2")
        assert ex["success"] is False
        assert ex["error"] == "Crashed"


class TestGetExecutions:
    def test_list_executions(self, tracker):
        for i in range(5):
            tracker.start_execution(job_id=f"l-{i}", title=f"Show {i}", path="/p")

        executions = tracker.get_executions(limit=3)
        assert len(executions) == 3

    def test_get_single_execution(self, tracker):
        tracker.start_execution(job_id="single", title="My Show", path="/p")
        ex = tracker.get_execution("single")
        assert ex is not None
        assert ex["title"] == "My Show"

    def test_get_nonexistent_returns_none(self, tracker):
        assert tracker.get_execution("nope") is None


class TestCancelExecution:
    def test_request_cancel(self, tracker):
        tracker.start_execution(job_id="cancel-1", title="Show", path="/p")
        assert tracker.request_cancel("cancel-1") is True
        assert tracker.is_cancel_requested("cancel-1") is True

    def test_cancel_nonexistent_returns_false(self, tracker):
        assert tracker.request_cancel("nope") is False
        assert tracker.is_cancel_requested("nope") is False


class TestRemoveExecution:
    def test_remove_existing(self, tracker):
        tracker.start_execution(job_id="rm-1", title="Show", path="/p")
        assert tracker.remove_execution("rm-1") is True
        assert tracker.get_execution("rm-1") is None

    def test_remove_nonexistent(self, tracker):
        assert tracker.remove_execution("nope") is False


class TestMarkStaleExecutions:
    def test_marks_stale(self, tracker):
        tracker.start_execution(
            job_id="stale-t",
            title="Old Show",
            path="/p",
            timestamp="2020-01-01T00:00:00",
        )

        marked = tracker.mark_stale_executions(timeout_seconds=60)
        assert marked >= 1


class TestClearOldExecutions:
    def test_clear_keeps_recent(self, tracker):
        for i in range(10):
            tracker.start_execution(job_id=f"clr-{i}", title=f"Show {i}", path="/p")

        tracker.clear_old_executions(keep_count=3)

        executions = tracker.get_executions(limit=100)
        assert len(executions) == 3
