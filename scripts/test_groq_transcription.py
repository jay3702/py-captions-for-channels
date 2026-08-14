#!/usr/bin/env python3
"""
Validate Groq's hosted Whisper API against the local faster-whisper pipeline.

Extracts a mono FLAC audio track from an input recording (chunking it if the
file would exceed Groq's size limits), transcribes it via Groq's
OpenAI-compatible endpoint, and optionally runs the same audio through the
local faster-whisper engine for a side-by-side speed/text comparison.

Note on hardware acceleration: this script only extracts audio (`-vn`), so no
video is ever decoded or encoded here — QSV/VAAPI/NVENC have nothing to do
regardless of what GPU is available, since audio codecs (flac/mp3/etc.) have
no fixed-function hardware path in ffmpeg. Hardware acceleration is relevant
to this project's separate ffmpeg *video* transcode path (TRANSCODE_FOR_FIRETV
/ GPU_ENCODER), not to audio extraction ahead of transcription.

Usage:
    export GROQ_API_KEY=...
    python scripts/test_groq_transcription.py --input /path/to/recording.mpg
    python scripts/test_groq_transcription.py --input /path/to/recording.mpg \
        --compare-local --local-model medium
"""

import argparse
import difflib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def setup_path():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_PRICE_PER_HOUR = {
    "whisper-large-v3": 0.111,
    "whisper-large-v3-turbo": 0.04,
}
# Stay comfortably under Groq's per-tier file size cap.
GROQ_SAFE_MAX_BYTES_BY_TIER = {
    "free": 20 * 1024 * 1024,  # cap is 25MB; leave margin
    "dev": 90 * 1024 * 1024,  # cap is 100MB; leave margin
}
CHUNK_TARGET_SECONDS = 20 * 60
GROQ_MAX_RETRIES = 3


def probe_duration(path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    return float(subprocess.check_output(cmd, text=True).strip())


def extract_audio(
    input_path: str, out_path: str, start: float = None, duration: float = None
) -> None:
    """Extract mono 16kHz FLAC audio. Audio-only (-vn): no hwaccel applies."""
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", input_path]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-vn", "-acodec", "flac", "-ar", "16000", "-ac", "1", out_path]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def build_chunks(
    input_path: str, work_dir: Path, total_duration: float, chunk_seconds: float
) -> list:
    """Time-slice the source into <=chunk_seconds pieces.

    Returns [(chunk_path, start_offset_seconds), ...].
    """
    chunks = []
    start = 0.0
    idx = 0
    while start < total_duration:
        dur = min(chunk_seconds, total_duration - start)
        chunk_path = str(work_dir / f"chunk_{idx:03d}.flac")
        print(f"  Extracting chunk {idx}: {start:.0f}s - {start + dur:.0f}s")
        extract_audio(input_path, chunk_path, start=start, duration=dur)
        chunks.append((chunk_path, start))
        start += dur
        idx += 1
    return chunks


def transcribe_chunk_with_groq(client, audio_path: str, model: str, language) -> list:
    """One Groq call for one audio file. Returns [{'start','end','text'}, ...]."""
    kwargs = dict(
        model=model,
        response_format="verbose_json",
        timestamp_granularities=["segment"],
    )
    if language:
        kwargs["language"] = language

    last_error = None
    for attempt in range(1, GROQ_MAX_RETRIES + 1):
        try:
            with open(audio_path, "rb") as f:
                resp = client.audio.transcriptions.create(file=f, **kwargs)
            return [
                {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
                for seg in resp.segments
            ]
        except Exception as e:
            last_error = e
            wait = 2**attempt
            print(f"  Groq request failed (attempt {attempt}): {e} - retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Groq transcription failed after {GROQ_MAX_RETRIES} attempts") from last_error


def transcribe_with_groq(input_path: str, model: str, language, tier: str) -> tuple:
    """Extract audio (chunking if needed), transcribe via Groq.

    Returns (segments, wall_seconds, audio_duration_seconds).
    """
    from openai import OpenAI

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("GROQ_API_KEY is not set in the environment.")
    client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)

    safe_max_bytes = GROQ_SAFE_MAX_BYTES_BY_TIER[tier]
    duration = probe_duration(input_path)

    with tempfile.TemporaryDirectory(prefix="groq_test_") as tmp:
        tmp_path = Path(tmp)
        full_audio = str(tmp_path / "full.flac")
        print(f"Extracting audio ({duration / 60:.1f} min)...")
        extract_audio(input_path, full_audio)
        size = os.path.getsize(full_audio)
        print(f"  Extracted audio size: {size / 1024 / 1024:.1f} MB")

        t0 = time.time()
        all_segments = []
        if size <= safe_max_bytes:
            print("Sending as a single request...")
            all_segments = transcribe_chunk_with_groq(client, full_audio, model, language)
        else:
            print(
                f"Audio exceeds {safe_max_bytes / 1024 / 1024:.0f}MB safe limit "
                f"({tier} tier) - chunking..."
            )
            bytes_per_second = size / duration
            # Leave 20% headroom under the byte budget for FLAC's variable rate.
            chunk_seconds = min(
                CHUNK_TARGET_SECONDS, (safe_max_bytes * 0.8) / bytes_per_second
            )
            os.remove(full_audio)
            chunks = build_chunks(input_path, tmp_path, duration, chunk_seconds)
            for i, (chunk_path, offset) in enumerate(chunks):
                print(f"Transcribing chunk {i + 1}/{len(chunks)}...")
                chunk_segments = transcribe_chunk_with_groq(
                    client, chunk_path, model, language
                )
                for seg in chunk_segments:
                    seg["start"] += offset
                    seg["end"] += offset
                all_segments.extend(chunk_segments)
        elapsed = time.time() - t0

    return all_segments, elapsed, duration


