"""
Cloud transcription via Groq's hosted Whisper API.

Used when WHISPER_DEVICE=groq. Handles the parts local transcription doesn't
need: chunking audio to stay under Groq's per-tier file-size limit, checking
local usage records against Groq's rate limits before spending a request,
and recording usage afterward so later jobs know how much quota is left.

Groq doesn't expose usage via API, so quota tracking here is necessarily an
estimate based on our own request history (GroqUsage table) — it can drift
from Groq's real counters if other tools share the same API key, but it's
the only signal available and errs conservative (a live 429 still triggers
the same fallback as a failed pre-flight check).

Every failure mode here — no API key, quota exceeded, network error, API
error — results in returning None rather than raising, so the caller can
fall back to local transcription uniformly. A job is never left uncaptioned
just because Groq didn't work.
"""

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from py_captions_for_channels.logging.structured_logger import get_logger

log = get_logger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CHUNK_TARGET_SECONDS = 20 * 60
GROQ_MAX_RETRIES = 3


@dataclass
class GroqSegment:
    """Mirrors the .start/.end/.text shape faster-whisper segments expose."""

    start: float
    end: float
    text: str


def _get_tier_limits(tier: str) -> dict:
    from py_captions_for_channels import config

    if tier == "dev":
        return {
            "max_file_mb": config.GROQ_DEV_MAX_FILE_MB,
            "rpm": config.GROQ_DEV_RPM,
            "rpd": config.GROQ_DEV_RPD,
            "ash": config.GROQ_DEV_ASH,
            "asd": config.GROQ_DEV_ASD,
        }
    return {
        "max_file_mb": config.GROQ_FREE_MAX_FILE_MB,
        "rpm": config.GROQ_FREE_RPM,
        "rpd": config.GROQ_FREE_RPD,
        "ash": config.GROQ_FREE_ASH,
        "asd": config.GROQ_FREE_ASD,
    }


def _check_quota(num_requests: int, total_audio_seconds: float, limits: dict) -> Optional[str]:
    """Pre-flight check of this job's request/audio budget against recent usage.

    Checked at job granularity (not per-chunk) to avoid ever splitting a
    single recording's transcript between Groq and local mid-job. Returns
    None if the job fits, otherwise a human-readable reason it doesn't.
    Limit dimensions set to 0 are treated as unenforced (see GROQ_TIER note
    in config.py — this is how the "dev" tier's unknown numbers stay inert).
    """
    from py_captions_for_channels.database import SessionLocal
    from py_captions_for_channels.models import GroqUsage
    from sqlalchemy import func

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        if limits["rpm"] > 0:
            since = now - timedelta(minutes=1)
            recent_requests = (
                db.query(func.count(GroqUsage.id))
                .filter(GroqUsage.created_at >= since)
                .scalar()
                or 0
            )
            if recent_requests + num_requests > limits["rpm"]:
                return (
                    f"would exceed free-tier RPM limit "
                    f"({recent_requests} used + {num_requests} needed > {limits['rpm']})"
                )

        if limits["rpd"] > 0:
            since = now - timedelta(days=1)
            today_requests = (
                db.query(func.count(GroqUsage.id))
                .filter(GroqUsage.created_at >= since)
                .scalar()
                or 0
            )
            if today_requests + num_requests > limits["rpd"]:
                return (
                    f"would exceed RPD limit "
                    f"({today_requests} used + {num_requests} needed > {limits['rpd']})"
                )

        if limits["ash"] > 0:
            since = now - timedelta(hours=1)
            hour_audio = (
                db.query(func.sum(GroqUsage.audio_seconds))
                .filter(GroqUsage.created_at >= since)
                .scalar()
                or 0.0
            )
            if hour_audio + total_audio_seconds > limits["ash"]:
                return (
                    f"would exceed ASH (audio-seconds/hour) limit "
                    f"({hour_audio:.0f}s used + {total_audio_seconds:.0f}s needed "
                    f"> {limits['ash']}s)"
                )

        if limits["asd"] > 0:
            since = now - timedelta(days=1)
            day_audio = (
                db.query(func.sum(GroqUsage.audio_seconds))
                .filter(GroqUsage.created_at >= since)
                .scalar()
                or 0.0
            )
            if day_audio + total_audio_seconds > limits["asd"]:
                return (
                    f"would exceed ASD (audio-seconds/day) limit "
                    f"({day_audio:.0f}s used + {total_audio_seconds:.0f}s needed "
                    f"> {limits['asd']}s)"
                )

        return None
    finally:
        db.close()


