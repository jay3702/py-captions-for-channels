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


class TestSplitCaptionSegment:
    def test_short_text_single_cue(self):
        from py_captions_for_channels.embed_captions import split_caption_segment

        assert split_caption_segment(1.0, 3.0, "Hello there.", 42) == [
            (1.0, 3.0, "Hello there.")
        ]

    def test_two_line_text_stays_one_cue(self):
        from py_captions_for_channels.embed_captions import split_caption_segment

        text = "This sentence is long enough to need a second line here."
        cues = split_caption_segment(0.0, 4.0, text, 42)
        assert len(cues) == 1
        assert cues[0][2].count("\n") == 1

    def test_long_segment_split_into_two_line_cues(self):
        from py_captions_for_channels.embed_captions import split_caption_segment

        text = " ".join(["word%d" % n for n in range(60)])  # ~400 chars
        cues = split_caption_segment(10.0, 40.0, text, 42)
        assert len(cues) > 1
        for _, _, cue_text in cues:
            lines = cue_text.split("\n")
            assert len(lines) <= 2
            assert all(len(line) <= 42 for line in lines)
        # All words preserved, in order
        assert " ".join(c[2].replace("\n", " ") for c in cues) == text
        # Timing covers the segment contiguously
        assert cues[0][0] == 10.0
        assert cues[-1][1] == 40.0
        for prev, nxt in zip(cues, cues[1:]):
            assert prev[1] == nxt[0]
            assert prev[0] < prev[1]

    def test_disabled_returns_unchanged(self):
        from py_captions_for_channels.embed_captions import split_caption_segment

        text = "x " * 200
        assert split_caption_segment(0.0, 1.0, text, 0) == [
            (0.0, 1.0, " ".join(text.split()))
        ]
