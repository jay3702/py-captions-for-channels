"""Tests for PollingCacheService — add, has, get, cleanup, clear."""

from datetime import datetime, timedelta, timezone

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.services.polling_cache_service import PollingCacheService


@pytest.fixture
def service():
    db = next(get_db())
    yield PollingCacheService(db)
    db.close()


class TestAddYielded:
    def test_add_new_returns_true(self, service):
        assert service.add_yielded("rec-123") is True

    def test_add_duplicate_returns_false(self, service):
        service.add_yielded("rec-123")
        assert service.add_yielded("rec-123") is False

    def test_custom_timestamp(self, service):
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        service.add_yielded("rec-456", yielded_at=ts)
        result = service.get_yielded_time("rec-456")
        assert result is not None


class TestHasYielded:
    def test_present(self, service):
        service.add_yielded("rec-789")
        assert service.has_yielded("rec-789") is True

    def test_absent(self, service):
        assert service.has_yielded("rec-nope") is False


class TestGetYieldedTime:
    def test_existing(self, service):
        service.add_yielded("rec-100")
        result = service.get_yielded_time("rec-100")
        assert result is not None

    def test_missing(self, service):
        assert service.get_yielded_time("rec-nope") is None


class TestCleanupOld:
    def test_removes_old_entries(self, service):
        old_time = datetime.now(timezone.utc) - timedelta(hours=48)
        service.add_yielded("old-rec", yielded_at=old_time)
        service.add_yielded("new-rec")

        removed = service.cleanup_old(max_age_hours=24)
        assert removed == 1
        assert service.has_yielded("old-rec") is False
        assert service.has_yielded("new-rec") is True


class TestGetAll:
    def test_returns_dict(self, service):
        service.add_yielded("a")
        service.add_yielded("b")
        result = service.get_all()
        assert len(result) == 2
        assert "a" in result
        assert "b" in result


class TestClearAll:
    def test_clears_everything(self, service):
        service.add_yielded("x")
        service.add_yielded("y")
        removed = service.clear_all()
        assert removed == 2
        assert service.get_all() == {}
