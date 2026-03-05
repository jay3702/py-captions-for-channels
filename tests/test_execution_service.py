"""Tests for ExecutionService — database-backed execution CRUD."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.services.execution_service import ExecutionService


@pytest.fixture
def service():
    """Provide a fresh ExecutionService with isolated DB."""
    db = next(get_db())
    yield ExecutionService(db)
    db.close()


class TestCreateExecution:
    def test_create_basic(self, service):
        ex = service.create_execution(
            job_id="job-1", title="Test Show", path="/rec/test.mpg"
        )
        assert ex.id == "job-1"
        assert ex.title == "Test Show"
        assert ex.status == "running"
        assert ex.kind == "normal"

    def test_create_with_explicit_timestamp(self, service):
        ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        ex = service.create_execution(job_id="job-ts", title="Show", started_at=ts)
        # SQLite may strip tzinfo; compare naive parts
        assert ex.started_at.replace(tzinfo=None) == ts.replace(tzinfo=None)

    def test_create_with_naive_timestamp_adds_utc(self, service):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        ex = service.create_execution(job_id="job-naive", title="Show", started_at=ts)
        # SQLite stores naive datetimes; just verify the value round-trips
        assert ex.started_at.replace(tzinfo=None) == ts


class TestGetExecution:
    def test_get_existing(self, service):
        service.create_execution(job_id="job-get", title="Show")
        ex = service.get_execution("job-get")
        assert ex is not None
        assert ex.title == "Show"

    def test_get_nonexistent_returns_none(self, service):
        assert service.get_execution("nonexistent") is None


class TestGetExecutions:
    def test_returns_most_recent_first(self, service):
        for i in range(5):
            ts = datetime(2026, 1, 15, 12, i, 0, tzinfo=timezone.utc)
            service.create_execution(
                job_id=f"job-{i}", title=f"Show {i}", started_at=ts
            )

        results = service.get_executions(limit=3)
        assert len(results) == 3
        assert results[0].id == "job-4"  # Most recent

    def test_filter_by_status(self, service):
        service.create_execution(job_id="r1", title="A", status="running")
        service.create_execution(job_id="c1", title="B", status="completed")

        running = service.get_executions(status="running")
        assert len(running) == 1
        assert running[0].id == "r1"


class TestUpdateStatus:
    def test_update_to_running_resets_started_at(self, service):
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        service.create_execution(
            job_id="job-u", title="Show", status="pending", started_at=ts
        )

        service.update_status("job-u", "running")
        ex = service.get_execution("job-u")
        assert ex.status == "running"
        # started_at should be reset to ~now, not the old timestamp
        # Normalize both to naive for comparison (SQLite strips tz)
        assert ex.started_at.replace(tzinfo=None) > ts.replace(tzinfo=None)

    def test_update_nonexistent_returns_false(self, service):
        assert service.update_status("nope", "running") is False


class TestCompleteExecution:
    def test_complete_success(self, service):
        service.create_execution(job_id="job-ok", title="Show")
        service.complete_execution("job-ok", success=True, elapsed_seconds=120.5)

        ex = service.get_execution("job-ok")
        assert ex.status == "completed"
        assert ex.success is True
        assert ex.elapsed_seconds == 120.5
        assert ex.completed_at is not None

    def test_complete_failure(self, service):
        service.create_execution(job_id="job-fail", title="Show")
        service.complete_execution(
            "job-fail", success=False, elapsed_seconds=10.0, error_message="crashed"
        )

        ex = service.get_execution("job-fail")
        assert ex.success is False
        assert ex.error_message == "crashed"

    def test_complete_nonexistent_returns_false(self, service):
        assert service.complete_execution("nope", True, 0.0) is False


class TestRequestCancel:
    def test_cancel_running(self, service):
        service.create_execution(job_id="job-c", title="Show", status="running")
        assert service.request_cancel("job-c") is True

        ex = service.get_execution("job-c")
        assert ex.cancel_requested is True
        assert ex.status == "canceling"

    def test_is_cancel_requested(self, service):
        service.create_execution(job_id="job-c2", title="Show")
        assert service.is_cancel_requested("job-c2") is False

        service.request_cancel("job-c2")
        assert service.is_cancel_requested("job-c2") is True


class TestRemoveExecution:
    def test_remove_existing(self, service):
        service.create_execution(job_id="job-rm", title="Show")
        assert service.remove_execution("job-rm") is True
        assert service.get_execution("job-rm") is None

    def test_remove_nonexistent(self, service):
        assert service.remove_execution("nope") is False


class TestMarkStaleExecutions:
    def test_marks_old_running_as_failed(self, service):
        old_ts = datetime.now(timezone.utc) - timedelta(hours=3)
        service.create_execution(
            job_id="stale-1", title="Old", status="running", started_at=old_ts
        )

        marked = service.mark_stale_executions(timeout_seconds=3600)
        assert marked >= 1

        ex = service.get_execution("stale-1")
        assert ex.status == "completed"
        assert ex.success is False
        assert (
            "interrupted" in ex.error_message.lower()
            or "timed out" in ex.error_message.lower()
        )

    def test_does_not_mark_recent_running(self, service):
        service.create_execution(job_id="fresh", title="New", status="running")
        service.mark_stale_executions(timeout_seconds=3600)
        # The fresh one should NOT be marked stale
        ex = service.get_execution("fresh")
        assert ex.status == "running"


class TestClearOldExecutions:
    def test_keeps_only_n_most_recent(self, service):
        for i in range(10):
            ts = datetime(2026, 1, 1, i, 0, 0, tzinfo=timezone.utc)
            service.create_execution(
                job_id=f"old-{i}", title=f"Show {i}", started_at=ts
            )

        removed = service.clear_old_executions(keep_count=3)
        assert removed == 7

        remaining = service.get_executions(limit=100)
        assert len(remaining) == 3


class TestArchiveAndRestore:
    def test_archive_and_restore(self, service, tmp_path):
        cutoff = datetime.now(timezone.utc)
        old_ts = cutoff - timedelta(days=2)
        service.create_execution(
            job_id="arc-1", title="Archived Show", started_at=old_ts
        )
        service.complete_execution("arc-1", success=True, elapsed_seconds=60.0)

        result = service.archive_executions_before_date(cutoff, str(tmp_path))
        assert result["archived"] == 1
        assert result["archive_file"] is not None
        assert os.path.exists(result["archive_file"])

        # Verify it was removed from DB
        assert service.get_execution("arc-1") is None

        # Restore it
        db = next(get_db())
        restore_result = ExecutionService.restore_archive(result["archive_file"], db)
        assert restore_result["restored"] == 1

        # Verify it's back
        ex = service.get_execution("arc-1")
        assert ex is not None
        assert ex.title == "Archived Show"

    def test_archive_empty_returns_zero(self, service, tmp_path):
        cutoff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        result = service.archive_executions_before_date(cutoff, str(tmp_path))
        assert result["archived"] == 0


class TestToDict:
    def test_to_dict_has_expected_keys(self, service):
        service.create_execution(job_id="dict-1", title="Show", path="/rec/test.mpg")
        ex = service.get_execution("dict-1")
        d = service.to_dict(ex)

        assert d["id"] == "dict-1"
        assert d["title"] == "Show"
        assert d["path"] == "/rec/test.mpg"
        assert "started_at" in d
        assert "status" in d
        assert "logs" in d  # Legacy compat


class TestAddStep:
    def test_add_and_update_step(self, service):
        service.create_execution(job_id="step-1", title="Show")
        step = service.add_step("step-1", "ffmpeg", status="pending")
        assert step is not None
        assert step.step_name == "ffmpeg"

        updated = service.update_step_status("step-1", "ffmpeg", "completed")
        assert updated is True

    def test_get_steps(self, service):
        service.create_execution(job_id="step-2", title="Show")
        service.add_step("step-2", "wav_extract")
        service.add_step("step-2", "whisper")
        service.add_step("step-2", "encode")

        steps = service.get_steps("step-2")
        assert len(steps) == 3
