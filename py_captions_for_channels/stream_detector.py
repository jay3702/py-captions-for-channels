"""
Stream detection and language-aware filtering for audio/subtitle tracks.

This module provides functions to:
- Probe all audio and subtitle streams in a video file
- Extract language metadata from streams
- Select appropriate streams based on language preferences
- Support fallback strategies when preferred language is not available
"""

import json
import subprocess
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class AudioStream:
    """Represents an audio stream with metadata."""

    index: int  # Stream index in file
    codec: str  # Audio codec (e.g., "ac3", "aac", "mp2")
    channels: int  # Number of audio channels (e.g., 2, 6 for 5.1)
    language: Optional[str]  # ISO 639-2/3 language code (e.g., "eng", "spa")
    title: Optional[str]  # Stream title/description
    channel_layout: Optional[str]  # e.g., "5.1(side)", "stereo"

    def __repr__(self):
        lang = self.language or "und"
        ch = f"{self.channels}ch"
        return f"<AudioStream #{self.index}: {self.codec} {ch} [{lang}]>"


@dataclass
class SubtitleStream:
    """Represents a subtitle stream with metadata."""

    index: int  # Stream index in file
    codec: str  # Subtitle codec (e.g., "dvb_subtitle", "mov_text")
    language: Optional[str]  # ISO 639-2/3 language code
    title: Optional[str]  # Stream title/description

    def __repr__(self):
        lang = self.language or "und"
        return f"<SubtitleStream #{self.index}: {self.codec} [{lang}]>"


@dataclass
class StreamSelection:
    """Selected streams for processing."""

    audio_index: int  # Selected audio stream index
    audio_stream: AudioStream
    subtitle_index: Optional[int]  # Selected subtitle stream index (or None)
    subtitle_stream: Optional[SubtitleStream]

    def __repr__(self):
        sub_info = (
            f"sub={self.subtitle_index}"
            if self.subtitle_index is not None
            else "no subtitles"
        )
        return f"<StreamSelection audio={self.audio_index} {sub_info}>"


def probe_streams(video_path: str) -> Dict[str, List]:
    """
    Use ffprobe to detect all audio and subtitle streams with language tags.

    Args:
        video_path: Path to video file

    Returns:
        Dictionary with keys "audio_streams" and "subtitle_streams",
        each containing lists of stream dictionaries with metadata

    Raises:
        subprocess.CalledProcessError: If ffprobe fails
        ValueError: If ffprobe output cannot be parsed
    """
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        video_path,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=30
        )

        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        audio_streams = []
        subtitle_streams = []

        for stream in streams:
            codec_type = stream.get("codec_type")

            if codec_type == "audio":
                # Extract audio stream metadata
                index = stream.get("index")
                codec = stream.get("codec_name", "unknown")
                channels = stream.get("channels", 0)
                channel_layout = stream.get("channel_layout")

                # Get language from tags (language, TAG:language)
                tags = stream.get("tags", {})
                language = tags.get("language", tags.get("LANGUAGE"))
                title = tags.get("title", tags.get("TITLE"))

                audio_streams.append(
                    AudioStream(
                        index=index,
                        codec=codec,
                        channels=channels,
                        language=language,
                        title=title,
                        channel_layout=channel_layout,
                    )
                )

            elif codec_type == "subtitle":
                # Extract subtitle stream metadata
                index = stream.get("index")
                codec = stream.get("codec_name", "unknown")

                tags = stream.get("tags", {})
                language = tags.get("language", tags.get("LANGUAGE"))
                title = tags.get("title", tags.get("TITLE"))

                subtitle_streams.append(
                    SubtitleStream(
                        index=index, codec=codec, language=language, title=title
                    )
                )

        return {"audio_streams": audio_streams, "subtitle_streams": subtitle_streams}

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed for {video_path}: {e.stderr}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse ffprobe output for {video_path}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffprobe timed out for {video_path}") from e


def select_audio_stream(
    audio_streams: List[AudioStream], preferred_language: str, fallback: str = "first"
) -> Tuple[Optional[AudioStream], str]:
    """
    Select the best audio stream based on language preference.

    Args:
        audio_streams: List of available audio streams
        preferred_language: Preferred language code (e.g., "eng", "spa")
        fallback: Fallback strategy if preferred language not found:
            - "first": Use first available stream
            - "skip": Return None (skip processing)
            - "all": Not applicable for audio (treated as "first")

    Returns:
        Tuple of (selected_stream, reason_message)
        stream is None if no suitable stream found
    """
    if not audio_streams:
        return None, "No audio streams found"

    # Normalize language code (handle both 2-letter and 3-letter codes)
    preferred_norm = preferred_language.lower()[:3]

    # Try exact match first
    for stream in audio_streams:
        if stream.language:
            stream_lang = stream.language.lower()[:3]
            if stream_lang == preferred_norm:
                return stream, f"Matched language '{stream.language}'"

    # Try partial match (eng matches en, spa matches es, etc.)
    preferred_2 = preferred_norm[:2]
    for stream in audio_streams:
        if stream.language:
            stream_lang = stream.language.lower()[:2]
            if stream_lang == preferred_2:
                return stream, f"Partial match language '{stream.language}'"

    # No match - apply fallback strategy
    if fallback == "skip":
        return None, f"Language '{preferred_language}' not found (fallback=skip)"

    # Default: use first stream
    first_stream = audio_streams[0]
    lang_desc = first_stream.language or "undefined"
    return (
        first_stream,
        f"Language '{preferred_language}' not found, using first stream ({lang_desc})",
    )


