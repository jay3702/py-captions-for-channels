"""Tests for config module — env helpers and configuration loading."""

from unittest.mock import patch

from py_captions_for_channels.config import (
    get_env_bool,
    get_env_int,
    translate_dvr_path,
)


class TestGetEnvBool:
    def test_true_values(self, monkeypatch):
        for val in ("true", "1", "yes", "on", "True", "YES", "ON"):
            monkeypatch.setenv("TEST_BOOL", val)
            assert get_env_bool("TEST_BOOL", False) is True

    def test_false_values(self, monkeypatch):
        for val in ("false", "0", "no", "off", "anything"):
            monkeypatch.setenv("TEST_BOOL", val)
            assert get_env_bool("TEST_BOOL", True) is False

    def test_unset_returns_default_true(self, monkeypatch):
        monkeypatch.delenv("TEST_BOOL_X", raising=False)
        assert get_env_bool("TEST_BOOL_X", True) is True

    def test_unset_returns_default_false(self, monkeypatch):
        monkeypatch.delenv("TEST_BOOL_Y", raising=False)
        assert get_env_bool("TEST_BOOL_Y", False) is False


class TestGetEnvInt:
    def test_valid_int(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "42")
        assert get_env_int("TEST_INT", 0) == 42

    def test_invalid_int_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "not_a_number")
        assert get_env_int("TEST_INT", 99) == 99

    def test_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("TEST_INT_X", raising=False)
        assert get_env_int("TEST_INT_X", 7) == 7

    def test_negative_int(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "-5")
        assert get_env_int("TEST_INT", 0) == -5

    def test_zero(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "0")
        assert get_env_int("TEST_INT", 10) == 0


# ---------------------------------------------------------------------------
# translate_dvr_path
# ---------------------------------------------------------------------------


class TestTranslateDvrPath:
    """Tests for translate_dvr_path() prefix mapping."""

    def test_both_prefixes_swaps(self):
        """When both prefixes are set, DVR prefix is swapped for local."""
        with patch(
            "py_captions_for_channels.config.DVR_PATH_PREFIX",
            "/home/channels/DVR",
        ), patch(
            "py_captions_for_channels.config.LOCAL_PATH_PREFIX",
            "/mnt/dvr-media",
        ):
            result = translate_dvr_path("/home/channels/DVR/TV/Show/ep.mpg")
            assert result == "/mnt/dvr-media/TV/Show/ep.mpg"

    def test_exact_prefix_path(self):
        """Path that is exactly the DVR prefix (no trailing content)."""
        with patch(
            "py_captions_for_channels.config.DVR_PATH_PREFIX",
            "/home/channels/DVR",
        ), patch(
            "py_captions_for_channels.config.LOCAL_PATH_PREFIX",
            "/mnt/dvr-media",
        ):
            result = translate_dvr_path("/home/channels/DVR")
            assert result == "/mnt/dvr-media"

    def test_path_not_matching_prefix_passthrough(self):
        """Path that doesn't start with DVR prefix passes through."""
        with patch(
            "py_captions_for_channels.config.DVR_PATH_PREFIX",
            "/home/channels/DVR",
        ), patch(
            "py_captions_for_channels.config.LOCAL_PATH_PREFIX",
            "/mnt/dvr-media",
        ):
            result = translate_dvr_path("/other/path/recording.mpg")
            assert result == "/other/path/recording.mpg"

    def test_no_prefixes_passthrough(self):
        """When no prefixes configured, paths pass through unchanged."""
        with patch(
            "py_captions_for_channels.config.DVR_PATH_PREFIX", None
        ), patch(
            "py_captions_for_channels.config.LOCAL_PATH_PREFIX", None
        ):
            result = translate_dvr_path("/recordings/show/ep.mpg")
            assert result == "/recordings/show/ep.mpg"

    def test_only_dvr_prefix_passthrough(self):
        """When only DVR prefix is set (no local), paths pass through."""
        with patch(
            "py_captions_for_channels.config.DVR_PATH_PREFIX",
            "/home/channels/DVR",
        ), patch(
            "py_captions_for_channels.config.LOCAL_PATH_PREFIX", None
        ):
            result = translate_dvr_path("/home/channels/DVR/TV/ep.mpg")
            assert result == "/home/channels/DVR/TV/ep.mpg"

    def test_only_local_prefix_passthrough(self):
        """When only local prefix is set (no DVR), paths pass through."""
        with patch(
            "py_captions_for_channels.config.DVR_PATH_PREFIX", None
        ), patch(
            "py_captions_for_channels.config.LOCAL_PATH_PREFIX",
            "/mnt/dvr-media",
        ):
            result = translate_dvr_path("/recordings/show/ep.mpg")
            assert result == "/recordings/show/ep.mpg"

    def test_windows_style_paths(self):
        """Prefix mapping works with Windows-style paths."""
        with patch(
            "py_captions_for_channels.config.DVR_PATH_PREFIX", "D:/DVR"
        ), patch(
            "py_captions_for_channels.config.LOCAL_PATH_PREFIX",
            "Z:/shared/dvr",
        ):
            result = translate_dvr_path("D:/DVR/TV/Show/ep.mpg")
            assert result == "Z:/shared/dvr/TV/Show/ep.mpg"

    def test_preserves_deep_path_structure(self):
        """Translation preserves the full path after the prefix."""
        with patch(
            "py_captions_for_channels.config.DVR_PATH_PREFIX",
            "/dvr",
        ), patch(
            "py_captions_for_channels.config.LOCAL_PATH_PREFIX",
            "/mnt/remote",
        ):
            deep = "/dvr/TV/2026/01/Show Name/S01E05 Title.mpg"
            result = translate_dvr_path(deep)
            assert result == "/mnt/remote/TV/2026/01/Show Name/S01E05 Title.mpg"
