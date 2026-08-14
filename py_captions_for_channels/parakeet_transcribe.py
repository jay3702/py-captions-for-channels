"""
Local transcription via a whisper.cpp/ggml build of NVIDIA's Parakeet TDT.

Used when WHISPER_ENGINE=parakeet. Runs on CPU only for now — the GPU
backend (Vulkan) crashed reliably in testing (device-lost on an Intel iGPU,
out-of-VRAM on a 4GB discrete GPU regardless of clip length) and is stubbed
out here for later, once that upstream backend matures. CPU-only was fast
and reliable in testing: ~0.1x real-time on a modern desktop CPU, actually
faster than GPU-accelerated whisper.cpp Whisper in the same testing.

Two real correctness issues found during testing, both handled here:

1. The model has an architectural single-pass ceiling well under NVIDIA's
   documented ~24 minutes — confirmed empirically between 15 and 35 minutes
   of real speech, on CPU as well as GPU. Audio is always chunked to stay
   safely under it, regardless of backend.

2. parakeet-cli's own top-level "Segment N: [start -> end]" summary line
   reports an unreliable end-timestamp for long spans (observed: claiming a
   10-minute chunk's one segment ended at 75 seconds, while the segment's
   own text clearly covered the full chunk). The per-token t0/t1 timestamps
   are accurate throughout, confirmed by cross-checking the last token's t1
   against the chunk's real duration. So this module never parses the
   Segment summary line at all — it parses individual token lines and
   reconstructs both the text and the caption timing from those directly.

Like groq_transcribe.py, every failure mode here returns (None, reason)
rather than raising, so the caller falls back to local faster-whisper
transcription uniformly while still logging why. A job is never left
uncaptioned just because Parakeet didn't work — and a chunk that comes back
with suspiciously little token coverage for its length is treated as a
failure too, not a false "success".
"""

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from py_captions_for_channels.logging.structured_logger import get_logger

log = get_logger(__name__)

PARAKEET_MODEL_URL = (
    "https://huggingface.co/ggml-org/parakeet-GGUF/resolve/main/"
    "ggml-parakeet-tdt-0.6b-v3-q8_0.bin"
)
PARAKEET_MODEL_FILENAME = "ggml-parakeet-tdt-0.6b-v3-q8_0.bin"
PARAKEET_CLI_PATH = "/usr/local/bin/parakeet-cli"

# NVIDIA's docs cite ~24 minutes as the model's single-pass ceiling; testing
# found real breakage well under that. Stay well clear of both.
PARAKEET_CHUNK_SECONDS = 10 * 60

# A chunk whose last recovered token timestamp falls short of this fraction
# of the chunk's real duration is treated as a failed chunk (silent
# under-coverage), not a legitimately short transcript.
MIN_COVERAGE_FRACTION = 0.85

# Caption segmentation: split accumulated words into a new segment at
# sentence-ending punctuation once the segment has run at least this long,
# or unconditionally once it hits the max, so a stretch of dialogue with no
# punctuation doesn't grow into one giant caption card.
SEGMENT_MIN_SECONDS = 1.5
SEGMENT_MAX_SECONDS = 8.0

TOKEN_LINE = re.compile(
    r"^\s*\[\s*\d+\]\s+id=\s*\d+\s+frame=\s*\d+\s+dur_idx=\s*\d+\s+"
    r"dur_val=\s*\d+\s+p=[\d.]+\s+plog=[-\d.]+\s+"
    r't0=\s*(\d+)\s+t1=\s*(\d+)\s+word_start=(true|false)\s+"(.*)"$'
)


@dataclass
class ParakeetSegment:
    """Mirrors the .start/.end/.text shape faster-whisper segments expose."""

    start: float
    end: float
    text: str


@dataclass
class _Token:
    t0_cs: int
    t1_cs: int
    word_start: bool
    text: str


def _model_path() -> str:
    from py_captions_for_channels import config

    return os.path.join(config.DATA_DIR, "parakeet", PARAKEET_MODEL_FILENAME)


