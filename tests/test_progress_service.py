"""Tests for ProgressService — update, get, clear, to_dict."""

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.services.progress_service import ProgressService


@pytest.fixture
def service():
    db = next(get_db())
    yield ProgressService(db)
    db.close()


class TestUpdateProgress:
    def test_create_new(self, service):
        prog = service.update_progress("job-1", "whisper", 50.0, "halfway")
        assert prog is not None
        assert prog.percent == 50.0

    def test_update_existing(self, service):
        service.update_progress("job-1", "whisper", 25.0)
        prog = service.update_progress("job-1", "ffmpeg", 75.0, "muxing")
        assert prog.process_type == "ffmpeg"
        assert prog.percent == 75.0

    def test_clamps_to_range(self, service):
        prog = service.update_progress("job-1", "whisper", 150.0)
        assert prog.percent == 100.0

        prog = service.update_progress("job-2", "whisper", -10.0)
        assert prog.percent == 0.0

    def test_with_details(self, service):
        details = {"speed": "2.5x", "eta": "30s"}
        prog = service.update_progress("job-1", "ffmpeg", 60.0, details=details)
        assert prog.progress_metadata is not None


class TestGetProgress:
    def test_existing(self, service):
        service.update_progress("job-1", "whisper", 50.0)
        prog = service.get_progress("job-1")
        assert prog is not None
        assert prog.job_id == "job-1"

    def test_missing(self, service):
        assert service.get_progress("nope") is None


class TestClearProgress:
    def test_clear_existing(self, service):
        service.update_progress("job-1", "whisper", 50.0)
        assert service.clear_progress("job-1") is True
        assert service.get_progress("job-1") is None

    def test_clear_missing(self, service):
        assert service.clear_progress("nope") is False


class TestClearAllProgress:
    def test_clears_all(self, service):
        service.update_progress("j1", "whisper", 10.0)
        service.update_progress("j2", "ffmpeg", 20.0)
        removed = service.clear_all_progress()
        assert removed == 2
        assert service.get_all_progress() == []


class TestToDict:
    def test_structure(self, service):
        service.update_progress("job-1", "whisper", 42.5, "running", {"speed": "1.0x"})
        prog = service.get_progress("job-1")
        d = service.to_dict(prog)
        assert d["process_type"] == "whisper"
        assert d["percent"] == 42.5
        assert d["message"] == "running"
        assert d["details"] == {"speed": "1.0x"}
        assert "updated_at" in d


class TestGetAllProgressDict:
    def test_returns_dict(self, service):
        service.update_progress("j1", "whisper", 10.0)
        service.update_progress("j2", "ffmpeg", 50.0)
        result = service.get_all_progress_dict()
        assert len(result) == 2
        assert "j1" in result
        assert result["j2"]["process_type"] == "ffmpeg"
