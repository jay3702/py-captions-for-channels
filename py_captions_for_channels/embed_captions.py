#!/usr/bin/env python3
"""
embed_captions.py
Safely replace embedded/delayed captions in Channels DVR recordings with externally
generated SRT captions.
Preserves Channels’ database identity and Android compatibility.
"""

import os
import sys
import time
import shutil
import subprocess

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from py_captions_for_channels.logging.structured_logger import get_logger
from py_captions_for_channels.database import get_db
from py_captions_for_channels.progress_tracker import get_progress_tracker
from py_captions_for_channels.services.execution_service import ExecutionService
from py_captions_for_channels.config import (
    OPTIMIZATION_MODE,
    CAPTION_DELAY_MS,
    AUDIO_LANGUAGE,
    SUBTITLE_LANGUAGE,
    LANGUAGE_FALLBACK,
    PRESERVE_ALL_AUDIO_TRACKS,
    NVENC_CQ,
    X264_CRF,
    HWACCEL_DECODE,
    GPU_ENCODER,
    QSV_PRESET,
    QSV_GLOBAL_QUALITY,
    AMF_QUALITY,
    AMF_QP,
    VAAPI_QP,
    VAAPI_DEVICE,
)
from py_captions_for_channels.encoding_profiles import (
    get_whisper_parameters,
    get_ffmpeg_parameters,
)
from py_captions_for_channels.system_monitor import get_pipeline_timeline
from py_captions_for_channels.stream_detector import select_streams

# Unique identifier for our subtitle tracks
SUBTITLE_TRACK_NAME = "py-captions-for-channels"


def extract_channel_number(video_path):
    """
    Attempt to extract channel number from the recording file path.

    Looks for patterns like:
    - Directory names: "4.1 KRON", "11.3 KNTV", "6030 CNN"
    - Path components with channel info
    - Falls back to Channels DVR API lookup if not found in path

    Returns:
        str or None: Channel number (e.g., "4.1", "6030") or None if not found
    """
    import re
    from py_captions_for_channels.channels_api import ChannelsAPI
    from py_captions_for_channels.config import CHANNELS_API_URL

    # Normalize path: strip temporary/backup extensions to ensure we look up
    # the original recording path.  Order matters — try the longest (most
    # specific) suffixes first so a combined suffix like .cc4chan.orig.tmp is
    # fully removed before a shorter suffix like .orig can match.
    path_str = str(video_path).replace("\\", "/")
    for suffix in [
        ".cc4chan.orig.tmp",
        ".cc4chan.orig",
        ".cc4chan.av.mp4",
        ".cc4chan.muxed.mp4",
        ".cc4chan.temp.wav",
        ".srt.cc4chan.tmp",
        # Legacy patterns (pre-cc4chan)
        ".orig.tmp",
        ".orig",
        ".av.mp4",
        ".muxed.mp4",
        ".temp.wav",
        ".tmp",
    ]:
        if path_str.endswith(suffix):
            path_str = path_str[: -len(suffix)]
            break

    # Pattern 1: OTA channels (X.Y format) in directory name
    # e.g., "/recordings/TV/4.1 KRON/..." or "/4.1 - KRON/..."
    ota_match = re.search(r"/(\d+\.\d+)[\s\-]", path_str)
    if ota_match:
        return ota_match.group(1)

    # Pattern 2: 4+ digit TV Everywhere channels
    # e.g., "/6030 CNN/..." or "/6030-CNN/..."
    tve_match = re.search(r"/(\d{4,})[\s\-]", path_str)
    if tve_match:
        return tve_match.group(1)

    # Pattern 3: Check filename itself for channel info
    # e.g., "Recording-4.1-..." or "Recording_6030_..."
    filename = Path(video_path).name
    filename_ota = re.search(r"[-_](\d+\.\d+)[-_]", filename)
    if filename_ota:
        return filename_ota.group(1)

    filename_tve = re.search(r"[-_](\d{4,})[-_]", filename)
    if filename_tve:
        return filename_tve.group(1)

    # Pattern 4: Fall back to Channels DVR API lookup
    try:
        api = ChannelsAPI(CHANNELS_API_URL)
        channel = api.get_channel_by_path(str(video_path))
        if channel:
            return channel
    except Exception:
        pass  # API lookup failed, return None

    # Could not determine channel number
    return None


