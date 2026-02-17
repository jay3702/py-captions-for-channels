"""
Encoding profile detection and Whisper parameter optimization.

Analyzes video encoding characteristics using ffprobe and provides
optimized Whisper transcription parameters based on source type.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Optional, Dict, Any
from pathlib import Path

from py_captions_for_channels.logging.structured_logger import get_logger

LOG = get_logger(__name__)


@dataclass
class EncodingSignature:
    """Encoding characteristics extracted from ffprobe."""

    codec: str
    profile: str
    width: int
    height: int
    fps: float
    video_bitrate: int
    audio_codec: str
    audio_channels: int
    audio_bitrate: int
    channel_number: Optional[str] = None


@dataclass
class WhisperProfile:
    """Optimized Whisper and ffmpeg parameters for a specific encoding signature."""

    name: str
    description: str
    # Whisper parameters
    beam_size: int = 5
    vad_filter: bool = True
    vad_min_silence_ms: int = 500
    # ffmpeg encoding parameters
    nvenc_preset: str = "fast"  # NVENC presets: hp, fast, slow, hq
    x264_preset: str = (
        "fast"  # x264 presets: ultrafast, veryfast, faster, fast, medium, slow
    )


# Encoding profile definitions
ENCODING_PROFILES = {
    "ota_hd_60fps_5.1": WhisperProfile(
        name="OTA HD 60fps 5.1",
        description="Over-the-air broadcast, 720p60, 5.1 surround audio",
        beam_size=5,
        vad_filter=True,
        vad_min_silence_ms=700,  # Broadcast audio is cleaner, can use longer silence
        nvenc_preset="hp",  # High performance - OTA is clean, encodes fast
        x264_preset="veryfast",  # Fast CPU encoding for high quality source
    ),
    "ota_hd_30fps_stereo": WhisperProfile(
        name="OTA HD 30fps Stereo",
        description="Over-the-air broadcast, 720p30, stereo audio",
        beam_size=5,
        vad_filter=True,
        vad_min_silence_ms=600,
        nvenc_preset="fast",  # Balanced preset
        x264_preset="fast",
    ),
    "tve_hd_30fps_stereo": WhisperProfile(
        name="TV Everywhere HD Stereo",
        description="Streaming source, 720p30, stereo audio with BT.709",
        beam_size=5,
        vad_filter=True,
        vad_min_silence_ms=500,  # Standard setting
        nvenc_preset="fast",  # Standard preset (current default)
        x264_preset="fast",
    ),
    "tve_hd_60fps_stereo": WhisperProfile(
        name="TV Everywhere HD 60fps Stereo",
        description="Streaming source, 720p60, stereo audio",
        beam_size=5,
        vad_filter=True,
        vad_min_silence_ms=500,
        nvenc_preset="fast",
        x264_preset="fast",
    ),
    "sd_content": WhisperProfile(
        name="SD Content",
        description="Standard definition content (480p or lower)",
        beam_size=4,  # Lower quality video might have lower quality audio
        vad_filter=True,
        vad_min_silence_ms=400,  # More aggressive for compressed audio
        nvenc_preset="hp",  # Fast encode for low quality
        x264_preset="faster",
    ),
}


def probe_encoding_signature(
    video_path: Path, channel_number: Optional[str] = None
) -> EncodingSignature:
    """
    Extract encoding signature from video file using ffprobe.

    Args:
        video_path: Path to video file
        channel_number: Optional channel number for OTA vs streaming detection

    Returns:
        EncodingSignature with video/audio characteristics

    Raises:
        RuntimeError: If ffprobe fails
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(video_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5, check=True
        )

        data = json.loads(result.stdout)

        # Extract video stream info
        video_stream = next(
            (s for s in data["streams"] if s["codec_type"] == "video"), None
        )
        if not video_stream:
            raise RuntimeError("No video stream found")

        # Extract audio stream info (first audio track)
        audio_stream = next(
            (s for s in data["streams"] if s["codec_type"] == "audio"), None
        )
        if not audio_stream:
            raise RuntimeError("No audio stream found")

        # Parse frame rate
        fps_str = video_stream.get("r_frame_rate", "30000/1001")
        fps_num, fps_den = map(int, fps_str.split("/"))
        fps = fps_num / fps_den if fps_den != 0 else 30.0

        signature = EncodingSignature(
            codec=video_stream.get("codec_name", "unknown"),
            profile=video_stream.get("profile", "unknown"),
            width=video_stream.get("width", 0),
            height=video_stream.get("height", 0),
            fps=fps,
            video_bitrate=int(video_stream.get("bit_rate", 0)),
            audio_codec=audio_stream.get("codec_name", "unknown"),
            audio_channels=audio_stream.get("channels", 2),
            audio_bitrate=int(audio_stream.get("bit_rate", 0)),
            channel_number=channel_number,
        )

        LOG.info(
            f"Detected encoding: {signature.codec} "
            f"{signature.width}x{signature.height} @ {signature.fps:.2f}fps, "
            f"{signature.audio_codec} {signature.audio_channels}ch"
        )

        return signature

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffprobe timeout analyzing {video_path}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed: {e.stderr}")
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise RuntimeError(f"Failed to parse ffprobe output: {e}")


