"""Tests for stream_detector — language-aware audio/subtitle selection."""

import pytest

from py_captions_for_channels.stream_detector import (
    AudioStream,
    SubtitleStream,
    StreamSelection,
    select_audio_stream,
    select_subtitle_stream,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def english_audio():
    return AudioStream(
        index=0,
        codec="ac3",
        channels=6,
        language="eng",
        title="English 5.1",
        channel_layout="5.1(side)",
    )


@pytest.fixture
def spanish_audio():
    return AudioStream(
        index=1,
        codec="aac",
        channels=2,
        language="spa",
        title="Spanish Stereo",
        channel_layout="stereo",
    )


@pytest.fixture
def undetermined_audio():
    return AudioStream(
        index=2,
        codec="mp2",
        channels=2,
        language=None,
        title=None,
        channel_layout="stereo",
    )


@pytest.fixture
def english_subtitle():
    return SubtitleStream(index=3, codec="mov_text", language="eng", title="English CC")


@pytest.fixture
def spanish_subtitle():
    return SubtitleStream(
        index=4, codec="dvb_subtitle", language="spa", title="Spanish"
    )


# ---------------------------------------------------------------------------
# AudioStream / SubtitleStream repr
# ---------------------------------------------------------------------------


class TestStreamRepr:
    def test_audio_stream_repr(self, english_audio):
        r = repr(english_audio)
        assert "ac3" in r
        assert "6ch" in r
        assert "eng" in r

    def test_audio_stream_no_language(self, undetermined_audio):
        r = repr(undetermined_audio)
        assert "und" in r

    def test_subtitle_stream_repr(self, english_subtitle):
        r = repr(english_subtitle)
        assert "mov_text" in r
        assert "eng" in r


# ---------------------------------------------------------------------------
# select_audio_stream
# ---------------------------------------------------------------------------


class TestSelectAudioStream:
    def test_exact_match(self, english_audio, spanish_audio):
        stream, reason = select_audio_stream([english_audio, spanish_audio], "eng")
        assert stream.index == 0
        assert "Matched" in reason

    def test_partial_match_2letter(self, spanish_audio):
        """Language code 'es' should match 'spa' via fallback or partial."""
        stream, reason = select_audio_stream([spanish_audio], "es")
        assert stream.index == 1
        assert "es" in reason.lower() or "spa" in reason.lower()

    def test_fallback_first(self, spanish_audio, undetermined_audio):
        stream, reason = select_audio_stream(
            [spanish_audio, undetermined_audio], "fra", fallback="first"
        )
        assert stream.index == 1  # First in list
        assert "not found" in reason.lower()

    def test_fallback_skip(self, spanish_audio):
        stream, reason = select_audio_stream([spanish_audio], "fra", fallback="skip")
        assert stream is None
        assert "skip" in reason.lower()

    def test_no_streams(self):
        stream, reason = select_audio_stream([], "eng")
        assert stream is None
        assert "No audio" in reason


# ---------------------------------------------------------------------------
# select_subtitle_stream
# ---------------------------------------------------------------------------


class TestSelectSubtitleStream:
    def test_exact_match(self, english_subtitle, spanish_subtitle):
        stream, reason = select_subtitle_stream(
            [english_subtitle, spanish_subtitle], "eng"
        )
        assert stream.index == 3
        assert "Matched" in reason

    def test_none_language_disables(self, english_subtitle):
        stream, reason = select_subtitle_stream([english_subtitle], None)
        assert stream is None
        assert "disabled" in reason.lower()

    def test_none_string_disables(self, english_subtitle):
        stream, reason = select_subtitle_stream([english_subtitle], "none")
        assert stream is None
        assert "disabled" in reason.lower()

    def test_fallback_first(self, spanish_subtitle):
        stream, reason = select_subtitle_stream(
            [spanish_subtitle], "fra", fallback="first"
        )
        assert stream.index == 4
        assert "not found" in reason.lower()

    def test_fallback_skip(self, spanish_subtitle):
        stream, reason = select_subtitle_stream(
            [spanish_subtitle], "fra", fallback="skip"
        )
        assert stream is None

    def test_no_streams(self):
        stream, reason = select_subtitle_stream([], "eng")
        assert stream is None
        assert "No subtitle" in reason


# ---------------------------------------------------------------------------
# StreamSelection repr
# ---------------------------------------------------------------------------


class TestStreamSelectionRepr:
    def test_with_subtitle(self, english_audio, english_subtitle):
        sel = StreamSelection(
            audio_index=0,
            audio_stream=english_audio,
            subtitle_index=3,
            subtitle_stream=english_subtitle,
        )
        r = repr(sel)
        assert "audio=0" in r
        assert "sub=3" in r

    def test_without_subtitle(self, english_audio):
        sel = StreamSelection(
            audio_index=0,
            audio_stream=english_audio,
            subtitle_index=None,
            subtitle_stream=None,
        )
        r = repr(sel)
        assert "no subtitles" in r