def detect_variable_frame_rate(video_path, log):
    """
    Detect if video uses variable frame rate (VFR).
    Returns True for VFR (Chrome capture), False for CFR (broadcast).

    Detection strategy:
    - Check avg_frame_rate: 0/0 indicates VFR
    - Also check if r_frame_rate looks like timebase (90000/1) vs fps
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,r_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.check_output(cmd, text=True).strip().split("\n")
        if len(result) >= 2:
            r_frame_rate = result[0].strip()
            avg_frame_rate = result[1].strip()

            # avg_frame_rate of 0/0 is definitive VFR indicator
            if avg_frame_rate == "0/0":
                log.info(
                    f"Detected VFR content "
                    f"(avg_frame_rate=0/0, r_frame_rate={r_frame_rate})"
                )
                return True

            # Check for high frame rate like 90000/1 (timebase, not fps)
            if r_frame_rate.startswith("90000/"):
                log.info(f"Detected potential VFR (r_frame_rate={r_frame_rate})")
                return True

            log.info(
                f"Detected CFR content " f"(avg={avg_frame_rate}, r={r_frame_rate})"
            )
            return False
    except subprocess.CalledProcessError as e:
        log.warning(f"Failed to probe frame rate, assuming CFR: {e}")
        return False


# ---------------------------------------------------------------------------
# Multi-GPU hardware acceleration detection and command building
# ---------------------------------------------------------------------------
# Supported backends:
#   NVIDIA  — NVDEC (CUVID) decode + NVENC encode  (fully implemented)
#   Intel   — QSV decode + QSV encode               (stubbed / untested)
#   AMD     — VAAPI decode + AMF/VAAPI encode        (stubbed / untested)
#
# Detection order (when HWACCEL_DECODE=auto / GPU_ENCODER=auto):
#   1. NVIDIA CUVID/NVENC  (most common in transcoding servers)
#   2. Intel QSV           (common in NUCs and integrated GPUs)
#   3. VA-API              (universal Linux API — Intel iGPU, AMD dGPU)
#   4. CPU software        (always-available fallback)
# ---------------------------------------------------------------------------


@dataclass
class GPUBackend:
    """Describes a detected GPU hardware acceleration backend."""

    name: str  # "nvidia", "qsv", "vaapi", "amf", "cpu"
    hwaccel_type: str  # ffmpeg -hwaccel value ("cuda", "qsv", "vaapi", "")
    encoder: str  # ffmpeg -c:v value ("h264_nvenc", "h264_qsv", etc.)
    # Decoder map: input_codec → ffmpeg decoder name
    decoders: dict  # e.g. {"mpeg2video": "mpeg2_cuvid", "h264": "h264_cuvid"}
    deinterlace_filter: str  # e.g. "yadif_cuda", "deinterlace_qsv", "yadif"
    hwaccel_output_format: str  # e.g. "cuda", "qsv", "vaapi", ""
    # Extra input flags (e.g. ["-hwaccel_device", "/dev/dri/renderD128"])
    extra_input_flags: list
    available: bool = False


# ---- Capability cache (populated once per process) ----
_ffmpeg_caps_cache: dict = {}


def _query_ffmpeg_capabilities() -> dict:
    """Query ffmpeg for available encoders, decoders, and filters.

    Returns a dict with keys: 'encoders', 'decoders', 'filters' — each a str
    of the raw ffmpeg output for substring checks.
    Results are cached for the process lifetime.
    """
    if _ffmpeg_caps_cache:
        return _ffmpeg_caps_cache

    for key, flag in [
        ("encoders", "-encoders"),
        ("decoders", "-decoders"),
        ("filters", "-filters"),
    ]:
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", flag],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            _ffmpeg_caps_cache[key] = result.stdout
        except Exception:
            _ffmpeg_caps_cache[key] = ""

    return _ffmpeg_caps_cache


def _detect_nvidia_backend() -> GPUBackend:
    """Detect NVIDIA NVENC/NVDEC capabilities."""
    caps = _query_ffmpeg_capabilities()

    decoders = {}
    for codec, dec_name in [
        ("mpeg2video", "mpeg2_cuvid"),
        ("h264", "h264_cuvid"),
        ("hevc", "hevc_cuvid"),
    ]:
        if dec_name in caps.get("decoders", ""):
            decoders[codec] = dec_name

    has_encoder = "h264_nvenc" in caps.get("encoders", "")
    has_deint = "yadif_cuda" in caps.get("filters", "")

    return GPUBackend(
        name="nvidia",
        hwaccel_type="cuda",
        encoder="h264_nvenc",
        decoders=decoders,
        deinterlace_filter=(
            "yadif_cuda=mode=send_frame:parity=auto:deint=all" if has_deint else ""
        ),
        hwaccel_output_format="cuda",
        extra_input_flags=[],
        available=has_encoder and len(decoders) > 0,
    )


def _detect_qsv_backend() -> GPUBackend:
    """Detect Intel Quick Sync Video capabilities.

    QSV requires Intel GPU with media driver. Available on most Intel CPUs
    with integrated graphics (HD/UHD/Iris) and Intel Arc discrete GPUs.
    """
    caps = _query_ffmpeg_capabilities()

    decoders = {}
    for codec, dec_name in [
        ("mpeg2video", "mpeg2_qsv"),
        ("h264", "h264_qsv"),
        ("hevc", "hevc_qsv"),
    ]:
        if dec_name in caps.get("decoders", ""):
            decoders[codec] = dec_name

    has_encoder = "h264_qsv" in caps.get("encoders", "")
    has_deint = "deinterlace_qsv" in caps.get("filters", "")

    return GPUBackend(
        name="qsv",
        hwaccel_type="qsv",
        encoder="h264_qsv",
        decoders=decoders,
        deinterlace_filter="deinterlace_qsv" if has_deint else "",
        hwaccel_output_format="qsv",
        extra_input_flags=[],
        available=has_encoder and len(decoders) > 0,
    )


def _detect_vaapi_backend() -> GPUBackend:
    """Detect VA-API capabilities (Intel iGPU / AMD dGPU on Linux).

    VA-API is the universal Linux hardware video API. Works with:
    - Intel iGPU (via intel-media-va-driver or i965-va-driver)
    - AMD dGPU (via mesa / AMDGPU-PRO)
    Requires /dev/dri/renderD128 (or configured VAAPI_DEVICE).
    """
    caps = _query_ffmpeg_capabilities()

    decoders = {}
    # VA-API uses the generic hwaccel mechanism; ffmpeg's -hwaccel vaapi
    # handles decoding without explicit per-codec decoder names.  However,
    # we still check for the encoder to confirm VA-API is functional.
    # For decode, VA-API uses the built-in decoders with -hwaccel vaapi.
    # We'll map codecs that VA-API commonly supports.
    for codec in ("mpeg2video", "h264", "hevc"):
        # VA-API decode is handled by -hwaccel vaapi (no _vaapi decoder names)
        # We just note which codecs are generally supported
        decoders[codec] = codec  # placeholder — hwaccel vaapi handles it

    has_encoder = "h264_vaapi" in caps.get("encoders", "")
    has_deint = "deinterlace_vaapi" in caps.get("filters", "")

    return GPUBackend(
        name="vaapi",
        hwaccel_type="vaapi",
        encoder="h264_vaapi",
        decoders=decoders if has_encoder else {},
        deinterlace_filter="deinterlace_vaapi" if has_deint else "",
        hwaccel_output_format="vaapi",
        extra_input_flags=["-hwaccel_device", VAAPI_DEVICE],
        available=has_encoder,
    )


def _detect_amf_backend() -> GPUBackend:
    """Detect AMD AMF (Advanced Media Framework) capabilities.

    AMF is AMD's proprietary encoding API. Available on:
    - Windows: via AMD Adrenalin drivers
    - Linux: via AMDGPU-PRO driver (not open-source mesa)
    Note: AMF encoding only — decode typically uses VA-API on Linux.
    """
    caps = _query_ffmpeg_capabilities()

    has_encoder = "h264_amf" in caps.get("encoders", "")

    # AMF is encode-only; decode is typically handled by VA-API or CPU.
    # For hwaccel decode on AMD, we fall back to VAAPI.
    return GPUBackend(
        name="amf",
        hwaccel_type="",  # AMF doesn't have its own hwaccel decode type
        encoder="h264_amf",
        decoders={},  # AMF is encode-only
        deinterlace_filter="",
        hwaccel_output_format="",
        extra_input_flags=[],
        available=has_encoder,
    )


# ---- Cached backend detection result ----
_detected_backend: Optional[GPUBackend] = None


def detect_gpu_backend(log) -> GPUBackend:
    """Auto-detect the best available GPU backend.

    Detection order: NVIDIA → QSV → VAAPI → AMF → CPU.
    Results are cached for the process lifetime.

    If GPU_ENCODER is set to a specific value (not 'auto'), that backend
    is returned directly (with available=True assumed — failure will be
    caught at encode time with a fallback to CPU).
    """
    global _detected_backend
    if _detected_backend is not None:
        return _detected_backend

    # If user forced a specific encoder, build and return that backend
    forced_map = {
        "nvenc": _detect_nvidia_backend,
        "qsv": _detect_qsv_backend,
        "vaapi": _detect_vaapi_backend,
        "amf": _detect_amf_backend,
    }
    if GPU_ENCODER != "auto" and GPU_ENCODER != "cpu":
        detector = forced_map.get(GPU_ENCODER)
        if detector:
            backend = detector()
            if backend.available:
                log.info(f"GPU encoder forced: {backend.name} ({backend.encoder})")
            else:
                log.warning(
                    f"GPU_ENCODER={GPU_ENCODER} requested but not available in ffmpeg"
                )
            _detected_backend = backend
            return backend

    if GPU_ENCODER == "cpu":
        cpu_backend = GPUBackend(
            name="cpu",
            hwaccel_type="",
            encoder="libx264",
            decoders={},
            deinterlace_filter="yadif",
            hwaccel_output_format="",
            extra_input_flags=[],
            available=True,
        )
        log.info("GPU encoding disabled (GPU_ENCODER=cpu), using libx264")
        _detected_backend = cpu_backend
        return cpu_backend

    # Auto-detection: try each backend in priority order
    for detect_fn, label in [
        (_detect_nvidia_backend, "NVIDIA NVENC"),
        (_detect_qsv_backend, "Intel QSV"),
        (_detect_vaapi_backend, "VA-API"),
        (_detect_amf_backend, "AMD AMF"),
    ]:
        backend = detect_fn()
        if backend.available:
            log.info(f"Auto-detected GPU backend: {label} ({backend.encoder})")
            _detected_backend = backend
            return backend

    # No GPU backend found — fall back to CPU
    cpu_backend = GPUBackend(
        name="cpu",
        hwaccel_type="",
        encoder="libx264",
        decoders={},
        deinterlace_filter="yadif",
        hwaccel_output_format="",
        extra_input_flags=[],
        available=True,
    )
    log.info("No GPU encoder detected, using CPU (libx264)")
    _detected_backend = cpu_backend
    return cpu_backend


# Audio codecs that can be muxed directly into an MP4 container
# without re-encoding.  This covers virtually every broadcast source.
_MP4_COMPATIBLE_AUDIO = frozenset(
    ["aac", "ac3", "eac3", "mp3", "flac", "opus", "alac", "mp2"]
)


def _probe_audio_codecs(media_path: str, log) -> list:
    """Return a list of audio codec names for all audio streams."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        codecs = [
            line.strip().lower()
            for line in result.stdout.strip().split("\n")
            if line.strip()
        ]
        log.debug(f"Input audio codecs: {codecs}")
        return codecs
    except Exception as e:
        log.warning(f"Failed to probe audio codecs: {e}")
        return []


def _probe_input_codec(video_path: str, log) -> str:
    """Return the video codec name of the *first* video stream (e.g. 'mpeg2video')."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        # OTA MPEG-TS containers can have multiple video programs,
        # causing ffprobe to return multiple lines — take only the first.
        codec = result.stdout.strip().split("\n")[0].strip().lower()
        log.debug(f"Input video codec: {codec}")
        return codec
    except Exception as e:
        log.warning(f"Failed to probe input codec: {e}")
        return "unknown"


def _probe_field_order(video_path: str, log) -> str:
    """Return field_order of the first video stream (e.g. 'tt', 'bb', 'progressive')."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=field_order",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        # Take first line only — multi-program MPEG-TS may return multiple.
        field_order = result.stdout.strip().split("\n")[0].strip().lower()
        log.debug(f"Input field order: {field_order}")
        return field_order
    except Exception as e:
        log.debug(f"Failed to probe field order: {e}")
        return "unknown"