def select_subtitle_stream(
    subtitle_streams: List[SubtitleStream],
    preferred_language: Optional[str],
    fallback: str = "first",
) -> Tuple[Optional[SubtitleStream], str]:
    """
    Select the best subtitle stream based on language preference.

    Args:
        subtitle_streams: List of available subtitle streams
        preferred_language: Preferred language code, or None to skip subtitles
        fallback: Fallback strategy if preferred language not found

    Returns:
        Tuple of (selected_stream, reason_message)
        stream is None if no subtitles desired or found
    """
    if not subtitle_streams:
        return None, "No subtitle streams available"

    # None means skip subtitles entirely
    if preferred_language is None or preferred_language.lower() == "none":
        return None, "Subtitles disabled by configuration"

    # Normalize language code
    preferred_norm = preferred_language.lower()[:3]

    # Try exact match
    for stream in subtitle_streams:
        if stream.language:
            stream_lang = stream.language.lower()[:3]
            if stream_lang == preferred_norm:
                return stream, f"Matched subtitle language '{stream.language}'"

    # Try partial match
    preferred_2 = preferred_norm[:2]
    for stream in subtitle_streams:
        if stream.language:
            stream_lang = stream.language.lower()[:2]
            if stream_lang == preferred_2:
                return stream, f"Partial match subtitle language '{stream.language}'"

    # No match - apply fallback
    if fallback == "skip":
        return (
            None,
            f"Subtitle language '{preferred_language}' not found (fallback=skip)",
        )

    # Default: use first stream
    first_stream = subtitle_streams[0]
    lang_desc = first_stream.language or "undefined"
    return (
        first_stream,
        f"Subtitle language '{preferred_language}' not found, "
        f"using first ({lang_desc})",
    )


def select_streams(
    video_path: str,
    audio_language: str = "eng",
    subtitle_language: Optional[str] = None,
    fallback: str = "first",
) -> StreamSelection:
    """
    High-level function to probe and select appropriate streams.

    Args:
        video_path: Path to video file
        audio_language: Preferred audio language (default: "eng")
        subtitle_language: Preferred subtitle language, or None to skip
        fallback: Fallback strategy when language not found

    Returns:
        StreamSelection with chosen audio and subtitle streams

    Raises:
        RuntimeError: If no suitable audio stream can be selected
    """
    # Probe all streams
    streams = probe_streams(video_path)
    audio_streams = streams["audio_streams"]
    subtitle_streams = streams["subtitle_streams"]

    # Select audio stream (required)
    audio_stream, audio_reason = select_audio_stream(
        audio_streams, audio_language, fallback
    )

    if audio_stream is None:
        raise RuntimeError(f"Cannot process {video_path}: {audio_reason}")

    # Select subtitle stream (optional)
    subtitle_stream, subtitle_reason = select_subtitle_stream(
        subtitle_streams, subtitle_language, fallback
    )

    return StreamSelection(
        audio_index=audio_stream.index,
        audio_stream=audio_stream,
        subtitle_index=subtitle_stream.index if subtitle_stream else None,
        subtitle_stream=subtitle_stream,
    )


def extract_audio_for_transcription(
    video_path: str, audio_stream_index: int, output_path: str, log
) -> bool:
    """
    Extract specific audio stream to WAV for Whisper transcription.

    Args:
        video_path: Source video file
        audio_stream_index: Index of audio stream to extract
        output_path: Output WAV file path
        log: Logger instance

    Returns:
        True if extraction successful, False otherwise
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-map",
        f"0:a:{audio_stream_index}",  # Select specific audio stream
        "-vn",  # No video
        "-acodec",
        "pcm_s16le",  # PCM audio for Whisper
        "-ar",
        "16000",  # 16kHz sample rate (Whisper standard)
        "-ac",
        "1",  # Mono
        output_path,
    ]

    log.info(f"Extracting audio stream {audio_stream_index}: {' '.join(cmd)}")

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,  # 5 minute timeout
        )

        log.info(f"Audio extracted successfully to {output_path}")
        return True

    except subprocess.CalledProcessError as e:
        log.error(f"Audio extraction failed: {e.stderr}")
        return False
    except subprocess.TimeoutExpired:
        log.error(f"Audio extraction timed out for {video_path}")
        return False


if __name__ == "__main__":
    """Test/demo the stream detector."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python stream_detector.py <video_file> [language]")
        sys.exit(1)

    video_path = sys.argv[1]
    preferred_lang = sys.argv[2] if len(sys.argv) > 2 else "eng"

    print("\n=== Stream Detection Demo ===")
    print(f"File: {video_path}")
    print(f"Preferred language: {preferred_lang}\n")

    # Probe all streams
    try:
        streams = probe_streams(video_path)

        print(f"Audio Streams ({len(streams['audio_streams'])}):")
        for stream in streams["audio_streams"]:
            print(f"  {stream}")

        print(f"\nSubtitle Streams ({len(streams['subtitle_streams'])}):")
        for stream in streams["subtitle_streams"]:
            print(f"  {stream}")

        # Select streams
        print(f"\n=== Stream Selection (lang={preferred_lang}) ===")
        selection = select_streams(video_path, preferred_lang, preferred_lang)
        print(f"Selected: {selection}")
        print(f"  Audio: {selection.audio_stream}")
        print(f"  Subtitle: {selection.subtitle_stream}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
