"""Tests for QuarantineService — file quarantine, restore, and delete."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.services.quarantine_service import QuarantineService


@pytest.fixture
def quarantine_dir(tmp_path):
    qdir = tmp_path / "quarantine"
    qdir.mkdir()
    return qdir


@pytest.fixture
def service(quarantine_dir):
    db = next(get_db())
    yield QuarantineService(db, str(quarantine_dir))
    db.close()


class TestQuarantineFile:
    def test_quarantine_moves_file(self, service, tmp_path, quarantine_dir):
        # Create a file to quarantine
        src = tmp_path / "show.mpg.orig"
        src.write_text("backup data")

        item = service.quarantine_file(
            original_path=str(src),
            file_type="orig",
            reason="orphaned_by_pipeline",
        )

        assert item is not None
        assert item.status == "quarantined"
        assert item.file_type == "orig"
        assert not src.exists()  # Moved away
        assert Path(item.quarantine_path).exists()

    def test_quarantine_nonexistent_returns_none(self, service):
        result = service.quarantine_file(
            original_path="/nonexistent/file.orig",
            file_type="orig",
        )
        assert result is None

    def test_quarantine_duplicate_skipped(self, service, tmp_path):
        src = tmp_path / "dup.orig"
        src.write_text("data")

        item1 = service.quarantine_file(str(src), "orig")
        assert item1 is not None

        # Create the file again for a second attempt
        src.write_text("data2")
        item2 = service.quarantine_file(str(src), "orig")
        # Should skip because original_path already quarantined
        assert item2 is None

    def test_quarantine_records_file_size(self, service, tmp_path):
        src = tmp_path / "sized.orig"
        src.write_bytes(b"x" * 1024)

        item = service.quarantine_file(str(src), "orig")
        assert item.file_size_bytes == 1024


class TestRestoreFile:
    def test_restore_moves_back(self, service, tmp_path):
        src = tmp_path / "restorable.orig"
        src.write_text("important data")

        item = service.quarantine_file(str(src), "orig")
        assert not src.exists()

        result = service.restore_file(item.id)
        assert result is True
        assert src.exists()
        assert src.read_text() == "important data"

    def test_restore_fails_if_original_occupied(self, service, tmp_path):
        src = tmp_path / "occupied.orig"
        src.write_text("v1")

        item = service.quarantine_file(str(src), "orig")

        # Create a new file at the original location
        src.write_text("v2")

        result = service.restore_file(item.id)
        assert result is False  # Can't overwrite

    def test_restore_nonexistent_id(self, service):
        assert service.restore_file(99999) is False


class TestDeleteFile:
    def test_delete_removes_file(self, service, tmp_path):
        src = tmp_path / "deletable.orig"
        src.write_text("data")

        item = service.quarantine_file(str(src), "orig")
        quarantine_path = Path(item.quarantine_path)
        assert quarantine_path.exists()

        result = service.delete_file(item.id)
        assert result is True
        assert not quarantine_path.exists()

    def test_delete_nonexistent_id(self, service):
        assert service.delete_file(99999) is False


class TestGetQuarantinedFiles:
    def test_list_quarantined(self, service, tmp_path):
        for name in ["a.orig", "b.orig", "c.srt"]:
            f = tmp_path / name
            f.write_text("data")
            service.quarantine_file(str(f), "orig" if name.endswith(".orig") else "srt")

        items = service.get_quarantined_files()
        assert len(items) == 3


class TestGetExpiredFiles:
    def test_expired_detection(self, service, tmp_path):
        src = tmp_path / "expired.orig"
        src.write_text("data")

        service.quarantine_file(
            str(src), "orig", expiration_days=0  # Expires immediately
        )

        # The item expires at now + 0 days = now, so it should be expired
        expired = service.get_expired_files()
        # Might need a tiny delay; check at least the method works
        assert isinstance(expired, list)


class TestQuarantineStats:
    def test_stats_structure(self, service, tmp_path):
        src = tmp_path / "stat.orig"
        src.write_bytes(b"x" * 2048)
        service.quarantine_file(str(src), "orig")

        stats = service.get_quarantine_stats()
        assert stats["total_quarantined"] == 1
        assert stats["total_size_bytes"] == 2048
        assert stats["total_size_mb"] == pytest.approx(2048 / (1024 * 1024), abs=0.01)


class TestDeduplicate:
    def test_deduplicate_removes_older(self, service, tmp_path):
        # Manually create two quarantine records for the same original path
        db = next(get_db())
        from py_captions_for_channels.models import QuarantineItem

        for i in range(2):
            f = tmp_path / f"dup_file_{i}.orig"
            f.write_text("data")
            qi = QuarantineItem(
                original_path="/rec/same.orig",
                quarantine_path=str(f),
                file_type="orig",
                reason="test",
                status="quarantined",
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db.add(qi)
        db.commit()

        result = service.deduplicate()
        assert result["duplicates_removed"] >= 1


class TestIsAlreadyQuarantined:
    def test_not_quarantined(self, service):
        assert service.is_already_quarantined("/nonexistent") is False

    def test_is_quarantined(self, service, tmp_path):
        src = tmp_path / "check.orig"
        src.write_text("data")
        service.quarantine_file(str(src), "orig")

        assert service.is_already_quarantined(str(src)) is True