def build_hwaccel_flags(input_path: str, log) -> list:
    """Build hwaccel input flags for ffmpeg based on config + capabilities.

    Returns a list of ffmpeg args to prepend *before* ``-i``, or an empty
    list when hardware decode is not available / not configured.

    When hardware decode is active and the source is interlaced, a
    GPU deinterlace video filter is appended to the returned list as well
    (after a ``-vf`` flag) so the caller can splice it in.

    Supports: NVIDIA CUVID, Intel QSV, VA-API (Intel/AMD).
    """
    if HWACCEL_DECODE == "off":
        log.debug("Hardware decode disabled (HWACCEL_DECODE=off)")
        return []

    backend = detect_gpu_backend(log)

    # If the backend has no hwaccel decode support, skip
    if not backend.hwaccel_type or not backend.decoders:
        log.debug(f"Backend '{backend.name}' has no hardware decode — using CPU decode")
        return []

    # Check if user forced a specific hwaccel type
    hwaccel_type_map = {
        "cuda": "cuda",
        "qsv": "qsv",
        "vaapi": "vaapi",
    }
    if HWACCEL_DECODE != "auto":
        forced_type = hwaccel_type_map.get(HWACCEL_DECODE)
        if forced_type and forced_type != backend.hwaccel_type:
            log.warning(
                f"HWACCEL_DECODE={HWACCEL_DECODE} but detected backend is "
                f"'{backend.name}' ({backend.hwaccel_type}) — attempting forced type"
            )
            # For forced HWACCEL_DECODE, try to use the corresponding backend
            forced_backends = {
                "cuda": _detect_nvidia_backend,
                "qsv": _detect_qsv_backend,
                "vaapi": _detect_vaapi_backend,
            }
            detector = forced_backends.get(forced_type)
            if detector:
                forced_backend = detector()
                if forced_backend.available and forced_backend.decoders:
                    backend = forced_backend
                else:
                    log.warning(
                        f"Forced hwaccel '{forced_type}' not available — "
                        f"using detected backend"
                    )

    input_codec = _probe_input_codec(input_path, log)

    # Check if this backend has a decoder for our input codec
    decoder = backend.decoders.get(input_codec)
    if not decoder:
        log.info(
            f"Backend '{backend.name}' has no decoder for '{input_codec}' "
            f"— using CPU decode"
        )
        return []

    # Build hwaccel flags
    flags = ["-hwaccel", backend.hwaccel_type]

    if backend.hwaccel_output_format:
        flags.extend(["-hwaccel_output_format", backend.hwaccel_output_format])

    # Add any extra input flags (e.g. -hwaccel_device for VAAPI)
    flags.extend(backend.extra_input_flags)

    # For NVIDIA CUVID, we specify the decoder explicitly
    if backend.name == "nvidia":
        flags.extend(["-c:v", decoder])
    # For QSV, specify the QSV decoder
    elif backend.name == "qsv":
        flags.extend(["-c:v", decoder])
    # For VAAPI, ffmpeg handles decoder selection via -hwaccel vaapi
    # (no explicit -c:v needed)

    # Check if source is interlaced — if so, add GPU deinterlace filter
    field_order = _probe_field_order(input_path, log)
    is_interlaced = field_order in ("tt", "bb", "tb", "bt")

    if is_interlaced and backend.deinterlace_filter:
        flags.extend(["-vf", backend.deinterlace_filter])
        log.info(
            f"Hardware decode enabled: {backend.name} ({decoder}) + "
            f"{backend.deinterlace_filter.split('=')[0]} deinterlace "
            f"(field_order={field_order})"
        )
    elif is_interlaced:
        # Interlaced source but no GPU deinterlace filter — fall back to
        # CPU decode so software yadif can handle it.
        log.info(
            f"Source is interlaced ({field_order}) but {backend.name} has no GPU "
            f"deinterlace filter — CPU decode with software deinterlace"
        )
        return []
    else:
        log.info(
            f"Hardware decode enabled: {backend.name} ({decoder}) "
            f"(progressive source)"
        )

    return flags


class StepTracker:
    """Record step timing to the database if available."""

    def __init__(self, execution_id, log):
        self.execution_id = execution_id
        self.log = log

    def _with_service(self, fn):
        db_gen = get_db()
        try:
            db = next(db_gen)
            service = ExecutionService(db)
            return fn(service)
        except Exception as exc:
            self.log.debug("Step tracking skipped: %s", exc)
            return None
        finally:
            try:
                next(db_gen)
            except Exception:
                pass

    def start(self, step_name, input_path=None, output_path=None):
        def _run(service):
            updated = service.update_step_status(
                self.execution_id, step_name, "running"
            )
            if not updated:
                service.add_step(
                    self.execution_id,
                    step_name,
                    status="running",
                    input_path=input_path,
                    output_path=output_path,
                )

        self._with_service(_run)

    def finish(self, step_name, status="completed"):
        def _run(service):
            updated = service.update_step_status(self.execution_id, step_name, status)
            if not updated:
                service.add_step(
                    self.execution_id,
                    step_name,
                    status=status,
                )

        self._with_service(_run)


def update_misc_progress(job_id, percent, message):
    """Update file/misc progress indicator in the UI."""
    try:
        progress_tracker = get_progress_tracker()
        progress_tracker.update_progress(job_id, "misc", percent, message)
    except Exception:
        pass


def update_whisper_progress(job_id, percent, message):
    """Update Whisper progress indicator in the UI."""
    try:
        progress_tracker = get_progress_tracker()
        progress_tracker.update_progress(job_id, "whisper", percent, message)
    except Exception:
        pass


def update_ffmpeg_progress(job_id, percent, message):
    """Update ffmpeg progress indicator in the UI."""
    try:
        progress_tracker = get_progress_tracker()
        progress_tracker.update_progress(job_id, "ffmpeg", percent, message)
    except Exception:
        pass


def probe_muxed_durations(muxed_path, log):
    """Return (video_duration, audio_duration, subtitle_duration) for muxed file."""

    def get_stream_duration(stream_type):
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            stream_type,
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            muxed_path,
        ]
        try:
            out = subprocess.check_output(cmd, text=True)
            durs = [float(x) for x in out.strip().splitlines() if x.strip()]
            return max(durs) if durs else 0.0
        except Exception as e:
            log.warning(f"ffprobe failed for {stream_type}: {e}")
            return 0.0

    v_dur = get_stream_duration("v:0")
    a_dur = get_stream_duration("a:0")
    s_dur = get_stream_duration("s:0")
    log.info(
        f"Muxed durations: video={v_dur:.3f}s, audio={a_dur:.3f}s, "
        f"subtitle={s_dur:.3f}s"
    )
    return v_dur, a_dur, s_dur


# --- CONFIGURABLE ---
STABLE_INTERVAL = 10  # seconds between file size checks
STABLE_CONSECUTIVE = 3  # number of consecutive stable checks required
STABLE_TIMEOUT = 300  # max seconds to wait for stability (5 minutes)


def extract_job_id_from_path(path):
    # Example: /mnt/recordings/12345_20260131_120000.mpg → 12345_20260131_120000
    return Path(path).stem


def wait_for_file_stability(
    path,
    log,
    interval=STABLE_INTERVAL,
    consecutive=STABLE_CONSECUTIVE,
    timeout=STABLE_TIMEOUT,
):
    """
    Wait until file size is stable for N consecutive checks, or abort after timeout.
    # Logs size progression for debugging.
    """
    log.info(f"Waiting for file stability: {path}")
    last_size = -1
    stable_count = 0
    elapsed = 0
    while True:
        try:
            size = os.stat(path).st_size
        except Exception as e:
            log.warning(f"File not found or inaccessible: {e}")
            size = None
        log.debug(f"Check at {elapsed}s: size={size}")
        if size is not None and size == last_size:
            stable_count += 1
            log.debug(f"Stable count: {stable_count}/{consecutive}")
            if stable_count >= consecutive:
                log.info(f"File size stable at {size} bytes for {consecutive} checks.")
                break
        else:
            stable_count = 1 if size is not None else 0
            last_size = size
        time.sleep(interval)
        elapsed += interval
        if elapsed >= timeout:
            log.error(
                f"File did not stabilize after {timeout} seconds. "
                f"Last size: {size}. Aborting."
            )
            sys.exit(1)


def validate_audio_decodability(path, log):
    """
    Test if ffmpeg can safely decode audio from the file without crashing.

    Returns True if file is safe to decode directly, False if audio should
    be extracted to WAV first to avoid segfaults from corrupted video frames.

    MPEG2 files are always flagged for WAV extraction due to frequent
    corruption issues that can occur anywhere in the file.
    """
    # Check codec type first - MPEG2 is prone to corruption
    try:
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=5)
        codec = result.stdout.split("\n")[0].strip().lower()

        # MPEG2 files: always use WAV extraction (corruption can be anywhere)
        if "mpeg2video" in codec:
            log.warning(
                f"MPEG2 codec detected - using WAV extraction to avoid "
                f"potential corruption (codec: {codec})"
            )
            return False

    except Exception as e:
        log.warning(f"Failed to probe codec type: {e}, proceeding with decode test")

    # For other codecs, do a quick decode test of first few seconds
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-t",
        "5",  # Test first 5 seconds
        "-i",
        path,
        "-vn",  # Skip video (we only care about audio)
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        # Check for fatal errors in stderr that indicate corrupted frames
        if result.returncode != 0:
            stderr_lower = result.stderr.lower()
            if any(
                error in stderr_lower
                for error in [
                    "invalid frame dimensions",
                    "segmentation fault",
                    "invalid data",
                    "corrupt",
                    "error",
                ]
            ):
                log.warning(f"Audio decodability test failed: {result.stderr[:200]}")
                return False

        log.debug("Audio decodability test passed - file can be decoded directly")
        return True

    except subprocess.TimeoutExpired:
        log.warning(f"Audio decodability test timed out for {path}")
        return False
    except Exception as e:
        log.warning(f"Audio decodability test error for {path}: {e}")
        return False


