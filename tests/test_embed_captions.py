"""Tests for embed_captions — extract_channel_number, GPUBackend, StepTracker."""

from unittest.mock import patch

import pytest

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

    def test_no_hard_line_break_when_slightly_over_line_length(self):
        from py_captions_for_channels.embed_captions import split_caption_segment

        # 45 chars: the old hard wrap at 42 left one word alone on line two
        # even though the player could fit it all on one line.
        text = "We will be right back after these messages ok"
        assert split_caption_segment(0.0, 4.0, text, 42) == [(0.0, 4.0, text)]

    def test_text_within_line_budget_stays_one_cue(self):
        from py_captions_for_channels.embed_captions import split_caption_segment

        text = "This sentence is long enough to need a second line here."
        assert split_caption_segment(0.0, 4.0, text, 42, max_lines=2) == [
            (0.0, 4.0, text)
        ]

    def test_one_line_setting_splits_into_more_cues(self):
        from py_captions_for_channels.embed_captions import split_caption_segment

        text = "This sentence is long enough to need a second line here."
        cues = split_caption_segment(0.0, 4.0, text, 42, max_lines=1)
        assert len(cues) == 2
        assert all(len(c[2]) <= 42 for c in cues)
        assert " ".join(c[2] for c in cues) == text
        assert cues[0][0] == 0.0 and cues[-1][1] == 4.0

    @pytest.mark.parametrize("max_lines", [1, 2, 3])
    def test_long_segment_split_into_capped_cues(self, max_lines):
        from py_captions_for_channels.embed_captions import split_caption_segment

        text = " ".join(["word%d" % n for n in range(60)])  # ~400 chars
        cues = split_caption_segment(10.0, 40.0, text, 42, max_lines=max_lines)
        assert len(cues) > 1
        for _, _, cue_text in cues:
            assert "\n" not in cue_text
            assert len(cue_text) <= 42 * max_lines
        # All words preserved, in order
        assert " ".join(c[2] for c in cues) == text
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

    def test_word_timings_start_cue_when_speech_starts(self):
        from types import SimpleNamespace as W

        from py_captions_for_channels.embed_captions import split_caption_segment

        # VAD pulled the segment start back to the end of the previous speech
        # (100s); the words are actually spoken 15s later, after the break.
        words = [
            W(word=" Welcome", start=115.0, end=115.4),
            W(word=" back", start=115.4, end=115.7),
            W(word=" to", start=115.7, end=115.8),
            W(word=" the", start=115.8, end=115.9),
            W(word=" show.", start=115.9, end=116.3),
        ]
        cues = split_caption_segment(
            100.0, 118.0, "Welcome back to the show.", 42, words=words
        )
        assert cues == [(115.0, 117.3, "Welcome back to the show.")]

    def test_word_timings_split_long_segment_around_pause(self):
        from types import SimpleNamespace as W

        from py_captions_for_channels.embed_captions import split_caption_segment

        first = [
            W(word=" word%d" % n, start=n * 0.3, end=n * 0.3 + 0.25) for n in range(12)
        ]
        # 20s pause, then more speech in the same engine segment
        second = [
            W(word=" more%d" % n, start=25.0 + n * 0.3, end=25.0 + n * 0.3 + 0.25)
            for n in range(12)
        ]
        words = first + second
        text = "".join(w.word for w in words).strip()
        cues = split_caption_segment(0.0, 30.0, text, 42, max_lines=1, words=words)
        assert len(cues) > 1
        assert " ".join(c[2] for c in cues) == text
        # No cue is on screen during the pause, and the cue holding the first
        # post-pause word starts when it's spoken.
        for t0, t1, cue_text in cues:
            assert not (t0 < 20.0 and t1 > 10.0)
            if cue_text.startswith("more0"):
                assert t0 == 25.0
        for prev, nxt in zip(cues, cues[1:]):
            assert prev[1] <= nxt[0]

    def test_word_timings_hold_never_exceeds_segment_end(self):
        from types import SimpleNamespace as W

        from py_captions_for_channels.embed_captions import split_caption_segment

        words = [W(word=" Hi.", start=1.0, end=1.2)]
        assert split_caption_segment(0.0, 1.5, "Hi.", 42, words=words) == [
            (1.0, 1.5, "Hi.")
        ]


class TestParakeetWords:
    def test_tokens_to_segments_attaches_word_timings(self):
        from py_captions_for_channels.parakeet_transcribe import (
            _Token,
            _tokens_to_segments,
        )

        tokens = [
            _Token(t0_cs=100, t1_cs=130, word_start=True, text="▁Wel"),
            _Token(t0_cs=130, t1_cs=150, word_start=False, text="come"),
            _Token(t0_cs=160, t1_cs=190, word_start=True, text="▁back."),
        ]
        (seg,) = _tokens_to_segments(tokens)
        assert seg.text == "Welcome back."
        assert [(w.word, w.start, w.end) for w in seg.words] == [
            (" Welcome", 1.0, 1.5),
            (" back.", 1.6, 1.9),
        ]


class TestAudioGapCorrection:
    def _detect(self, ffprobe_csv):
        from unittest.mock import MagicMock

        from py_captions_for_channels.embed_captions import detect_audio_pts_gaps

        result = MagicMock(returncode=0, stdout=ffprobe_csv, stderr="")
        with patch(
            "py_captions_for_channels.embed_captions.subprocess.run",
            return_value=result,
        ):
            return detect_audio_pts_gaps("x.ts", MagicMock())

    def test_small_capture_drops_are_counted(self):
        # 21.333ms AAC frames with a ~10ms drop after every 100th packet, the
        # pattern Chrome Capture recordings show (each far below 0.5s).
        frame = 1024 / 48000
        lines, pts = [], 0.0
        for n in range(1000):
            lines.append(f"{pts:.6f},{pts:.6f},{frame:.6f}")
            pts += frame + (0.010 if n % 100 == 99 else 0.0)
        gaps = self._detect("\n".join(lines))
        assert len(gaps) == 9
        assert abs(sum(g for _, g in gaps) - 0.090) < 0.001

    def test_timestamp_rounding_jitter_is_not_a_gap(self):
        frame = 1024 / 48000
        lines = []
        for n in range(200):
            jitter = 0.0001 if n % 2 else -0.0001
            pts = n * frame + jitter
            lines.append(f"{pts:.6f},{pts:.6f},{frame:.6f}")
        assert self._detect("\n".join(lines)) == []

    def test_correction_accumulates_across_gaps(self, tmp_path):
        from unittest.mock import MagicMock

        from py_captions_for_channels.embed_captions import (
            correct_srt_for_audio_gaps,
        )

        srt = tmp_path / "x.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nA\n\n"
            "2\n00:00:20,000 --> 00:00:21,000\nB\n\n"
            "3\n00:01:00,000 --> 00:01:01,000\nC\n\n"
        )
        # 0.5s missing at 10s, 1.0s missing at 30s (real time)
        correct_srt_for_audio_gaps(str(srt), [(10.0, 0.5), (30.0, 1.0)], MagicMock())
        text = srt.read_text()
        assert "00:00:01,000 --> 00:00:02,000" in text
        assert "00:00:20,500 --> 00:00:21,500" in text
        assert "00:01:01,500 --> 00:01:02,500" in text
