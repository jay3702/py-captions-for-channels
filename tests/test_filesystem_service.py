"""Tests for FilesystemService — distributed quarantine directory management."""

import os
from pathlib import Path

import pytest

from py_captions_for_channels.services.filesystem_service import (
    QUARANTINE_DIRNAME,
    FilesystemService,
)


@pytest.fixture
def fs_service(tmp_path):
    """Create a FilesystemService with a temporary fallback dir."""
    fallback = str(tmp_path / "fallback_quarantine")
    return FilesystemService(fallback_quarantine_dir=fallback)


@pytest.fixture
def scan_dirs(tmp_path):
    """Create two scan directories (same FS on dev machines)."""
    d1 = tmp_path / "media1"
    d2 = tmp_path / "media2"
    d1.mkdir()
    d2.mkdir()
    return d1, d2


class TestRegisterPath:
    def test_register_creates_quarantine_dir(self, fs_service, scan_dirs):
        d1, _ = scan_dirs
        info = fs_service.register_path(str(d1))

        assert info is not None
        quarantine = Path(info.quarantine_dir)
        assert quarantine.exists()
        assert quarantine.name == QUARANTINE_DIRNAME

    def test_register_nonexistent_path_returns_none(self, fs_service, tmp_path):
        info = fs_service.register_path(str(tmp_path / "does_not_exist"))
        assert info is None

    def test_same_fs_paths_share_quarantine_dir(self, fs_service, scan_dirs):
        d1, d2 = scan_dirs
        info1 = fs_service.register_path(str(d1))
        info2 = fs_service.register_path(str(d2))

        # Both are on the same tmp_path filesystem
        assert info1.quarantine_dir == info2.quarantine_dir
        assert len(info1.scan_paths) == 2  # same FilesystemInfo object

    def test_register_multiple_paths(self, fs_service, scan_dirs):
        d1, d2 = scan_dirs
        fs_service.register_paths([str(d1), str(d2)])
        assert fs_service.filesystem_count >= 1

    def test_duplicate_register_is_idempotent(self, fs_service, scan_dirs):
        d1, _ = scan_dirs
        fs_service.register_path(str(d1))
        fs_service.register_path(str(d1))
        info = fs_service._filesystems[os.stat(str(d1)).st_dev]
        assert info.scan_paths.count(str(d1)) == 1


class TestQuarantineDirFor:
    def test_returns_same_fs_quarantine(self, fs_service, scan_dirs, tmp_path):
        d1, _ = scan_dirs
        info = fs_service.register_path(str(d1))

        # Create a file under d1
        test_file = d1 / "test.mpg"
        test_file.write_text("dummy")

        qdir = fs_service.quarantine_dir_for(str(test_file))
        assert qdir == info.quarantine_dir

    def test_returns_fallback_for_unknown_fs(self, fs_service, tmp_path):
        # Don't register any paths — everything is unknown
        test_file = tmp_path / "some_file.mpg"
        test_file.write_text("dummy")

        qdir = fs_service.quarantine_dir_for(str(test_file))
        assert qdir == fs_service.fallback_dir

    def test_uses_parent_dir_when_file_missing(self, fs_service, scan_dirs):
        d1, _ = scan_dirs
        fs_service.register_path(str(d1))

        # File doesn't exist, but parent does
        missing = d1 / "nonexistent.mpg"
        qdir = fs_service.quarantine_dir_for(str(missing))
        info = fs_service._filesystems[os.stat(str(d1)).st_dev]
        assert qdir == info.quarantine_dir


class TestAnalysis:
    def test_get_analysis_returns_structure(self, fs_service, scan_dirs):
        d1, d2 = scan_dirs
        fs_service.register_path(str(d1))
        fs_service.register_path(str(d2))

        analysis = fs_service.get_analysis()
        assert "filesystems" in analysis
        assert "warnings" in analysis
        assert "fallback_quarantine_dir" in analysis
        assert analysis["total_scan_paths"] == 2

    def test_analysis_includes_disk_usage(self, fs_service, scan_dirs):
        d1, _ = scan_dirs
        fs_service.register_path(str(d1))

        analysis = fs_service.get_analysis()
        fs_entry = analysis["filesystems"][0]
        # total_bytes should be a positive integer (or None on exotic systems)
        assert fs_entry["total_bytes"] is None or fs_entry["total_bytes"] > 0

    def test_all_quarantine_dirs_includes_fallback(self, fs_service, scan_dirs):
        d1, _ = scan_dirs
        fs_service.register_path(str(d1))

        dirs = fs_service.all_quarantine_dirs
        assert fs_service.fallback_dir in dirs


class TestQuarantineServiceIntegration:
    """Test that QuarantineService uses FilesystemService for routing."""

    def test_quarantine_file_uses_fs_service(self, fs_service, scan_dirs, tmp_path):
        """Verify quarantine_file routes to the per-FS quarantine dir."""
        from py_captions_for_channels.database import get_db
        from py_captions_for_channels.services.quarantine_service import (
            QuarantineService,
        )

        d1, _ = scan_dirs
        fs_service.register_path(str(d1))

        db = next(get_db())
        service = QuarantineService(
            db, str(tmp_path / "fallback"), filesystem_service=fs_service
        )

        # Create a test file
        test_file = d1 / "test_recording.orig.mpg"
        test_file.write_bytes(b"x" * 100)

        item = service.quarantine_file(
            original_path=str(test_file),
            file_type="orig",
        )
        assert item is not None
        # File should have been moved to the per-FS quarantine dir, not fallback
        info = fs_service._filesystems[os.stat(str(d1)).st_dev]
        assert item.quarantine_path.startswith(info.quarantine_dir)
        assert not test_file.exists()
        assert Path(item.quarantine_path).exists()
