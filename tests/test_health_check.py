"""Tests for health_check module — ffprobe/ffmpeg detection, state/log file checks."""

import shutil
from unittest.mock import patch

from py_captions_for_channels.health_check import (
    check_state_file,
    check_log_file,
    check_ffprobe,
    check_ffmpeg,
)


class TestCheckStateFile:
    def test_creates_and_validates(self, tmp_path):
        sf = tmp_path / "state.json"
        with patch("py_captions_for_channels.health_check.STATE_FILE", str(sf)):
            assert check_state_file() is True
            assert sf.exists()

    def test_existing_file_is_ok(self, tmp_path):
        sf = tmp_path / "state.json"
        sf.write_text("{}")
        with patch("py_captions_for_channels.health_check.STATE_FILE", str(sf)):
            assert check_state_file() is True


class TestCheckLogFile:
    def test_writable(self, tmp_path):
        lf = tmp_path / "logs" / "app.log"
        with patch("py_captions_for_channels.health_check.LOG_FILE", str(lf)):
            assert check_log_file() is True
            assert lf.exists()


class TestCheckFfprobe:
    def test_available(self):
        with patch.object(shutil, "which", return_value="/usr/bin/ffprobe"):
            assert check_ffprobe() is True

    def test_missing(self):
        with patch.object(shutil, "which", return_value=None):
            assert check_ffprobe() is False


class TestCheckFfmpeg:
    def test_available(self):
        with patch.object(shutil, "which", return_value="/usr/bin/ffmpeg"):
            assert check_ffmpeg() is True

    def test_missing(self):
        with patch.object(shutil, "which", return_value=None):
            assert check_ffmpeg() is False
