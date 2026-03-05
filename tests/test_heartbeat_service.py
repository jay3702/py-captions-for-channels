"""Tests for HeartbeatService — beat, get, stale detection, clear."""

from datetime import datetime, timedelta, timezone

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.services.heartbeat_service import HeartbeatService


@pytest.fixture
def service():
    db = next(get_db())
    yield HeartbeatService(db)
    db.close()


class TestBeat:
    def test_first_beat_creates(self, service):
        service.beat("polling")
        hb = service.get_heartbeat("polling")
        assert hb is not None
        assert hb["status"] == "alive"

    def test_second_beat_updates(self, service):
        service.beat("polling")
        service.get_heartbeat("polling")
        service.beat("polling", status="stale")
        hb2 = service.get_heartbeat("polling")
        assert hb2["status"] == "stale"

    def test_custom_beat_time(self, service):
        custom = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        service.beat("web", beat_time=custom)
        hb = service.get_heartbeat("web")
        assert "2025-06-15" in hb["last_beat"]


class TestGetHeartbeat:
    def test_missing_returns_none(self, service):
        assert service.get_heartbeat("nonexistent") is None

    def test_includes_age(self, service):
        old = datetime.now(timezone.utc) - timedelta(seconds=60)
        service.beat("slow", beat_time=old)
        hb = service.get_heartbeat("slow")
        assert hb["age_seconds"] >= 59
        assert hb["alive"] is False  # > 30 seconds


class TestGetAllHeartbeats:
    def test_returns_all(self, service):
        service.beat("polling")
        service.beat("manual")
        service.beat("web")
        all_hb = service.get_all_heartbeats()
        assert len(all_hb) == 3
        assert "polling" in all_hb
        assert "manual" in all_hb


class TestCheckStale:
    def test_missing_is_stale(self, service):
        assert service.check_stale("ghost") is True

    def test_recent_is_not_stale(self, service):
        service.beat("fresh")
        assert service.check_stale("fresh", timeout_seconds=30) is False

    def test_old_is_stale(self, service):
        old = datetime.now(timezone.utc) - timedelta(seconds=60)
        service.beat("old", beat_time=old)
        assert service.check_stale("old", timeout_seconds=30) is True


class TestClearHeartbeat:
    def test_remove_existing(self, service):
        service.beat("temp")
        assert service.clear_heartbeat("temp") is True
        assert service.get_heartbeat("temp") is None

    def test_remove_nonexistent(self, service):
        assert service.clear_heartbeat("nope") is False


class TestClearAll:
    def test_clears_everything(self, service):
        service.beat("a")
        service.beat("b")
        removed = service.clear_all()
        assert removed == 2
        assert service.get_all_heartbeats() == {}
