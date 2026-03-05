"""Tests for embed_captions — extract_channel_number, GPUBackend, StepTracker."""

from unittest.mock import patch

from py_captions_for_channels.embed_captions import extract_channel_number


class TestExtractChannelNumber:
    """Test channel number extraction from recording file paths."""

    def test_ota_channel_in_directory(self):
        # Pattern 1: "4.1 KRON" in path
        path = "/recordings/TV/4.1 KRON/News at 10/ep.mpg"
        assert extract_channel_number(path) == "4.1"

    def test_ota_channel_double_digit(self):
        path = "/recordings/TV/11.3 KNTV/Show/ep.mpg"
        assert extract_channel_number(path) == "11.3"

    def test_tve_channel_in_directory(self):
        # Pattern 2: "6030 CNN" in path
        path = "/recordings/TV/6030 CNN/Wolf Blitzer/ep.mpg"
        assert extract_channel_number(path) == "6030"

    def test_ota_channel_with_dash(self):
        path = "/recordings/TV/4.1 - KRON/News/ep.mpg"
        assert extract_channel_number(path) == "4.1"

    def test_tve_channel_with_dash(self):
        path = "/recordings/TV/6030-CNN/Show/ep.mpg"
        assert extract_channel_number(path) == "6030"

    def test_strips_cc4chan_suffix(self):
        # Should normalize away the .cc4chan.orig before parsing
        path = "/recordings/TV/4.1 KRON/News/ep.mpg.cc4chan.orig"
        assert extract_channel_number(path) == "4.1"

    def test_strips_orig_suffix(self):
        path = "/recordings/TV/4.1 KRON/News/ep.mpg.orig"
        assert extract_channel_number(path) == "4.1"

    def test_strips_cc4chan_muxed(self):
        path = "/recordings/TV/4.1 KRON/News/ep.mpg.cc4chan.muxed.mp4"
        assert extract_channel_number(path) == "4.1"

    def test_no_channel_info(self):
        # When no pattern matches AND API lookup fails
        with patch("py_captions_for_channels.channels_api.ChannelsAPI") as mock_api_cls:
            mock_api_cls.return_value.get_channel_by_path.return_value = None
            result = extract_channel_number("/tmp/random/file.mpg")
        assert result is None

    def test_filename_ota_pattern(self):
        # Pattern 3: channel in filename
        path = "/recordings/Recording-4.1-News.mpg"
        assert extract_channel_number(path) == "4.1"

    def test_filename_tve_pattern(self):
        path = "/recordings/Recording_6030_CNN.mpg"
        assert extract_channel_number(path) == "6030"

    def test_api_fallback(self):
        # Pattern 4: fall back to API
        with patch("py_captions_for_channels.channels_api.ChannelsAPI") as mock_api_cls:
            mock_api_cls.return_value.get_channel_by_path.return_value = "7.1"
            result = extract_channel_number("/plain/path/file.mpg")
        assert result == "7.1"