def match_profile(signature: EncodingSignature) -> WhisperProfile:
    """
    Match encoding signature to optimal Whisper profile.

    Args:
        signature: Encoding characteristics

    Returns:
        WhisperProfile with optimized parameters
    """
    # Detect OTA vs TV Everywhere by channel number pattern
    is_ota = False
    if signature.channel_number:
        # OTA channels: X.Y format (e.g., 4.1, 11.3)
        # TVE channels: high numbers (e.g., 6030, 9043)
        is_ota = bool(re.match(r"^\d+\.\d+$", signature.channel_number))

    # Match based on characteristics
    is_60fps = signature.fps >= 50  # Account for 59.94
    is_5_1_audio = signature.audio_channels >= 6
    is_stereo = signature.audio_channels == 2
    is_sd = signature.height < 720

    # Match to profile
    if is_sd:
        profile_key = "sd_content"
    elif is_ota and is_60fps and is_5_1_audio:
        profile_key = "ota_hd_60fps_5.1"
    elif is_ota and is_60fps and is_stereo:
        profile_key = (
            "ota_hd_30fps_stereo"  # Use 30fps profile even for 60fps stereo OTA
        )
    elif is_ota and is_stereo:
        profile_key = "ota_hd_30fps_stereo"
    elif not is_ota and is_60fps:
        profile_key = "tve_hd_60fps_stereo"
    else:
        # Default TV Everywhere profile
        profile_key = "tve_hd_30fps_stereo"

    profile = ENCODING_PROFILES[profile_key]

    LOG.info(
        f"Matched profile: {profile.name} - {profile.description} "
        f"(beam_size={profile.beam_size}, vad_silence={profile.vad_min_silence_ms}ms)"
    )

    return profile


def get_whisper_parameters(
    video_path: Path, channel_number: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get optimized Whisper parameters for a video file.

    Args:
        video_path: Path to video file
        channel_number: Optional channel number for source detection

    Returns:
        Dictionary of Whisper transcribe() parameters
    """
    try:
        signature = probe_encoding_signature(video_path, channel_number)
        profile = match_profile(signature)

        return {
            "language": "en",
            "beam_size": profile.beam_size,
            "vad_filter": profile.vad_filter,
            "vad_parameters": {"min_silence_duration_ms": profile.vad_min_silence_ms},
        }

    except Exception as e:
        LOG.warning(f"Failed to detect encoding profile: {e}, using defaults")
        # Return standard defaults
        return {
            "language": "en",
            "beam_size": 5,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }


def get_ffmpeg_parameters(
    video_path: Path, channel_number: Optional[str] = None
) -> Dict[str, str]:
    """
    Get optimized ffmpeg encoder parameters for a video file.

    Args:
        video_path: Path to video file
        channel_number: Optional channel number for source detection

    Returns:
        Dictionary with 'nvenc_preset' and 'x264_preset' keys
    """
    try:
        signature = probe_encoding_signature(video_path, channel_number)
        profile = match_profile(signature)

        return {
            "nvenc_preset": profile.nvenc_preset,
            "x264_preset": profile.x264_preset,
        }

    except Exception as e:
        LOG.warning(f"Failed to detect encoding profile: {e}, using defaults")
        # Return standard defaults
        return {"nvenc_preset": "fast", "x264_preset": "fast"}


def get_profile_summary() -> str:
    """Get a summary of all available encoding profiles."""
    lines = ["Available Encoding Profiles:"]
    for key, profile in ENCODING_PROFILES.items():
        lines.append(
            f"  {profile.name}: {profile.description} "
            f"(beam={profile.beam_size}, vad={profile.vad_min_silence_ms}ms)"
        )
    return "\n".join(lines)
