"""Tests for subtitle track detection and naming."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from py_captions_for_channels.embed_captions import (
    SUBTITLE_TRACK_NAME,
    detect_subtitle_streams,
    has_our_subtitles,
)


def test_detect_subtitle_streams_with_our_track():
    """Test detection of our unique subtitle track."""
    log = MagicMock()

    # Mock ffprobe output with our subtitle track
    mock_output = json.dumps(
        {
            "streams": [
                {
                    "index": 3,
                    "codec_name": "mov_text",
                    "tags": {
                        "title": SUBTITLE_TRACK_NAME,
                        "handler_name": SUBTITLE_TRACK_NAME,
                    },
                }
            ]
        }
    )

    with patch("subprocess.check_output", return_value=mock_output):
        streams = detect_subtitle_streams("/fake/path.mp4", log)

    assert len(streams) == 1
    assert streams[0]["codec_name"] == "mov_text"
    assert streams[0]["tags"]["title"] == SUBTITLE_TRACK_NAME


def test_detect_subtitle_streams_no_subs():
    """Test detection when no subtitle streams exist."""
    log = MagicMock()

    # Mock ffprobe output with no streams
    mock_output = json.dumps({"streams": []})

    with patch("subprocess.check_output", return_value=mock_output):
        streams = detect_subtitle_streams("/fake/path.mp4", log)

    assert len(streams) == 0


def test_detect_subtitle_streams_different_track():
    """Test detection of subtitle track that's not ours."""
    log = MagicMock()

    # Mock ffprobe output with different subtitle track
    mock_output = json.dumps(
        {
            "streams": [
                {
                    "index": 2,
                    "codec_name": "subrip",
                    "tags": {
                        "title": "Broadcast Captions",
                        "handler_name": "SubtitleHandler",
                    },
                }
            ]
        }
    )

    with patch("subprocess.check_output", return_value=mock_output):
        streams = detect_subtitle_streams("/fake/path.mp4", log)

    assert len(streams) == 1
    assert streams[0]["tags"]["title"] == "Broadcast Captions"


def test_has_our_subtitles_true():
    """Test that has_our_subtitles returns True when our track exists."""
    log = MagicMock()

    mock_output = json.dumps(
        {
            "streams": [
                {"codec_name": "mov_text", "tags": {"title": SUBTITLE_TRACK_NAME}}
            ]
        }
    )

    with patch("subprocess.check_output", return_value=mock_output):
        result = has_our_subtitles("/fake/path.mp4", log)

    assert result is True


def test_has_our_subtitles_false():
    """Test that has_our_subtitles returns False when our track doesn't exist."""
    log = MagicMock()

    mock_output = json.dumps(
        {"streams": [{"codec_name": "subrip", "tags": {"title": "Different Track"}}]}
    )

    with patch("subprocess.check_output", return_value=mock_output):
        result = has_our_subtitles("/fake/path.mp4", log)

    assert result is False


def test_has_our_subtitles_no_streams():
    """Test that has_our_subtitles returns False when no subtitle streams exist."""
    log = MagicMock()

    mock_output = json.dumps({"streams": []})

    with patch("subprocess.check_output", return_value=mock_output):
        result = has_our_subtitles("/fake/path.mp4", log)

    assert result is False


def test_detect_subtitle_streams_ffprobe_error():
    """Test graceful handling of ffprobe errors."""
    log = MagicMock()

    with patch(
        "subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "ffprobe"),
    ):
        streams = detect_subtitle_streams("/fake/path.mp4", log)

    assert streams == []
    log.warning.assert_called_once()


def test_subtitle_constant_value():
    """Test that our subtitle track name is unique and identifiable."""
    assert SUBTITLE_TRACK_NAME == "py-captions-for-channels"
    assert len(SUBTITLE_TRACK_NAME) > 5  # Long enough to be unique
    assert "-" in SUBTITLE_TRACK_NAME  # Contains our naming convention