def probe_duration(path, log):
    """Return duration in seconds using ffprobe."""
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
    try:
        out = subprocess.check_output(cmd, text=True)
        return float(out.strip())
    except Exception as e:
        log.warning(f"ffprobe failed for {path}: {e}")
        return 0.0


def preserve_original(mpg_path, log):
    """
    Preserve the original file once and NEVER overwrite it.

    The .orig file represents the pristine, unprocessed original.
    Once created, it must never be modified, even if the .mpg changes.
    """
    orig_path = mpg_path + ".cc4chan.orig"
    tmp_path = orig_path + ".tmp"

    # Also check for legacy .orig naming (migration support)
    legacy_orig_path = mpg_path + ".orig"

    if os.path.exists(legacy_orig_path) and not os.path.exists(orig_path):
        # Rename legacy .orig to new naming convention
        os.rename(legacy_orig_path, orig_path)
        log.info(
            f"Migrated legacy .orig to new naming: {legacy_orig_path} -> {orig_path}"
        )
    elif not os.path.exists(orig_path):
        log.info(f"Preserving original (first time): {mpg_path} -> {orig_path}")
        shutil.copy2(mpg_path, tmp_path)
        os.replace(tmp_path, orig_path)
    else:
        log.info(f".cc4chan.orig already exists and will not be modified: {orig_path}")


def srt_exists_and_valid(srt_path):
    return os.path.exists(srt_path) and os.path.getsize(srt_path) > 0


def probe_media_end_time(mpg_path, log):
    """Return max end time (seconds) of video/audio streams using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:a",
        "-show_entries",
        "stream=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        mpg_path,
    ]
    try:
        out = subprocess.check_output(cmd, text=True)
        durations = [float(x) for x in out.strip().splitlines() if x.strip()]
        return max(durations) if durations else 0.0
    except Exception as e:
        log.error(f"ffprobe failed: {e}")
        return 0.0


def detect_subtitle_streams(video_path, log):
    """
    Detect subtitle streams in video file.
    Returns list of dicts with codec_name and title metadata.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_name:stream_tags=title,handler_name",
        "-of",
        "json",
        video_path,
    ]
    try:
        import json

        result = subprocess.check_output(cmd, text=True)
        data = json.loads(result)
        streams = data.get("streams", [])
        log.debug(f"Found {len(streams)} subtitle stream(s) in {video_path}")
        for i, s in enumerate(streams):
            tags = s.get("tags", {})
            title = tags.get("title", tags.get("handler_name", "Unknown"))
            log.debug(f"  Stream {i}: {s.get('codec_name')} - {title}")
        return streams
    except Exception as e:
        log.warning(f"Failed to detect subtitle streams: {e}")
        return []


def has_our_subtitles(video_path, log):
    """
    Check if video already has our subtitle track.
    Returns True if our unique subtitle track name is found.
    """
    streams = detect_subtitle_streams(video_path, log)
    for stream in streams:
        tags = stream.get("tags", {})
        title = tags.get("title", tags.get("handler_name", ""))
        if SUBTITLE_TRACK_NAME in title:
            log.info(f"Found our subtitle track: {title}")
            return True
    return False


def probe_srt_end_time(srt_path):
    """Return end time (seconds) of last subtitle in SRT."""
    import re

    last_end = 0.0
    timepat = re.compile(r"\d{2}:\d{2}:\d{2},\d{3} --> (\d{2}):(\d{2}):(\d{2}),(\d{3})")
    with open(srt_path, encoding="utf-8") as f:
        for line in f:
            m = timepat.search(line)
            if m:
                h, m_, s, ms = map(int, m.groups())
                end = h * 3600 + m_ * 60 + s + ms / 1000.0
                if end > last_end:
                    last_end = end
    return last_end