def _ensure_model() -> Optional[str]:
    """Download the GGML model to a persistent path on first use.

    Stored under DATA_DIR rather than the container's ephemeral layer
    (where faster-whisper's own cache lives) since 668MB is too much to
    silently re-download on every deploy. Returns the local path, or None
    if the download fails.
    """
    path = _model_path()
    if os.path.exists(path):
        return path

    log.info(f"Downloading Parakeet model (~640MB, one-time) to {path}")
    tmp_path = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with requests.get(PARAKEET_MODEL_URL, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                    f.write(chunk)
        os.replace(tmp_path, path)
        log.info("Parakeet model downloaded successfully")
        return path
    except Exception as e:
        log.warning(f"Failed to download Parakeet model: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return None


def _probe_duration(path: str) -> float:
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


def _parse_tokens(stdout: str) -> List[_Token]:
    tokens = []
    for line in stdout.splitlines():
        m = TOKEN_LINE.match(line)
        if not m:
            continue
        t0_cs, t1_cs, word_start, text = m.groups()
        tokens.append(
            _Token(
                t0_cs=int(t0_cs),
                t1_cs=int(t1_cs),
                word_start=(word_start == "true"),
                text=text,
            )
        )
    return tokens


def _tokens_to_segments(tokens: List[_Token]) -> List[ParakeetSegment]:
    """Reconstruct words from subword tokens, then group words into
    caption-sized segments using the tokens' own (trustworthy) timestamps.
    """
    if not tokens:
        return []

    # Reconstruct words: a word_start token begins a new word; subsequent
    # word_start=false tokens are subword continuations appended directly.
    words = []  # list of (text, t0_cs, t1_cs)
    for tok in tokens:
        piece = tok.text.replace("▁", "")  # strip SentencePiece '▁'
        if tok.word_start or not words:
            words.append([piece, tok.t0_cs, tok.t1_cs])
        else:
            words[-1][0] += piece
            words[-1][1] = min(words[-1][1], tok.t0_cs)
            words[-1][2] = tok.t1_cs
    words = [(text, t0, t1) for text, t0, t1 in words if text]

    segments = []
    buf_words: List[str] = []
    buf_start_cs = None
    buf_end_cs = None

    def flush():
        if buf_words:
            segments.append(
                ParakeetSegment(
                    start=buf_start_cs / 100.0,
                    end=buf_end_cs / 100.0,
                    text=" ".join(buf_words).strip(),
                )
            )

    for text, t0_cs, t1_cs in words:
        if buf_start_cs is None:
            buf_start_cs = t0_cs
        buf_words.append(text)
        buf_end_cs = t1_cs
        span = (buf_end_cs - buf_start_cs) / 100.0
        ends_sentence = text.rstrip().endswith((".", "!", "?"))
        if (
            ends_sentence and span >= SEGMENT_MIN_SECONDS
        ) or span >= SEGMENT_MAX_SECONDS:
            flush()
            buf_words = []
            buf_start_cs = None
    flush()

    return segments


def _transcribe_chunk(model_path: str, audio_path: str) -> List[ParakeetSegment]:
    cmd = [
        PARAKEET_CLI_PATH,
        "-m",
        model_path,
        "-f",
        audio_path,
        "-ng",
        "-ps",
        "-np",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(
            f"parakeet-cli exited {result.returncode}: {result.stderr[-500:]}"
        )

    # -ps's segment/token dump goes to stderr, not stdout (stdout carries
    # only the plain-text result). Confirmed by direct inspection — mixing
    # the two streams together (as a quick `2>&1` shell test does) hides
    # this distinction.
    tokens = _parse_tokens(result.stderr)
    if not tokens:
        chunk_duration = _probe_duration(audio_path)
        if chunk_duration > 5:
            raise RuntimeError(
                f"parakeet-cli produced no tokens for a " f"{chunk_duration:.0f}s chunk"
            )
        return []

    chunk_duration = _probe_duration(audio_path)
    last_t1 = tokens[-1].t1_cs / 100.0
    if last_t1 < chunk_duration * MIN_COVERAGE_FRACTION:
        raise RuntimeError(
            f"parakeet-cli output only covers {last_t1:.0f}s of a "
            f"{chunk_duration:.0f}s chunk (silent under-coverage)"
        )

    return _tokens_to_segments(tokens)


def transcribe_via_parakeet(
    input_path: str,
) -> Tuple[Optional[List[ParakeetSegment]], Optional[str]]:
    """Attempt local transcription via Parakeet (CPU-only for now). Returns
    (segments, None) on success, or (None, reason) on any failure — binary
    missing, model download failed, crash, silent under-coverage — so the
    caller falls back to faster-whisper while still being able to log why.
    Never raises.
    """
    from py_captions_for_channels import config

    if config.PARAKEET_DEVICE != "cpu":
        reason = (
            f"PARAKEET_DEVICE={config.PARAKEET_DEVICE} is not supported yet "
            f"(GPU backend crashed reliably in testing)"
        )
        log.warning(f"{reason} - falling back to local")
        return None, reason

    if not os.path.exists(PARAKEET_CLI_PATH):
        reason = f"parakeet-cli not found at {PARAKEET_CLI_PATH}"
        log.warning(f"{reason} - falling back to local")
        return None, reason

    model_path = _ensure_model()
    if model_path is None:
        return None, "Parakeet model download failed"

    try:
        duration = _probe_duration(input_path)
        with tempfile.TemporaryDirectory(prefix="parakeet_transcribe_") as tmp:
            tmp_path = Path(tmp)
            if duration <= PARAKEET_CHUNK_SECONDS:
                full_audio = str(tmp_path / "full.flac")
                _extract_audio(input_path, full_audio)
                chunks = [(full_audio, 0.0)]
            else:
                log.info(
                    f"Audio is {duration / 60:.1f} min, exceeding Parakeet's "
                    f"single-pass limit - splitting into "
                    f"{PARAKEET_CHUNK_SECONDS // 60}-minute chunks"
                )
                chunks = _build_chunks(
                    input_path, tmp_path, duration, PARAKEET_CHUNK_SECONDS
                )

            all_segments: List[ParakeetSegment] = []
            for i, (chunk_path, offset) in enumerate(chunks):
                log.debug(f"Transcribing Parakeet chunk {i + 1}/{len(chunks)}")
                segments = _transcribe_chunk(model_path, chunk_path)
                for seg in segments:
                    seg.start += offset
                    seg.end += offset
                all_segments.extend(segments)

            log.info(
                f"Parakeet transcription succeeded: {len(all_segments)} segments, "
                f"{duration / 60:.1f} min of audio, {len(chunks)} chunk(s)"
            )
            return all_segments, None
    except Exception as e:
        reason = str(e)
        log.warning(f"Parakeet transcription failed, falling back to local: {reason}")
        return None, reason
