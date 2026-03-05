"""Tests for ProgressTracker — database-backed progress tracking."""

from pathlib import Path

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.progress_tracker import ProgressTracker
from py_captions_for_channels.services.progress_service import ProgressService


@pytest.fixture
def tracker(tmp_path):
    """Create a ProgressTracker with a non-existent legacy JSON file."""
    legacy_file = tmp_path / "progress.json"
    return ProgressTracker(legacy_file)


class TestProgressTracker:
    def test_update_and_get(self, tracker):
        tracker.update_progress("job-1", "whisper", 50.0, "halfway")
        progress = tracker.get_progress("job-1")
        assert progress is not None
        assert progress["percent"] == 50.0
        assert progress["message"] == "halfway"

    def test_get_missing(self, tracker):
        assert tracker.get_progress("nope") is None

    def test_clear_progress(self, tracker):
        tracker.update_progress("job-1", "whisper", 50.0)
        tracker.clear_progress("job-1")
        assert tracker.get_progress("job-1") is None

    def test_get_all_progress(self, tracker):
        tracker.update_progress("j1", "whisper", 10.0)
        tracker.update_progress("j2", "ffmpeg", 80.0)
        all_prog = tracker.get_all_progress()
        assert len(all_prog) == 2
        assert "j1" in all_prog
        assert "j2" in all_prog

    def test_migrate_from_json(self, tmp_path):
        """Test migration from legacy JSON file to database."""
        import json

        legacy_file = tmp_path / "progress.json"
        legacy_file.write_text(
            json.dumps(
                {
                    "old-job": {
                        "process_type": "whisper",
                        "percent": 99.0,
                        "message": "almost done",
                    }
                }
            )
        )

        tracker = ProgressTracker(legacy_file)
        # After migration, the old data should be in the DB
        prog = tracker.get_progress("old-job")
        assert prog is not None
        assert prog["percent"] == 99.0
        # Original file should be renamed
        assert not legacy_file.exists()
        assert (tmp_path / "progress.json.migrated").exists()

    def test_no_migration_when_marker_exists(self, tmp_path):
        """Skip migration if marker file exists."""
        import json

        legacy_file = tmp_path / "progress.json"
        legacy_file.write_text(json.dumps({"stale": {"process_type": "x"}}))
        marker = tmp_path / ".progress_migrated"
        marker.touch()

        tracker = ProgressTracker(legacy_file)
        # Legacy file untouched, no migration
        assert legacy_file.exists()