def validate_and_trim_srt(srt_path, max_end_time, log):
    """Trim last subtitle if it exceeds max_end_time."""
    import re

    lines = []
    timepat = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})")
    with open(srt_path, encoding="utf-8") as f:
        for line in f:
            m = timepat.match(line)
            if m:
                start, end = m.groups()
                h, m_, s, ms = map(int, re.split("[:,]", end))
                end_sec = h * 3600 + m_ * 60 + s + ms / 1000.0
                if end_sec > max_end_time:
                    # Clamp end time
                    end_sec = max_end_time
                    h = int(end_sec // 3600)
                    m_ = int((end_sec % 3600) // 60)
                    s = int(end_sec % 60)
                    ms = int((end_sec - int(end_sec)) * 1000)
                    new_end = f"{h:02}:{m_:02}:{s:02},{ms:03}"
                    line = f"{start} --> {new_end}\n"
            lines.append(line)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log.info(f"Trimmed SRT to {max_end_time:.2f}s for Android compatibility.")


def _build_gpu_encoder_args(backend: "GPUBackend", ffmpeg_params: dict) -> list:
    """Build the encoder-specific ffmpeg arguments for a given GPU backend.

    Returns a list like ["-c:v", "h264_nvenc", "-preset", "fast", "-rc", "vbr", ...].
    """
    if backend.name == "nvidia":
        preset = ffmpeg_params.get("nvenc_preset", "fast")
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            preset,
            "-rc",
            "vbr",
            "-cq",
            str(NVENC_CQ),
        ]
    elif backend.name == "qsv":
        preset = ffmpeg_params.get("qsv_preset", QSV_PRESET)
        return [
            "-c:v",
            "h264_qsv",
            "-preset",
            preset,
            "-global_quality",
            str(QSV_GLOBAL_QUALITY),
        ]
    elif backend.name == "amf":
        quality = ffmpeg_params.get("amf_quality", AMF_QUALITY)
        return [
            "-c:v",
            "h264_amf",
            "-quality",
            quality,
            "-qp_i",
            str(AMF_QP),
            "-qp_p",
            str(AMF_QP),
        ]
    elif backend.name == "vaapi":
        return [
            "-c:v",
            "h264_vaapi",
            "-qp",
            str(VAAPI_QP),
        ]
    else:
        # CPU fallback
        preset = ffmpeg_params.get("x264_preset", "fast")
        return [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(X264_CRF),
        ]


def encode_av_only(
    mpg_orig, temp_av, log, job_id=None, source_path=None, audio_stream_index=None
):
    """Step 1: Encode video (GPU if available, else CPU), copy audio, no subs.

    Tries GPU encoders in priority order (NVENC → QSV → AMF → VAAPI) based
    on the detected backend, with automatic fallback to CPU libx264.

    Args:
        mpg_orig: Path to .orig file to encode
        temp_av: Output path for encoded video
        log: Logger instance
        job_id: Optional job ID for progress tracking
        source_path: Original .mpg path (without .orig) for channel extraction
        audio_stream_index: Optional audio stream index
            (for filtering tracks)
    """
    # Get video duration for progress tracking
    video_duration = probe_duration(mpg_orig, log)

    # Detect if content is VFR (Chrome capture) or CFR (broadcast TV)
    is_vfr = detect_variable_frame_rate(mpg_orig, log)

    # Determine encoder presets based on OPTIMIZATION_MODE
    # Use source_path for channel extraction (API knows about .mpg, not .orig)
    channel_number = extract_channel_number(source_path or mpg_orig)
    print(f"[OPTIMIZATION] ffmpeg channel detected: {channel_number}")
    if OPTIMIZATION_MODE == "automatic":
        ffmpeg_params = get_ffmpeg_parameters(mpg_orig, channel_number)
        log.info(
            f"Using automatic ffmpeg presets (channel={channel_number}): "
            f"{ffmpeg_params}"
        )
        print(
            f"[OPTIMIZATION] Using automatic ffmpeg: "
            f"nvenc={ffmpeg_params.get('nvenc_preset')}, "
            f"x264={ffmpeg_params.get('x264_preset')}"
        )
    else:
        # Standard mode: use hardcoded presets (current default)
        ffmpeg_params = {
            "nvenc_preset": "fast",
            "qsv_preset": "fast",
            "amf_quality": "balanced",
            "vaapi_compression": 4,
            "x264_preset": "fast",
        }
        log.info("Using standard ffmpeg presets (OPTIMIZATION_MODE=standard)")

    # Detect GPU backend
    backend = detect_gpu_backend(log)

    # Attempt hardware-accelerated decoding (NVDEC/QSV/VAAPI) to keep the
    # entire decode→encode pipeline on the GPU, avoiding CPU bottleneck.
    hwaccel_flags = build_hwaccel_flags(mpg_orig, log)

    # When hwaccel includes a deinterlace filter, a -vf flag is already set.
    # Extract it so we can place it correctly in the command.
    vf_flags = []
    input_flags = []
    for i, flag in enumerate(hwaccel_flags):
        if flag == "-vf" and i + 1 < len(hwaccel_flags):
            vf_flags = ["-vf", hwaccel_flags[i + 1]]
        else:
            if i > 0 and hwaccel_flags[i - 1] == "-vf":
                continue  # Already captured as part of vf_flags
            input_flags.append(flag)

    # Determine audio stream mapping based on configuration
    if PRESERVE_ALL_AUDIO_TRACKS or audio_stream_index is None:
        # Default: preserve all audio tracks for language options
        audio_map = ["-map", "0:v", "-map", "0:a?"]
        if not PRESERVE_ALL_AUDIO_TRACKS and audio_stream_index is not None:
            log.info("Preserving all audio tracks (PRESERVE_ALL_AUDIO_TRACKS=true)")
    else:
        # Performance mode: filter to only selected language track
        audio_map = ["-map", "0:v", "-map", f"0:{audio_stream_index}"]
        log.info(
            f"Filtering to audio stream {audio_stream_index} "
            f"(PRESERVE_ALL_AUDIO_TRACKS=false, faster encoding)"
        )

    # Determine audio codec strategy
    from py_captions_for_channels.config import AUDIO_CODEC

    audio_codecs = _probe_audio_codecs(mpg_orig, log)
    all_mp4_ok = audio_codecs and all(c in _MP4_COMPATIBLE_AUDIO for c in audio_codecs)

    if AUDIO_CODEC == "copy":
        audio_codec_flags = ["-c:a", "copy"]
        log.info("Audio: stream copy (AUDIO_CODEC=copy)")
    elif AUDIO_CODEC == "aac":
        audio_codec_flags = ["-c:a", "aac", "-b:a", "256k"]
        log.info("Audio: re-encode to AAC 256k (AUDIO_CODEC=aac)")
    else:  # auto
        if all_mp4_ok:
            audio_codec_flags = ["-c:a", "copy"]
            log.info(
                f"Audio: stream copy — source codecs {audio_codecs} "
                f"are MP4-compatible (AUDIO_CODEC=auto)"
            )
        else:
            audio_codec_flags = ["-c:a", "aac", "-b:a", "256k"]
            log.info(
                f"Audio: re-encode to AAC 256k — source codecs "
                f"{audio_codecs} not all MP4-compatible (AUDIO_CODEC=auto)"
            )

    audio_tail = (
        audio_codec_flags
        + [
            "-analyzeduration",
            "2147483647",
            "-probesize",
            "2147483647",
        ]
        + audio_map
        + [temp_av]
    )

    # ---- Try GPU encode (with hwaccel decode) ----
    if backend.name != "cpu":
        encoder_args = _build_gpu_encoder_args(backend, ffmpeg_params)
        cmd_gpu = (
            ["ffmpeg", "-y", "-progress", "pipe:2"]
            + input_flags
            + ["-i", mpg_orig]
            + encoder_args
        )

        # Add video filter (GPU deinterlace) if hwaccel detection provided one
        if vf_flags:
            cmd_gpu.extend(vf_flags)
        if is_vfr:
            cmd_gpu.extend(["-vsync", "vfr"])
        cmd_gpu.extend(audio_tail)

        step_label = (
            f"Encoding ({backend.name.upper()}+hwaccel)"
            if input_flags
            else f"Encoding ({backend.name.upper()})"
        )
        log.info(f"Trying {backend.name.upper()} encode: {' '.join(cmd_gpu)}")
        try:
            _run_ffmpeg_with_progress(cmd_gpu, video_duration, step_label, log, job_id)
            return
        except subprocess.CalledProcessError:
            log.warning(f"{backend.name.upper()} encode failed")

        # ---- Retry GPU encode WITHOUT hwaccel decode ----
        if input_flags:
            log.warning(
                f"{backend.name.upper()} with hwaccel decode failed, "
                f"retrying without hardware decode"
            )
            cmd_gpu_sw = [
                "ffmpeg",
                "-y",
                "-progress",
                "pipe:2",
                "-i",
                mpg_orig,
            ] + encoder_args
            if is_vfr:
                cmd_gpu_sw.extend(["-vsync", "vfr"])
            cmd_gpu_sw.extend(audio_tail)

            log.info(
                f"Trying {backend.name.upper()} (sw decode): " f"{' '.join(cmd_gpu_sw)}"
            )
            try:
                _run_ffmpeg_with_progress(
                    cmd_gpu_sw,
                    video_duration,
                    f"Encoding ({backend.name.upper()}, sw decode)",
                    log,
                    job_id,
                )
                return
            except subprocess.CalledProcessError:
                log.warning(
                    f"{backend.name.upper()} (sw decode) also failed, "
                    f"falling to CPU"
                )

    # ---- CPU fallback (libx264) ----
    x264_preset = ffmpeg_params.get("x264_preset", "fast")
    cmd_cpu = [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",
        "-i",
        mpg_orig,
        "-c:v",
        "libx264",
        "-preset",
        x264_preset,
        "-crf",
        str(X264_CRF),
    ]

    if is_vfr:
        cmd_cpu.extend(["-vsync", "vfr"])
    cmd_cpu.extend(audio_tail)

    log.info(f"Trying CPU encode: {' '.join(cmd_cpu)}")
    try:
        _run_ffmpeg_with_progress(
            cmd_cpu, video_duration, "Encoding (CPU)", log, job_id
        )
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg failed: {e}")
        sys.exit(1)


def _run_ffmpeg_with_progress(cmd, duration, step_name, log, job_id=None):
    """Run ffmpeg and parse progress from stderr output."""
    import re

    # Report initial progress immediately so UI shows status
    if job_id:
        update_ffmpeg_progress(job_id, 0, f"{step_name}: starting...")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
    )

    last_progress = 0
    progress_pattern = re.compile(r"out_time_ms=(\d+)")

    try:
        for line in process.stderr:
            # Parse ffmpeg progress output (format: key=value)
            match = progress_pattern.search(line)
            if match and duration > 0:
                # out_time_ms is in microseconds
                current_time = int(match.group(1)) / 1000000.0
                progress = min(95, int((current_time / duration) * 100))

                # Report every 5% or significant progress
                if progress >= last_progress + 5:
                    if job_id:
                        update_ffmpeg_progress(
                            job_id,
                            progress,
                            f"{step_name}: {current_time:.0f}/{duration:.0f}s",
                        )
                    log.info(
                        f"ffmpeg progress: {progress}% "
                        f"({current_time:.1f}/{duration:.1f}s)"
                    )
                    last_progress = progress

        # Wait for process to complete
        returncode = process.wait()

        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, cmd)

        # Final progress update
        if job_id:
            update_ffmpeg_progress(job_id, 100, f"{step_name} complete")

    finally:
        process.stdout.close()
        process.stderr.close()


def probe_av_end(temp_av, log):
    """Step 2: Probe encoded A/V duration, return END = max(video, audio) - 0.050"""

    def get_stream_duration(stream_type):
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            stream_type,
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            temp_av,
        ]
        try:
            out = subprocess.check_output(cmd, text=True)
            durs = [float(x) for x in out.strip().splitlines() if x.strip()]
            return max(durs) if durs else 0.0
        except Exception as e:
            log.warning(f"ffprobe failed for {stream_type}: {e}")
            return 0.0

    v_dur = get_stream_duration("v:0")
    a_dur = get_stream_duration("a:0")
    end = max(v_dur, a_dur) - 0.050
    log.info(
        f"Probed durations: video={v_dur:.3f}s, audio={a_dur:.3f}s, END={end:.3f}s"
    )
    return max(end, 0.0)


