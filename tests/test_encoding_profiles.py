"""Tests for encoding profile detection and Whisper parameter optimization."""

from py_captions_for_channels.encoding_profiles import (
    EncodingSignature,
    match_profile,
    get_whisper_parameters,
)
from py_captions_for_channels.embed_captions import extract_channel_number


class TestChannelNumberExtraction:
    """Test channel number extraction from file paths."""

    def test_ota_channel_in_directory(self):
        """Test OTA channel (X.Y format) in directory name."""
        path = "/recordings/TV/4.1 KRON/News/news-2026-01-18.mpg"
        assert extract_channel_number(path) == "4.1"

    def test_ota_channel_with_dash(self):
        """Test OTA channel with dash separator."""
        path = "/recordings/4.1-KRON/Recording.mpg"
        assert extract_channel_number(path) == "4.1"

    def test_tve_channel_in_directory(self):
        """Test TV Everywhere 4+ digit channel."""
        path = "/recordings/TV/6030 CNN/CNN News/recording.mpg"
        assert extract_channel_number(path) == "6030"

    def test_tve_channel_with_dash(self):
        """Test TVE channel with dash separator."""
        path = "/recordings/9043-MSNBC/show.mpg"
        assert extract_channel_number(path) == "9043"

    def test_channel_in_filename(self):
        """Test channel in filename itself."""
        path = "/recordings/Show_4.1_2026.mpg"
        assert extract_channel_number(path) == "4.1"

    def test_no_channel_found(self):
        """Test when no channel pattern is found."""
        path = "/recordings/TV/SomeShow/recording.mpg"
        assert extract_channel_number(path) is None

    def test_windows_path(self):
        """Test with Windows-style path."""
        path = r"C:\recordings\TV\4.1 KRON\show.mpg"
        assert extract_channel_number(path) == "4.1"


class TestProfileMatching:
    """Test encoding profile matching logic."""

    def test_ota_hd_60fps_5_1_match(self):
        """Test OTA HD 60fps with 5.1 audio matches correct profile."""
        sig = EncodingSignature(
            codec="h264",
            profile="Main",
            width=1280,
            height=720,
            fps=59.94,
            video_bitrate=2000,
            audio_codec="aac",
            audio_channels=6,
            audio_bitrate=500,
            channel_number="4.1",
        )
        profile = match_profile(sig)
        assert profile == "ota_hd_60fps_5.1"

    def test_ota_hd_30fps_stereo_match(self):
        """Test OTA HD 30fps with stereo audio."""
        sig = EncodingSignature(
            codec="h264",
            profile="Main",
            width=1280,
            height=720,
            fps=29.97,
            video_bitrate=2000,
            audio_codec="aac",
            audio_channels=2,
            audio_bitrate=192,
            channel_number="11.3",
        )
        profile = match_profile(sig)
        assert profile == "ota_hd_30fps_stereo"

    def test_tve_hd_30fps_stereo_match(self):
        """Test TV Everywhere HD 30fps with stereo."""
        sig = EncodingSignature(
            codec="h264",
            profile="Main",
            width=1280,
            height=720,
            fps=29.97,
            video_bitrate=2000,
            audio_codec="aac",
            audio_channels=2,
            audio_bitrate=170,
            channel_number="6030",
        )
        profile = match_profile(sig)
        assert profile == "tve_hd_30fps_stereo"

    def test_tve_hd_60fps_stereo_match(self):
        """Test TV Everywhere HD 60fps with stereo."""
        sig = EncodingSignature(
            codec="h264",
            profile="Main",
            width=1280,
            height=720,
            fps=59.94,
            video_bitrate=2000,
            audio_codec="aac",
            audio_channels=2,
            audio_bitrate=192,
            channel_number="9043",
        )
        profile = match_profile(sig)
        assert profile == "tve_hd_60fps_stereo"

    def test_sd_content_match(self):
        """Test SD content detection."""
        sig = EncodingSignature(
            codec="mpeg2video",
            profile="Main",
            width=720,
            height=480,
            fps=29.97,
            video_bitrate=3000,
            audio_codec="ac3",
            audio_channels=2,
            audio_bitrate=192,
            channel_number="2.1",
        )
        profile = match_profile(sig)
        assert profile == "sd_content"

    def test_unknown_channel_defaults_to_tve(self):
        """Test unknown channel number defaults to TVE profile."""
        sig = EncodingSignature(
            codec="h264",
            profile="Main",
            width=1280,
            height=720,
            fps=29.97,
            video_bitrate=2000,
            audio_codec="aac",
            audio_channels=2,
            audio_bitrate=170,
            channel_number=None,
        )
        profile = match_profile(sig)
        assert profile == "tve_hd_30fps_stereo"  # Default


class TestWhisperParameters:
    """Test Whisper parameter generation."""

    def test_automatic_mode_with_channel(self):
        """Test automatic parameter generation with known channel."""
        # This would normally call ffprobe, so we'll just verify the function exists
        # and returns a dict with expected keys
        params = get_whisper_parameters("dummy.mpg", "4.1")
        assert isinstance(params, dict)
        assert "language" in params
        assert "beam_size" in params
        assert "vad_filter" in params
        assert "vad_parameters" in params

    def test_fallback_to_standard_on_error(self):
        """Test fallback to standard params when detection fails."""
        # Non-existent file should trigger fallback
        params = get_whisper_parameters("/nonexistent/file.mpg", None)
        assert params["beam_size"] == 5
        assert params["vad_parameters"]["min_silence_duration_ms"] == 500
        assert params["language"] == "en"
