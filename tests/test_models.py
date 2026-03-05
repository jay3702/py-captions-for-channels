"""Tests for SQLAlchemy models — creation, repr, and relationships."""

from datetime import datetime, timezone

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.models import (
    Execution,
    ExecutionStep,
    Heartbeat,
    ManualQueueItem,
    OrphanCleanupHistory,
    PollingCache,
    Progress,
    QuarantineItem,
    ScanPath,
    Setting,
)


@pytest.fixture
def db():
    gen = get_db()
    session = next(gen)
    yield session
    try:
        next(gen)
    except StopIteration:
        pass


class TestSettingModel:
    def test_create_and_repr(self, db):
        s = Setting(key="test_key", value="hello", value_type="string")
        db.add(s)
        db.commit()
        assert "test_key" in repr(s)

    def test_roundtrip(self, db):
        s = Setting(key="round", value="42", value_type="int")
        db.add(s)
        db.commit()
        loaded = db.query(Setting).filter_by(key="round").first()
        assert loaded.value == "42"
        assert loaded.value_type == "int"


class TestExecutionModel:
    def test_create_and_repr(self, db):
        ex = Execution(
            id="test-exec-1",
            title="Test Show",
            path="/rec/test.mpg",
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(ex)
        db.commit()
        assert "test-exec-1" in repr(ex)

    def test_execution_with_steps(self, db):
        ex = Execution(
            id="test-steps",
            title="Show",
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(ex)
        db.commit()

        step = ExecutionStep(
            execution_id="test-steps",
            step_name="ffmpeg",
            status="pending",
        )
        db.add(step)
        db.commit()

        loaded = db.query(Execution).filter_by(id="test-steps").first()
        assert len(loaded.steps) == 1
        assert loaded.steps[0].step_name == "ffmpeg"


class TestManualQueueItemModel:
    def test_create(self, db):
        item = ManualQueueItem(path="/rec/manual.mpg")
        db.add(item)
        db.commit()
        assert item.id is not None
        assert "manual.mpg" in repr(item)


class TestHeartbeatModel:
    def test_create(self, db):
        hb = Heartbeat(
            service_name="polling",
            last_beat=datetime.now(timezone.utc),
            status="alive",
        )
        db.add(hb)
        db.commit()
        assert "polling" in repr(hb)


class TestProgressModel:
    def test_create(self, db):
        p = Progress(
            job_id="prog-1",
            process_type="whisper",
            percent=45.5,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(p)
        db.commit()
        assert "prog-1" in repr(p)


class TestQuarantineItemModel:
    def test_create(self, db):
        qi = QuarantineItem(
            original_path="/rec/show.mpg.orig",
            quarantine_path="/data/quarantine/show.mpg.orig",
            file_type="orig",
            reason="orphaned_by_pipeline",
            status="quarantined",
            expires_at=datetime.now(timezone.utc),
        )
        db.add(qi)
        db.commit()
        assert qi.id is not None
        assert "quarantined" in repr(qi)


class TestPollingCacheModel:
    def test_create(self, db):
        pc = PollingCache(
            rec_id="rec-123",
            yielded_at=datetime.now(timezone.utc),
        )
        db.add(pc)
        db.commit()
        assert "rec-123" in repr(pc)


class TestScanPathModel:
    def test_create(self, db):
        sp = ScanPath(path="/mnt/recordings", label="Main DVR")
        db.add(sp)
        db.commit()
        assert sp.id is not None
        assert "Main DVR" in repr(sp) or "/mnt/recordings" in repr(sp)


class TestOrphanCleanupHistoryModel:
    def test_create(self, db):
        h = OrphanCleanupHistory(
            cleanup_timestamp=datetime.now(timezone.utc),
            orig_files_deleted=5,
            srt_files_deleted=3,
        )
        db.add(h)
        db.commit()
        assert h.id is not None