def clamp_srt_to_end(srt_path, end_time, log):
    """Step 3: Clamp SRT cues to END, drop cues starting after END."""
    import re

    lines = []
    timepat = re.compile(
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})"
    )

    def to_sec(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    def to_srt_time(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    with open(srt_path, encoding="utf-8") as f:
        cue = []
        seq_num = 0
        for line in f:
            # Check if this is a sequence number line (digit-only)
            if line.strip().isdigit() and not cue:
                seq_num = int(line.strip())
                continue

            m = timepat.match(line)
            if m:
                start = to_sec(*m.groups()[:4])
                end = to_sec(*m.groups()[4:])
                if start > end_time:
                    cue = []  # drop this cue
                    continue
                if end > end_time:
                    end = end_time
                # Write sequence number, then timestamp
                new_line = f"{to_srt_time(start)} --> {to_srt_time(end)}\n"
                cue = [f"{seq_num}\n", new_line]
            elif line.strip() == "" and cue:
                lines.extend(cue)
                lines.append(line)
                cue = []
            elif cue:
                cue.append(line)
    # Write any remaining cue at end of file
    if cue:
        lines.extend(cue)
        lines.append("\n")  # Ensure proper SRT closure
    with open(srt_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log.info(f"Clamped SRT to END={end_time:.3f}s")


def shift_srt_timestamps(srt_path, delay_ms, log):
    """Shift all SRT timestamps forward by delay_ms milliseconds.

    Useful for accessibility - some viewers prefer captions appearing
    slightly after audio.
    """
    if delay_ms <= 0:
        return  # No delay needed

    import re

    lines = []
    timepat = re.compile(
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})"
    )

    def to_sec(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    def to_srt_time(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    delay_sec = delay_ms / 1000.0

    with open(srt_path, encoding="utf-8") as f:
        for line in f:
            m = timepat.match(line)
            if m:
                start = to_sec(*m.groups()[:4]) + delay_sec
                end = to_sec(*m.groups()[4:]) + delay_sec
                new_line = f"{to_srt_time(start)} --> {to_srt_time(end)}\n"
                lines.append(new_line)
            else:
                lines.append(line)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log.info(f"Shifted SRT timestamps forward by {delay_ms}ms ({delay_sec:.3f}s)")


def mux_subs(av_path, srt_path, output_path, log, job_id=None):
    """Step 4: Mux subtitles into MP4 with mov_text, +faststart."""
    if job_id:
        update_ffmpeg_progress(job_id, 0, "Muxing subtitles...")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        av_path,
        "-i",
        srt_path,
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-map",
        "1",
        # Add unique metadata to subtitle track for detection
        "-metadata:s:s:0",
        f"title={SUBTITLE_TRACK_NAME}",
        "-metadata:s:s:0",
        f"handler_name={SUBTITLE_TRACK_NAME}",
        "-movflags",
        "+faststart",
        output_path,
    ]
    log.info(f"Muxing subs: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
        if job_id:
            update_ffmpeg_progress(job_id, 100, "Muxing complete")
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg mux failed: {e}")
        sys.exit(1)


def atomic_replace(src, dst, log):
    """
    Atomically replace dst with src using os.rename (same filesystem only).
    Abort if dst is missing before replacement. Never recreate or restore.
    """
    log.info(f"Preparing to atomically replace {dst} with {src}")
    dst_path = Path(dst)
    src_path = Path(src)
    if not dst_path.exists():
        log.error(f"Target file {dst} disappeared before replacement. Aborting safely.")
        return
    # Ensure both files are in the same directory
    if dst_path.parent != src_path.parent:
        log.error(f"Temp file {src} is not in the same directory as {dst}. Aborting.")
        return
    try:
        os.rename(src, dst)
        log.debug(f"Replaced {dst} atomically using os.rename.")
    except Exception as e:
        log.error(f"Atomic replacement failed: {e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Embed captions into Channels DVR recordings."
    )
    parser.add_argument("--input", required=True, help="Path to video file (.mpg)")
    parser.add_argument("--srt", required=True, help="Path to SRT captions file")
    parser.add_argument(
        "--model",
        default=os.getenv("WHISPER_MODEL", "medium"),
        help="Whisper model to use",
    )
    parser.add_argument(
        "--skip-caption-generation",
        action="store_true",
        help="Skip caption generation step (assume SRT exists)",
    )
    parser.add_argument(
        "--verbosity",
        default=os.getenv("LOG_VERBOSITY", "NORMAL"),
        help="Log verbosity (MINIMAL, NORMAL, VERBOSE)",
    )
    parser.add_argument(
        "--job-id",
        default=None,
        help="Execution job id for step tracking",
    )
    # Add more options as needed
    args = parser.parse_args()

    mpg_path = args.input
    srt_path = args.srt
    job_id = args.job_id or extract_job_id_from_path(mpg_path)
    log = get_logger("embed_captions", job_id=job_id)
    step_tracker = StepTracker(job_id, log)
    pipeline = get_pipeline_timeline()
    filename = os.path.basename(mpg_path)

    def run_step(step_name, func, input_path=None, output_path=None, misc_label=None):
        step_tracker.start(step_name, input_path=input_path, output_path=output_path)
        pipeline.stage_start(step_name, job_id, filename)
        if misc_label:
            update_misc_progress(job_id, 0.0, misc_label)
        step_start = time.time()
        try:
            result = func()
            step_elapsed = time.time() - step_start
            step_tracker.finish(step_name, status="completed")
            pipeline.stage_end(step_name, job_id)
            log.info(f"STEP TIMING: {step_name} completed in {step_elapsed:.1f}s")
            return result
        except SystemExit:
            step_elapsed = time.time() - step_start
            step_tracker.finish(step_name, status="failed")
            pipeline.stage_end(step_name, job_id)
            log.info(f"STEP TIMING: {step_name} failed after {step_elapsed:.1f}s")
            raise
        except Exception:
            step_elapsed = time.time() - step_start
            step_tracker.finish(step_name, status="failed")
            pipeline.stage_end(step_name, job_id)
            log.info(f"STEP TIMING: {step_name} failed after {step_elapsed:.1f}s")
            raise
        finally:
            if misc_label:
                update_misc_progress(job_id, 100.0, misc_label)

    # Set verbosity if needed (optional)
    # from py_captions_for_channels.logging_config import set_verbosity
    # set_verbosity(args.verbosity)

    # ---- Determine the actual source file to read from ----
    # For reprocessing: if .cc4chan.orig exists, read from it directly.
    # This avoids a multi-GB copy of the original back to .mpg.
    # mpg_path remains the output identity (for Channels DVR, output paths, etc.).
    orig_candidate = mpg_path + ".cc4chan.orig"
    legacy_orig_candidate = mpg_path + ".orig"
    if os.path.exists(orig_candidate):
        input_source = orig_candidate
        log.info("Reprocessing: using .cc4chan.orig as source (skipping restore copy)")
    elif os.path.exists(legacy_orig_candidate):
        input_source = legacy_orig_candidate
        log.info("Reprocessing: using legacy .orig as source (skipping restore copy)")
    else:
        input_source = mpg_path  # First-time processing

    run_step(
        "file_stability",
        lambda: wait_for_file_stability(input_source, log),
        input_path=input_source,
        misc_label="Waiting for file stability",
    )

    # Detect and select audio/subtitle streams based on language preference
    log.debug(
        f"Detecting streams with language preference: "
        f"audio={AUDIO_LANGUAGE}, subtitle={SUBTITLE_LANGUAGE}"
    )
    try:
        # Resolve subtitle language ("same" means use audio language)
        subtitle_lang = (
            AUDIO_LANGUAGE if SUBTITLE_LANGUAGE == "same" else SUBTITLE_LANGUAGE
        )

        stream_selection = select_streams(
            input_source,
            audio_language=AUDIO_LANGUAGE,
            subtitle_language=subtitle_lang,
            fallback=LANGUAGE_FALLBACK,
        )

        log.debug(f"Stream selection: {stream_selection}")
        log.debug(f"  Selected audio: {stream_selection.audio_stream}")
        if stream_selection.subtitle_stream:
            log.debug(f"  Selected subtitle: {stream_selection.subtitle_stream}")
        else:
            log.debug("  No subtitle stream selected")

        # Extract language code for Whisper (convert ISO 639-2/3 to 2-letter code)
        audio_lang_code = stream_selection.audio_stream.language or "en"
        # Whisper prefers 2-letter codes (en, es, fr, etc.)
        selected_language = (
            audio_lang_code[:2] if len(audio_lang_code) > 2 else audio_lang_code
        )

        # Store stream index for later use in encoding
        selected_audio_index = stream_selection.audio_index

        log.debug(
            f"Will transcribe audio stream {selected_audio_index} "
            f"with Whisper language={selected_language}"
        )

    except Exception as e:
        log.error(f"Stream detection failed: {e}")
        if LANGUAGE_FALLBACK == "skip":
            log.error("LANGUAGE_FALLBACK=skip, aborting processing")
            sys.exit(1)
        else:
            log.warning("Falling back to processing all streams (legacy behavior)")
            selected_language = "en"  # Default to English
            selected_audio_index = None  # Process all audio streams

    # Check if source file already has our subtitle track
    # (only meaningful for first-time processing; reprocessing reads the original)
    if input_source == mpg_path and has_our_subtitles(mpg_path, log):
        log.warning(
            f"File already has '{SUBTITLE_TRACK_NAME}' subtitle track! "
            "This indicates the file was already processed. "
            "Processing will continue but may result in duplicate captions."
        )
    else:
        log.debug("No existing subtitle track detected - proceeding with processing")

    # Generate captions with Whisper if needed (BEFORE preserving original)
    if args.skip_caption_generation:
        log.info("Skipping caption generation step (using existing SRT)")
        step_tracker.finish("whisper", status="skipped")
        pipeline.stage_start("whisper", job_id, filename)
        pipeline.stage_end("whisper", job_id)
    else:
        log.debug(f"Preparing Faster-Whisper model: {args.model}")
        step_tracker.start("whisper", input_path=input_source, output_path=srt_path)

        def _run_whisper():
            def format_srt_timestamp(seconds):
                """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                secs = int(seconds % 60)
                millis = int((seconds - int(seconds)) * 1000)
                return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

            try:
                from faster_whisper import WhisperModel
                from py_captions_for_channels.config import WHISPER_DEVICE

                # Determine device based on configuration
                if WHISPER_DEVICE == "none":
                    device = "cpu"
                    compute_type = "int8"  # Use int8 for CPU efficiency
                    log.debug(
                        f"Loading Faster-Whisper model: {args.model} "
                        f"(device={device}, compute_type={compute_type}) - "
                        f"CPU forced by config"
                    )
                    model = WhisperModel(
                        args.model, device=device, compute_type=compute_type
                    )
                    log.info("Faster-Whisper model loaded with CPU (GPU disabled)")
                elif WHISPER_DEVICE == "nvidia":
                    # Force NVIDIA GPU even if detection fails
                    device = "cuda"
                    compute_type = "float16"
                    log.debug(
                        f"Loading Faster-Whisper model: {args.model} "
                        f"(device={device}, compute_type={compute_type}) - "
                        f"NVIDIA GPU forced"
                    )
                    model = WhisperModel(
                        args.model, device=device, compute_type=compute_type
                    )
                    log.info("Faster-Whisper model loaded with NVIDIA GPU (forced)")
                elif WHISPER_DEVICE in ["amd", "intel"]:
                    # AMD/Intel GPU support - try GPU first, fallback to auto behavior
                    device = "cuda"
                    compute_type = "float16"
                    log.debug(
                        f"Loading Faster-Whisper model: {args.model} "
                        f"(device={device}, compute_type={compute_type}) - "
                        f"{WHISPER_DEVICE.upper()} GPU requested "
                        f"(using CUDA, ROCm/OpenVINO support coming soon)"
                    )
                    try:
                        model = WhisperModel(
                            args.model, device=device, compute_type=compute_type
                        )
                        log.info(
                            f"{WHISPER_DEVICE.upper()} GPU mode activated "
                            f"(CUDA fallback)"
                        )
                    except Exception as e:
                        # If GPU fails, fall back to auto detection
                        log.warning(
                            f"{WHISPER_DEVICE.upper()} GPU not supported, "
                            f"falling back to auto detection: {e}"
                        )
                        device = "cuda"
                        compute_type = "float16"
                        try:
                            model = WhisperModel(
                                args.model, device=device, compute_type=compute_type
                            )
                            log.info(
                                "Faster-Whisper model loaded with GPU (auto-detected)"
                            )
                        except Exception:
                            device = "cpu"
                            compute_type = "int8"
                            model = WhisperModel(
                                args.model, device=device, compute_type=compute_type
                            )
                            log.info(
                                "Faster-Whisper model loaded with CPU (GPU fallback)"
                            )
                else:  # auto mode
                    # Initialize model with GPU if available, fallback to CPU
                    device = "cuda"
                    compute_type = "float16"  # Use float16 for better GPU performance

                    log.debug(
                        f"Loading Faster-Whisper model: {args.model} "
                        f"(device={device}, compute_type={compute_type}) - "
                        f"auto-detect mode"
                    )

                    try:
                        model = WhisperModel(
                            args.model, device=device, compute_type=compute_type
                        )
                        log.debug("Faster-Whisper model loaded successfully with GPU")
                    except Exception as e:
                        log.warning(
                            f"Failed to load model with GPU: {e}, falling back to CPU"
                        )
                        device = "cpu"
                        compute_type = "int8"  # Use int8 for CPU efficiency
                        model = WhisperModel(
                            args.model, device=device, compute_type=compute_type
                        )
                        log.info("Faster-Whisper model loaded with CPU fallback")

                # Transcribe with progress tracking
                log.debug(f"Transcribing audio from: {input_source}")

                # Get video duration for progress calculation
                video_duration = probe_duration(input_source, log)
                log.debug(
                    f"Video duration: {video_duration:.1f}s for progress tracking"
                )

                # Determine Whisper parameters based on OPTIMIZATION_MODE
                channel_number = extract_channel_number(mpg_path)
                print(f"[OPTIMIZATION] Channel detected: {channel_number}", flush=True)
                if OPTIMIZATION_MODE == "automatic":
                    whisper_params = get_whisper_parameters(
                        input_source, channel_number
                    )
                    beam_size = whisper_params.get("beam_size")
                    vad_ms = whisper_params.get("vad_parameters", {}).get(
                        "min_silence_duration_ms"
                    )
                    log.debug(
                        f"Using automatic Whisper parameters "
                        f"(channel={channel_number}): "
                        f"beam_size={beam_size}, vad_min_silence_ms={vad_ms}"
                    )
                    print(
                        f"[OPTIMIZATION] Using automatic Whisper: "
                        f"beam_size={beam_size}, vad_min_silence_ms={vad_ms}",
                        flush=True,
                    )
                else:
                    # Standard mode: use hardcoded parameters (proven, reliable)
                    # Language determined by stream selection (passed via closure)
                    whisper_params = {
                        "language": selected_language,
                        "beam_size": 5,
                        "vad_filter": True,
                        "vad_parameters": {"min_silence_duration_ms": 500},
                    }
                    log.info(
                        f"Using standard Whisper parameters "
                        f"(OPTIMIZATION_MODE=standard, language={selected_language})"
                    )

                # Check if file can be safely decoded - if not, extract audio first
                wav_path = None
                use_wav_path = input_source  # Default to direct transcription

                if not validate_audio_decodability(input_source, log):
                    log.warning(
                        "File contains corrupted/problematic frames - "
                        "extracting audio to WAV first to avoid segfault"
                    )
                    wav_path = f"{mpg_path}.cc4chan.temp.wav"
                    try:
                        # Map specific audio stream for language-aware processing
                        audio_map = (
                            ["-map", f"0:a:{selected_audio_index}"]
                            if selected_audio_index is not None
                            else []
                        )
                        extract_cmd = (
                            [
                                "ffmpeg",
                                "-y",
                                "-err_detect",
                                "ignore_err",  # Ignore decoding errors
                                "-i",
                                input_source,
                            ]
                            + audio_map
                            + [
                                "-vn",  # No video
                                "-acodec",
                                "pcm_s16le",  # PCM audio
                                "-ar",
                                "16000",  # 16kHz sample rate (Whisper standard)
                                "-ac",
                                "1",  # Mono
                                wav_path,
                            ]
                        )
                        log.info(f"Extracting audio: {' '.join(extract_cmd)}")
                        result = subprocess.run(
                            extract_cmd,
                            check=False,  # Don't raise on non-zero exit
                            capture_output=True,
                            text=True,
                        )

                        if result.returncode == 0 and os.path.exists(wav_path):
                            log.info(f"Audio extracted successfully to {wav_path}")
                            use_wav_path = wav_path  # Use WAV for transcription
                        else:
                            log.error(
                                f"Audio extraction failed (exit {result.returncode}): "
                                f"{result.stderr[:500]}"
                            )
                            raise Exception("Proactive WAV extraction failed")

                    except Exception as e:
                        log.error(f"Failed to extract audio proactively: {e}")
                        # Clean up partial WAV
                        if wav_path and os.path.exists(wav_path):
                            try:
                                os.remove(wav_path)
                            except Exception:
                                pass
                        raise

                # Start the pipeline stage right before actual transcription
                log.debug("Starting transcription...")
                pipeline.stage_start("whisper", job_id, filename)

                # Report initial progress immediately so UI shows status
                if args.job_id:
                    update_whisper_progress(args.job_id, 0, "Transcription starting...")

                # Try GPU transcription first, fall back to CPU if GPU libraries fail
                transcription_successful = False
                try:
                    segments_generator, info = model.transcribe(
                        use_wav_path, **whisper_params
                    )
                    transcription_successful = True
                except Exception as e:
                    # GPU transcription failed
                    # (e.g., CUDA library missing or codec error)
                    if device == "cuda":
                        log.error(f"Faster-Whisper transcription failed: {e}")
                        log.warning("Retrying with CPU...")
                        device = "cpu"
                        compute_type = "int8"
                        model = WhisperModel(
                            args.model, device=device, compute_type=compute_type
                        )
                        log.info("Faster-Whisper model reloaded with CPU")
                        try:
                            # Use same path (WAV if we extracted it, mpg otherwise)
                            segments_generator, info = model.transcribe(
                                use_wav_path, **whisper_params
                            )
                            transcription_successful = True
                        except Exception as cpu_error:
                            log.error(
                                "Faster-Whisper transcription failed on CPU: %s",
                                cpu_error,
                            )
                            # If we haven't tried WAV extraction yet, try it now
                            if wav_path is None:
                                error_str = str(cpu_error)
                                if (
                                    "avcodec" in error_str.lower()
                                    or "16976906" in error_str
                                    or "invalid" in error_str.lower()
                                ):
                                    log.warning(
                                        "Codec error detected. Attempting "
                                        "workaround: extracting audio to WAV..."
                                    )
                                    wav_path = f"{mpg_path}.cc4chan.temp.wav"
                                    try:
                                        # Map specific audio stream
                                        # for language-aware processing
                                        audio_map = (
                                            ["-map", f"0:a:{selected_audio_index}"]
                                            if selected_audio_index is not None
                                            else []
                                        )
                                        extract_cmd = (
                                            [
                                                "ffmpeg",
                                                "-y",
                                                "-err_detect",
                                                "ignore_err",
                                                "-i",
                                                input_source,
                                            ]
                                            + audio_map
                                            + [
                                                "-vn",  # No video
                                                "-acodec",
                                                "pcm_s16le",  # PCM audio
                                                "-ar",
                                                "16000",  # 16kHz sample rate
                                                "-ac",
                                                "1",  # Mono
                                                wav_path,
                                            ]
                                        )
                                        log.info(
                                            f"Extracting audio: "
                                            f"{' '.join(extract_cmd)}"
                                        )
                                        subprocess.run(
                                            extract_cmd,
                                            check=True,
                                            capture_output=True,
                                        )
                                        log.info(
                                            "Audio extracted successfully to "
                                            f"{wav_path}"
                                        )

                                        # Try transcribing the WAV file
                                        segments_generator, info = model.transcribe(
                                            wav_path, **whisper_params
                                        )
                                        transcription_successful = True
                                        log.info("Transcription successful using WAV")

                                    except Exception as wav_error:
                                        log.error(
                                            "WAV extraction workaround failed: %s",
                                            wav_error,
                                        )
                                        # Clean up partial WAV if it exists
                                        try:
                                            if wav_path and os.path.exists(wav_path):
                                                os.remove(wav_path)
                                                wav_path = None
                                        except Exception:
                                            pass
                                        raise cpu_error  # Re-raise original error
                                else:
                                    raise  # Not a codec error, re-raise
                            else:
                                # Already tried WAV, nothing more we can do
                                raise
                    else:
                        raise  # GPU failed but not CUDA device, re-raise

                if not transcription_successful:
                    raise RuntimeError("Transcription failed on all attempts")

                log.debug(
                    f"Detected language: {info.language} "
                    f"(probability: {info.language_probability:.2f})"
                )

                # Write SRT file with real-time progress tracking
                srt_lines = []
                last_progress_report = 0
                segment_count = 0

                for i, segment in enumerate(segments_generator, start=1):
                    segment_count = i
                    # Format timestamps for SRT
                    start_time = format_srt_timestamp(segment.start)
                    end_time = format_srt_timestamp(segment.end)

                    # Add segment to SRT
                    srt_lines.append(f"{i}\n")
                    srt_lines.append(f"{start_time} --> {end_time}\n")
                    srt_lines.append(f"{segment.text.strip()}\n")
                    srt_lines.append("\n")

                    # Update progress based on segment end time
                    if video_duration > 0:
                        progress = min(95, int((segment.end / video_duration) * 100))
                        # Report every 5% or when significant progress is made
                        if progress >= last_progress_report + 5 or (
                            progress - last_progress_report >= 1 and time.time() % 2 < 1
                        ):
                            update_whisper_progress(
                                args.job_id,
                                progress,
                                f"Transcribing: {segment.end:.0f}/"
                                f"{video_duration:.0f}s "
                                f"({segment_count} segments)",
                            )
                            last_progress_report = progress
                            log.debug(
                                f"Whisper progress: {progress}% "
                                f"({segment.end:.1f}/{video_duration:.1f}s)"
                            )

                # Final progress update
                update_whisper_progress(
                    args.job_id, 95, f"Transcription complete: {segment_count} segments"
                )
                log.info(f"Transcribed {segment_count} segments total")

                # Write SRT file atomically
                srt_tmp = srt_path + ".cc4chan.tmp"
                with open(srt_tmp, "w", encoding="utf-8") as f:
                    f.writelines(srt_lines)
                os.replace(srt_tmp, srt_path)

                log.info(
                    f"Faster-Whisper completed successfully, generated: {srt_path}"
                )

                # Clean up temporary WAV file if it was created
                if wav_path and os.path.exists(wav_path):
                    try:
                        os.remove(wav_path)
                        log.info(f"Cleaned up temporary WAV file: {wav_path}")
                    except Exception as e:
                        log.warning(f"Failed to clean up WAV file: {e}")

                # End pipeline stage after successful transcription
                pipeline.stage_end("whisper", job_id)

            except ImportError as e:
                log.error(
                    f"faster-whisper not installed: {e}. "
                    f"Install with: pip install faster-whisper"
                )
                pipeline.stage_end("whisper", job_id)
                sys.exit(1)
            except Exception as e:
                log.error(f"Faster-Whisper transcription failed: {e}")
                pipeline.stage_end("whisper", job_id)
                sys.exit(1)

        try:
            _run_whisper()
            step_tracker.finish("whisper", status="completed")
        except SystemExit:
            step_tracker.finish("whisper", status="failed")
            raise
        except Exception:
            step_tracker.finish("whisper", status="failed")
            raise

    # Now preserve the original AFTER caption generation
    run_step(
        "file_copy",
        lambda: preserve_original(mpg_path, log),
        input_path=mpg_path,
        output_path=mpg_path + ".cc4chan.orig",
        misc_label="Preserving original",
    )

    if not srt_exists_and_valid(srt_path):
        log.error("Missing or invalid SRT file.")
        sys.exit(1)
    orig_path = mpg_path + ".cc4chan.orig"
    temp_av = mpg_path + ".cc4chan.av.mp4"
    temp_muxed = mpg_path + ".cc4chan.muxed.mp4"
    # Step 1: Encode A/V only (behavior controlled by PRESERVE_ALL_AUDIO_TRACKS)
    run_step(
        "ffmpeg_encode",
        lambda: encode_av_only(
            orig_path,
            temp_av,
            log,
            args.job_id,
            source_path=mpg_path,
            audio_stream_index=selected_audio_index,
        ),
        input_path=orig_path,
        output_path=temp_av,
    )
    # Step 2: Probe encoded A/V duration
    end_time = run_step(
        "probe_av",
        lambda: probe_av_end(temp_av, log),
        input_path=temp_av,
        misc_label="Probing media",
    )
    # Step 3: Shift SRT timestamps (caption delay)
    if CAPTION_DELAY_MS > 0:
        run_step(
            "shift_srt",
            lambda: shift_srt_timestamps(srt_path, CAPTION_DELAY_MS, log),
            input_path=srt_path,
            misc_label="Adjusting captions",
        )
    # Step 4: Clamp SRT
    run_step(
        "clamp_srt",
        lambda: clamp_srt_to_end(srt_path, end_time, log),
        input_path=srt_path,
        misc_label="Finalizing captions",
    )
    # Step 5: Mux subtitles
    run_step(
        "ffmpeg_mux",
        lambda: mux_subs(temp_av, srt_path, temp_muxed, log, args.job_id),
        input_path=temp_av,
        output_path=temp_muxed,
    )
    # Final verification for Android compatibility
    v_dur, a_dur, s_dur = run_step(
        "verify_mux",
        lambda: probe_muxed_durations(temp_muxed, log),
        input_path=temp_muxed,
        misc_label="Verifying output",
    )
    max_av = max(v_dur, a_dur)
    if s_dur <= max_av + 0.050:
        run_step(
            "replace_output",
            lambda: atomic_replace(temp_muxed, mpg_path, log),
            input_path=temp_muxed,
            output_path=mpg_path,
            misc_label="Replacing output",
        )
        # Clean up temp files
        run_step(
            "cleanup",
            lambda: [os.remove(f) for f in [temp_av] if os.path.exists(f)],
            misc_label="Cleaning up",
        )
        pipeline.job_complete(job_id)
        log.debug("Caption embedding complete.")
    else:
        pipeline.job_complete(job_id)
        log.error(
            f"Verification failed: subtitle_duration={s_dur:.3f}s > "
            f"max_av+0.050={max_av+0.050:.3f}s. Not replacing target file."
        )
        log.error(f"Temp files kept for inspection: {temp_av}, {temp_muxed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
