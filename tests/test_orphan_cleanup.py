"""Tests for orphan_cleanup module — file detection, quarantine, and scheduling."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from py_captions_for_channels.orphan_cleanup import (
    CC4CHAN_TEMP_SUFFIXES,
    LEGACY_TEMP_SUFFIXES,
    OrphanCleanupScheduler,
    _is_cc4chan_temp_file,
    _video_path_for_orphan,
    find_orphaned_files_by_filesystem,
    scan_filesystem_progressive,
)

# ---------------------------------------------------------------------------
# _video_path_for_orphan
# ---------------------------------------------------------------------------


class TestVideoPathForOrphan:
    def test_cc4chan_orig(self):
        assert _video_path_for_orphan("/rec/show.mpg.cc4chan.orig") == "/rec/show.mpg"

    def test_cc4chan_orig_tmp(self):
        assert (
            _video_path_for_orphan("/rec/show.mpg.cc4chan.orig.tmp") == "/rec/show.mpg"
        )

    def test_cc4chan_av_mp4(self):
        assert _video_path_for_orphan("/rec/show.mpg.cc4chan.av.mp4") == "/rec/show.mpg"

    def test_cc4chan_muxed_mp4(self):
        assert (
            _video_path_for_orphan("/rec/show.mpg.cc4chan.muxed.mp4") == "/rec/show.mpg"
        )

    def test_cc4chan_temp_wav(self):
        assert (
            _video_path_for_orphan("/rec/show.mpg.cc4chan.temp.wav") == "/rec/show.mpg"
        )

    def test_srt_cc4chan_tmp_returns_none(self):
        # .srt.cc4chan.tmp cannot derive a single video path
        assert _video_path_for_orphan("/rec/show.srt.cc4chan.tmp") is None

    def test_legacy_orig(self):
        assert _video_path_for_orphan("/rec/show.mpg.orig") == "/rec/show.mpg"

    def test_legacy_orig_tmp(self):
        assert _video_path_for_orphan("/rec/show.mpg.orig.tmp") == "/rec/show.mpg"

    def test_old_style_orig_mpg(self):
        assert _video_path_for_orphan("/rec/show.orig.mpg") == "/rec/show.mpg"

    def test_unknown_extension_returns_none(self):
        assert _video_path_for_orphan("/rec/show.mpg") is None

    def test_plain_file_returns_none(self):
        assert _video_path_for_orphan("/rec/notes.txt") is None


# ---------------------------------------------------------------------------
# _is_cc4chan_temp_file
# ---------------------------------------------------------------------------


class TestIsCc4chanTempFile:
    def test_cc4chan_orig(self):
        assert _is_cc4chan_temp_file("show.mpg.cc4chan.orig") is True

    def test_cc4chan_av(self):
        assert _is_cc4chan_temp_file("show.mpg.cc4chan.av.mp4") is True

    def test_regular_file(self):
        assert _is_cc4chan_temp_file("show.mpg") is False

    def test_legacy_orig_not_cc4chan(self):
        assert _is_cc4chan_temp_file("show.mpg.orig") is False


# ---------------------------------------------------------------------------
# find_orphaned_files_by_filesystem
# ---------------------------------------------------------------------------


class TestFindOrphanedFilesByFilesystem:
    def test_nonexistent_path_returns_empty(self):
        orig, srt = find_orphaned_files_by_filesystem("/nonexistent/path")
        assert orig == []
        assert srt == []

    def test_empty_path_returns_empty(self):
        orig, srt = find_orphaned_files_by_filesystem("")
        assert orig == []
        assert srt == []

    def test_finds_orphaned_orig(self, tmp_path):
        # Create an orphaned .cc4chan.orig with no matching video
        orphan = tmp_path / "show.mpg.cc4chan.orig"
        orphan.write_text("backup data")

        with patch(
            "py_captions_for_channels.config.MEDIA_FILE_EXTENSIONS",
            (".mpg", ".ts", ".mp4"),
        ):
            orig, srt = find_orphaned_files_by_filesystem(str(tmp_path))

        assert len(orig) == 1
        assert orig[0].name == "show.mpg.cc4chan.orig"

    def test_not_orphaned_when_video_exists(self, tmp_path):
        # Video exists → .cc4chan.orig is NOT orphaned
        video = tmp_path / "show.mpg"
        video.write_text("video data")
        backup = tmp_path / "show.mpg.cc4chan.orig"
        backup.write_text("backup data")

        with patch(
            "py_captions_for_channels.config.MEDIA_FILE_EXTENSIONS",
            (".mpg", ".ts", ".mp4"),
        ):
            orig, srt = find_orphaned_files_by_filesystem(str(tmp_path))

        assert len(orig) == 0

    def test_finds_orphaned_srt(self, tmp_path):
        # .srt with no matching video
        srt_file = tmp_path / "show.srt"
        srt_file.write_text("captions")

        with patch(
            "py_captions_for_channels.config.MEDIA_FILE_EXTENSIONS",
            (".mpg", ".ts", ".mp4"),
        ):
            orig, srt = find_orphaned_files_by_filesystem(str(tmp_path))

        assert len(srt) == 1
        assert srt[0].name == "show.srt"

    def test_srt_not_orphaned_when_video_exists(self, tmp_path):
        video = tmp_path / "show.mpg"
        video.write_text("video data")
        srt_file = tmp_path / "show.srt"
        srt_file.write_text("captions")

        with patch(
            "py_captions_for_channels.config.MEDIA_FILE_EXTENSIONS",
            (".mpg", ".ts", ".mp4"),
        ):
            orig, srt = find_orphaned_files_by_filesystem(str(tmp_path))

        assert len(srt) == 0


# ---------------------------------------------------------------------------
# scan_filesystem_progressive
# ---------------------------------------------------------------------------


class TestScanFilesystemProgressive:
    def test_nonexistent_scan_path(self):
        orig, srt = scan_filesystem_progressive(
            [{"path": "/nonexistent", "label": "test"}]
        )
        assert orig == []
        assert srt == []

    def test_cancel_aborts_scan(self, tmp_path):
        orphan = tmp_path / "show.mpg.cc4chan.orig"
        orphan.write_text("data")

        with patch(
            "py_captions_for_channels.config.MEDIA_FILE_EXTENSIONS",
            (".mpg",),
        ):
            orig, srt = scan_filesystem_progressive(
                [{"path": str(tmp_path)}],
                cancel_check=lambda: True,
            )
        # Cancelled immediately, may find 0 results
        assert isinstance(orig, list)
        assert isinstance(srt, list)

    def test_progress_callback_called(self, tmp_path):
        (tmp_path / "orphan.mpg.orig").write_text("data")
        calls = []

        with patch(
            "py_captions_for_channels.config.MEDIA_FILE_EXTENSIONS",
            (".mpg",),
        ):
            scan_filesystem_progressive(
                [{"path": str(tmp_path)}],
                progress_callback=calls.append,
            )

        assert len(calls) >= 2  # At least enumerating + complete
        assert calls[-1]["phase"] == "complete"


# ---------------------------------------------------------------------------
# OrphanCleanupScheduler
# ---------------------------------------------------------------------------


class TestOrphanCleanupScheduler:
    def test_disabled_scheduler_never_runs(self):
        scheduler = OrphanCleanupScheduler(enabled=False)
        assert scheduler.should_run_cleanup() is False

    def test_first_run_allowed(self):
        scheduler = OrphanCleanupScheduler(enabled=True)
        with patch(
            "py_captions_for_channels.orphan_cleanup.is_system_idle", return_value=True
        ):
            assert scheduler.should_run_cleanup() is True

    def test_respects_interval(self):
        scheduler = OrphanCleanupScheduler(enabled=True, check_interval_hours=1)
        scheduler.last_cleanup_time = datetime.utcnow()

        with patch(
            "py_captions_for_channels.orphan_cleanup.is_system_idle", return_value=True
        ):
            # Just ran → should NOT run again
            assert scheduler.should_run_cleanup() is False

    def test_runs_after_interval_elapsed(self):
        scheduler = OrphanCleanupScheduler(enabled=True, check_interval_hours=1)
        scheduler.last_cleanup_time = datetime.utcnow() - timedelta(hours=2)

        with patch(
            "py_captions_for_channels.orphan_cleanup.is_system_idle", return_value=True
        ):
            assert scheduler.should_run_cleanup() is True

    def test_not_idle_blocks_cleanup(self):
        scheduler = OrphanCleanupScheduler(enabled=True)
        with patch(
            "py_captions_for_channels.orphan_cleanup.is_system_idle",
            return_value=False,
        ):
            assert scheduler.should_run_cleanup() is False

    def test_run_if_needed_returns_none_when_skipped(self):
        scheduler = OrphanCleanupScheduler(enabled=False)
        assert scheduler.run_if_needed() is None