def _record_usage(audio_seconds: float, model: str) -> None:
    from py_captions_for_channels.database import SessionLocal
    from py_captions_for_channels.models import GroqUsage

    db = SessionLocal()
    try:
        db.add(GroqUsage(audio_seconds=audio_seconds, model=model))
        db.commit()
    except Exception as e:
        log.warning(f"Failed to record Groq usage: {e}")
        db.rollback()
    finally:
        db.close()


def _extract_audio(
    input_path: str, out_path: str, start: float = None, duration: float = None
) -> None:
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", input_path]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-vn", "-acodec", "flac", "-ar", "16000", "-ac", "1", out_path]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _build_chunks(
    input_path: str, work_dir: Path, total_duration: float, chunk_seconds: float
) -> List[tuple]:
    chunks = []
    start = 0.0
    idx = 0
    while start < total_duration:
        dur = min(chunk_seconds, total_duration - start)
        chunk_path = str(work_dir / f"chunk_{idx:03d}.flac")
        _extract_audio(input_path, chunk_path, start=start, duration=dur)
        chunks.append((chunk_path, start))
        start += dur
        idx += 1
    return chunks


def _transcribe_chunk(client, audio_path: str, model: str, language: Optional[str]) -> List[GroqSegment]:
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
                GroqSegment(start=seg.start, end=seg.end, text=seg.text.strip())
                for seg in resp.segments
            ]
        except Exception as e:
            last_error = e
            if attempt < GROQ_MAX_RETRIES:
                time.sleep(2**attempt)
    raise RuntimeError(f"Groq request failed after {GROQ_MAX_RETRIES} attempts") from last_error


def transcribe_via_groq(
    input_path: str, model: str, language: Optional[str]
) -> Optional[List[GroqSegment]]:
    """Attempt cloud transcription via Groq. Returns None on any failure —
    quota exceeded, no API key, network/API error — so the caller falls back
    to local transcription. Never raises.
    """
    from py_captions_for_channels import config

    if not config.GROQ_API_KEY:
        log.warning("WHISPER_DEVICE=groq but GROQ_API_KEY is not set — falling back to local")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openai package not installed — falling back to local")
        return None

    tier = config.GROQ_TIER if config.GROQ_TIER in ("free", "dev") else "free"
    limits = _get_tier_limits(tier)

    try:
        with tempfile.TemporaryDirectory(prefix="groq_transcribe_") as tmp:
            tmp_path = Path(tmp)
            full_audio = str(tmp_path / "full.flac")
            max_audio_seconds = (
                config.GROQ_MAX_AUDIO_MINUTES * 60
                if config.GROQ_MAX_AUDIO_MINUTES > 0
                else None
            )
            if max_audio_seconds:
                log.info(
                    f"Capping audio sent to Groq at the first "
                    f"{config.GROQ_MAX_AUDIO_MINUTES} minute(s) "
                    f"(GROQ_MAX_AUDIO_MINUTES)"
                )
            log.debug("Extracting audio for Groq transcription")
            _extract_audio(input_path, full_audio, duration=max_audio_seconds)

            duration_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", full_audio,
            ]
            duration = float(subprocess.check_output(duration_cmd, text=True).strip())
            size = os.path.getsize(full_audio)
            max_bytes = limits["max_file_mb"] * 1024 * 1024

            if size <= max_bytes:
                chunk_paths = [(full_audio, 0.0)]
            else:
                bytes_per_second = size / duration
                chunk_seconds = min(
                    CHUNK_TARGET_SECONDS, (max_bytes * 0.8) / bytes_per_second
                )
                chunk_paths = _build_chunks(input_path, tmp_path, duration, chunk_seconds)
                log.info(
                    f"Groq: audio exceeds {limits['max_file_mb']}MB {tier}-tier limit, "
                    f"split into {len(chunk_paths)} chunks"
                )

            reason = _check_quota(len(chunk_paths), duration, limits)
            if reason:
                log.warning(f"Groq quota check failed, falling back to local: {reason}")
                return None

            client = OpenAI(api_key=config.GROQ_API_KEY, base_url=GROQ_BASE_URL)
            all_segments: List[GroqSegment] = []
            for chunk_path, offset in chunk_paths:
                chunk_duration_cmd = [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", chunk_path,
                ]
                chunk_duration = float(
                    subprocess.check_output(chunk_duration_cmd, text=True).strip()
                )
                segments = _transcribe_chunk(client, chunk_path, model, language)
                for seg in segments:
                    seg.start += offset
                    seg.end += offset
                all_segments.extend(segments)
                _record_usage(chunk_duration, model)

            log.info(
                f"Groq transcription succeeded: {len(all_segments)} segments, "
                f"{duration / 60:.1f} min of audio, {len(chunk_paths)} request(s)"
            )
            return all_segments

    except Exception as e:
        log.warning(f"Groq transcription failed, falling back to local: {e}")
        return None
