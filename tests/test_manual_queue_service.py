"""Tests for ManualQueueService — add, get, remove, clear, to_dict."""

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.services.manual_queue_service import ManualQueueService


@pytest.fixture
def service():
    db = next(get_db())
    yield ManualQueueService(db)
    db.close()


class TestAddToQueue:
    def test_add_new(self, service):
        item = service.add_to_queue("/rec/show.mpg")
        assert item.path == "/rec/show.mpg"
        assert item.skip_caption_generation is False
        assert item.log_verbosity == "NORMAL"

    def test_add_with_options(self, service):
        item = service.add_to_queue(
            "/rec/show.mpg",
            skip_caption_generation=True,
            log_verbosity="DEBUG",
        )
        assert item.skip_caption_generation is True
        assert item.log_verbosity == "DEBUG"

    def test_add_duplicate_updates(self, service):
        service.add_to_queue("/rec/show.mpg", log_verbosity="NORMAL")
        item = service.add_to_queue("/rec/show.mpg", log_verbosity="DEBUG")
        assert item.log_verbosity == "DEBUG"
        # Should still have only one item
        assert len(service.get_queue()) == 1


class TestGetQueue:
    def test_empty(self, service):
        assert service.get_queue() == []

    def test_ordered(self, service):
        service.add_to_queue("/rec/a.mpg")
        service.add_to_queue("/rec/b.mpg")
        queue = service.get_queue()
        assert len(queue) == 2
        assert queue[0].path == "/rec/a.mpg"


class TestGetQueuePaths:
    def test_returns_paths(self, service):
        service.add_to_queue("/rec/a.mpg")
        service.add_to_queue("/rec/b.mpg")
        paths = service.get_queue_paths()
        assert paths == ["/rec/a.mpg", "/rec/b.mpg"]


class TestHasPath:
    def test_present(self, service):
        service.add_to_queue("/rec/show.mpg")
        assert service.has_path("/rec/show.mpg") is True

    def test_absent(self, service):
        assert service.has_path("/rec/nope.mpg") is False


class TestRemoveFromQueue:
    def test_remove_existing(self, service):
        service.add_to_queue("/rec/show.mpg")
        assert service.remove_from_queue("/rec/show.mpg") is True
        assert service.has_path("/rec/show.mpg") is False

    def test_remove_nonexistent(self, service):
        assert service.remove_from_queue("/rec/nope.mpg") is False


class TestClearQueue:
    def test_clear(self, service):
        service.add_to_queue("/rec/a.mpg")
        service.add_to_queue("/rec/b.mpg")
        removed = service.clear_queue()
        assert removed == 2
        assert service.get_queue() == []


class TestToDict:
    def test_structure(self, service):
        item = service.add_to_queue("/rec/show.mpg")
        d = service.to_dict(item)
        assert d["path"] == "/rec/show.mpg"
        assert "added_at" in d
        assert "updated_at" in d
        assert "skip_caption_generation" in d
        assert "log_verbosity" in d