def transcribe_with_local_whisper(input_path: str, model_size: str) -> tuple:
    """Run the same audio through local faster-whisper. Returns (segments, wall_seconds)."""
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
        device = "cuda"
    except Exception:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        device = "cpu"
    print(f"Loaded local faster-whisper '{model_size}' on {device}")

    t0 = time.time()
    segments_gen, info = model.transcribe(
        input_path, beam_size=5, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    segments = [
        {"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments_gen
    ]
    elapsed = time.time() - t0
    print(f"  Detected language: {info.language} (p={info.language_probability:.2f})")
    return segments, elapsed


def format_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments: list, out_path: str) -> None:
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(f"{i}\n")
        lines.append(
            f"{format_srt_timestamp(seg['start'])} --> {format_srt_timestamp(seg['end'])}\n"
        )
        lines.append(f"{seg['text']}\n\n")
    Path(out_path).write_text("".join(lines), encoding="utf-8")


def main():
    setup_path()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to a recording")
    parser.add_argument(
        "--model",
        default="whisper-large-v3-turbo",
        choices=list(GROQ_PRICE_PER_HOUR),
        help="Groq model to test",
    )
    parser.add_argument("--language", default=None, help="ISO language code, e.g. en")
    parser.add_argument(
        "--tier",
        default="free",
        choices=list(GROQ_SAFE_MAX_BYTES_BY_TIER),
        help="Groq account tier, controls the file-size chunking threshold",
    )
    parser.add_argument(
        "--compare-local", action="store_true", help="Also run local faster-whisper"
    )
    parser.add_argument("--local-model", default="medium", help="faster-whisper model size")
    args = parser.parse_args()

    input_path = args.input
    if not os.path.exists(input_path):
        raise SystemExit(f"Input not found: {input_path}")

    print("=" * 70)
    print("GROQ TRANSCRIPTION TEST")
    print("=" * 70)

    groq_segments, groq_elapsed, duration = transcribe_with_groq(
        input_path, args.model, args.language, args.tier
    )
    groq_srt = input_path + f".groq-{args.model}.srt"
    write_srt(groq_segments, groq_srt)

    cost = (duration / 3600) * GROQ_PRICE_PER_HOUR[args.model]
    print("\n--- Groq results ---")
    print(f"Audio duration:   {duration / 60:.1f} min")
    print(f"Wall time:        {groq_elapsed:.1f}s")
    print(f"Segments:         {len(groq_segments)}")
    print(f"Estimated cost:   ${cost:.4f}  (model: {args.model})")
    print(f"SRT written to:   {groq_srt}")

    if args.compare_local:
        print("\n" + "=" * 70)
        print("LOCAL FASTER-WHISPER COMPARISON")
        print("=" * 70)
        local_segments, local_elapsed = transcribe_with_local_whisper(
            input_path, args.local_model
        )
        local_srt = input_path + f".local-{args.local_model}.srt"
        write_srt(local_segments, local_srt)

        groq_text = " ".join(s["text"] for s in groq_segments)
        local_text = " ".join(s["text"] for s in local_segments)
        similarity = difflib.SequenceMatcher(None, groq_text, local_text).ratio()

        print("\n--- Comparison ---")
        print(f"Groq wall time:        {groq_elapsed:.1f}s  ({duration / max(groq_elapsed, 0.01):.1f}x real-time)")
        print(f"Local wall time:       {local_elapsed:.1f}s  ({duration / max(local_elapsed, 0.01):.1f}x real-time)")
        print(f"Groq word count:       {len(groq_text.split())}")
        print(f"Local word count:      {len(local_text.split())}")
        print(f"Rough text similarity: {similarity:.1%}  (character-level, not true WER)")
        print(f"Local SRT written to:  {local_srt}")
        print("\nInspect both .srt files by eye for real accuracy differences -")
        print("similarity ratio is only a rough sanity check, not a quality score.")


if __name__ == "__main__":
    main()
