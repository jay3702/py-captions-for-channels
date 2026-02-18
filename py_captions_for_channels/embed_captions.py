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

from pathlib import Path
from py_captions_for_channels.logging.structured_logger import get_logger
from py_captions_for_channels.database import get_db
from py_captions_for_channels.progress_tracker import get_progress_tracker
from py_captions_for_channels.services.execution_service import ExecutionService
from py_captions_for_channels.config import WHISPER_MODE
from py_captions_for_channels.encoding_profiles import (
    get_whisper_parameters,
    get_ffmpeg_parameters,
)
from py_captions_for_channels.system_monitor import get_pipeline_timeline

# Unique identifier for our subtitle tracks
SUBTITLE_TRACK_NAME = "py-captions-for-channels"


def extract_channel_number(video_path):
    """
    Attempt to extract channel number from the recording file path.

    Looks for patterns like:
    - Directory names: "4.1 KRON", "11.3 KNTV", "6030 CNN"
    - Path components with channel info

    Returns:
        str or None: Channel number (e.g., "4.1", "6030") or None if not found
    """
    import re

    # Normalize path separators to forward slashes for consistent regex
    path_str = str(video_path).replace("\\", "/")

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
        log.info(f"Check at {elapsed}s: size={size}")
        if size is not None and size == last_size:
            stable_count += 1
            log.info(f"Stable count: {stable_count}/{consecutive}")
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
    orig_path = mpg_path + ".orig"
    tmp_path = orig_path + ".tmp"

    if not os.path.exists(orig_path):
        log.info(f"Preserving original (first time): {mpg_path} -> {orig_path}")
        shutil.copy2(mpg_path, tmp_path)
        os.replace(tmp_path, orig_path)
    else:
        log.info(f".orig already exists and will not be modified: {orig_path}")


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
        log.info(f"Found {len(streams)} subtitle stream(s) in {video_path}")
        for i, s in enumerate(streams):
            tags = s.get("tags", {})
            title = tags.get("title", tags.get("handler_name", "Unknown"))
            log.info(f"  Stream {i}: {s.get('codec_name')} - {title}")
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


def encode_av_only(mpg_orig, temp_av, log, job_id=None):
    """Step 1: Encode video (NVENC if available, else CPU), copy audio, no subs."""
    # Get video duration for progress tracking
    video_duration = probe_duration(mpg_orig, log)

    # Detect if content is VFR (Chrome capture) or CFR (broadcast TV)
    is_vfr = detect_variable_frame_rate(mpg_orig, log)

    # Determine encoder presets based on WHISPER_MODE
    channel_number = extract_channel_number(mpg_orig)
    if WHISPER_MODE == "automatic":
        ffmpeg_params = get_ffmpeg_parameters(mpg_orig, channel_number)
        nvenc_preset = ffmpeg_params["nvenc_preset"]
        x264_preset = ffmpeg_params["x264_preset"]
        log.info(
            f"Using automatic ffmpeg presets (channel={channel_number}): "
            f"nvenc={nvenc_preset}, x264={x264_preset}"
        )
    else:
        # Standard mode: use hardcoded presets (current default)
        nvenc_preset = "fast"
        x264_preset = "fast"
        log.info("Using standard ffmpeg presets (WHISPER_MODE=standard)")

    # Build base command for NVENC
    cmd_nvenc = [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",  # Enable progress reporting to stderr
        "-i",
        mpg_orig,
        "-c:v",
        "h264_nvenc",
        "-preset",
        nvenc_preset,
    ]

    # Add VFR handling if needed (critical for Chrome-captured content)
    if is_vfr:
        cmd_nvenc.extend(["-vsync", "vfr"])

    cmd_nvenc.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-analyzeduration",
            "2147483647",
            "-probesize",
            "2147483647",
            "-map",
            "0:v",
            "-map",
            "0:a?",
            temp_av,
        ]
    )
    log.info(f"Trying NVENC encode: {' '.join(cmd_nvenc)}")
    try:
        _run_ffmpeg_with_progress(
            cmd_nvenc, video_duration, "Encoding (GPU)", log, job_id
        )
        return
    except subprocess.CalledProcessError:
        log.warning("NVENC failed, falling back to CPU (libx264)")

    # Fallback to CPU with same VFR handling
    cmd_cpu = [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",  # Enable progress reporting to stderr
        "-i",
        mpg_orig,
        "-c:v",
        "libx264",
        "-preset",
        x264_preset,
    ]

    if is_vfr:
        cmd_cpu.extend(["-vsync", "vfr"])

    cmd_cpu.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-analyzeduration",
            "2147483647",
            "-probesize",
            "2147483647",
            "-map",
            "0:v",
            "-map",
            "0:a?",
            temp_av,
        ]
    )
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
        log.info(f"Replaced {dst} atomically using os.rename.")
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
        try:
            result = func()
            step_tracker.finish(step_name, status="completed")
            pipeline.stage_end(step_name, job_id)
            return result
        except SystemExit:
            step_tracker.finish(step_name, status="failed")
            pipeline.stage_end(step_name, job_id)
            raise
        except Exception:
            step_tracker.finish(step_name, status="failed")
            pipeline.stage_end(step_name, job_id)
            raise
        finally:
            if misc_label:
                update_misc_progress(job_id, 100.0, misc_label)

    # Set verbosity if needed (optional)
    # from py_captions_for_channels.logging_config import set_verbosity
    # set_verbosity(args.verbosity)

    run_step(
        "wait_stable",
        lambda: wait_for_file_stability(mpg_path, log),
        input_path=mpg_path,
        misc_label="Waiting for file stability",
    )

    # Check if file already has our subtitle track
    if has_our_subtitles(mpg_path, log):
        log.warning(
            f"File already has '{SUBTITLE_TRACK_NAME}' subtitle track! "
            "This indicates the file was already processed. "
            "Processing will continue but may result in duplicate captions."
        )
    else:
        log.info("No existing subtitle track detected - proceeding with processing")

    # Generate captions with Whisper if needed (BEFORE preserving original)
    if args.skip_caption_generation:
        log.info("Skipping caption generation step (using existing SRT)")
        step_tracker.finish("whisper", status="skipped")
        pipeline.stage_start("whisper", job_id, filename)
        pipeline.stage_end("whisper", job_id)
    else:
        log.info(f"Generating captions with Faster-Whisper model: {args.model}")

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

                # Initialize model with GPU if available
                device = "cuda"
                compute_type = "float16"  # Use float16 for better GPU performance

                log.info(
                    f"Loading Faster-Whisper model: {args.model} "
                    f"(device={device}, compute_type={compute_type})"
                )

                try:
                    model = WhisperModel(
                        args.model, device=device, compute_type=compute_type
                    )
                    log.info("Faster-Whisper model loaded successfully with GPU")
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
                log.info(f"Transcribing audio from: {mpg_path}")

                # Get video duration for progress calculation
                video_duration = probe_duration(mpg_path, log)
                log.info(f"Video duration: {video_duration:.1f}s for progress tracking")

                # Determine Whisper parameters based on WHISPER_MODE
                channel_number = extract_channel_number(mpg_path)
                if WHISPER_MODE == "automatic":
                    whisper_params = get_whisper_parameters(mpg_path, channel_number)
                    beam_size = whisper_params.get("beam_size")
                    vad_ms = whisper_params.get("vad_parameters", {}).get(
                        "min_silence_duration_ms"
                    )
                    log.info(
                        f"Using automatic Whisper parameters "
                        f"(channel={channel_number}): "
                        f"beam_size={beam_size}, vad_min_silence_ms={vad_ms}"
                    )
                else:
                    # Standard mode: use hardcoded parameters (proven, reliable)
                    whisper_params = {
                        "language": "en",
                        "beam_size": 5,
                        "vad_filter": True,
                        "vad_parameters": {"min_silence_duration_ms": 500},
                    }
                    log.info(
                        "Using standard Whisper parameters (WHISPER_MODE=standard)"
                    )

                # Try GPU transcription first, fall back to CPU if GPU libraries fail
                transcription_successful = False
                try:
                    segments_generator, info = model.transcribe(
                        mpg_path, **whisper_params
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
                            segments_generator, info = model.transcribe(
                                mpg_path, **whisper_params
                            )
                            transcription_successful = True
                        except Exception as cpu_error:
                            log.error(
                                "Faster-Whisper transcription failed: %s",
                                cpu_error,
                            )
                            # Check if this is a codec error
                            error_str = str(cpu_error)
                            if (
                                "avcodec" in error_str.lower()
                                or "16976906" in error_str
                            ):
                                log.warning(
                                    "Codec error detected. Attempting "
                                    "workaround: extracting audio to WAV..."
                                )
                                # Try extracting audio as WAV first
                                wav_path = f"{mpg_path}.temp.wav"
                                try:
                                    extract_cmd = [
                                        "ffmpeg",
                                        "-y",
                                        "-i",
                                        mpg_path,
                                        "-vn",  # No video
                                        "-acodec",
                                        "pcm_s16le",  # PCM audio
                                        "-ar",
                                        "16000",  # 16kHz sample rate (Whisper standard)
                                        "-ac",
                                        "1",  # Mono
                                        wav_path,
                                    ]
                                    log.info(
                                        f"Extracting audio: {' '.join(extract_cmd)}"
                                    )
                                    subprocess.run(
                                        extract_cmd, check=True, capture_output=True
                                    )
                                    log.info(
                                        f"Audio extracted successfully to {wav_path}"
                                    )

                                    # Try transcribing the WAV file
                                    segments_generator, info = model.transcribe(
                                        wav_path, **whisper_params
                                    )
                                    transcription_successful = True
                                    log.info(
                                        "Transcription successful using WAV workaround"
                                    )

                                    # Clean up WAV file after success
                                    try:
                                        os.remove(wav_path)
                                        log.info(
                                            "Cleaned up temporary WAV file: %s",
                                            wav_path,
                                        )
                                    except Exception:
                                        pass
                                except Exception as wav_error:
                                    log.error(
                                        "WAV extraction workaround failed: %s",
                                        wav_error,
                                    )
                                    # Clean up partial WAV if it exists
                                    try:
                                        if os.path.exists(wav_path):
                                            os.remove(wav_path)
                                    except Exception:
                                        pass
                                    raise cpu_error  # Re-raise original error
                            else:
                                raise cpu_error
                    else:
                        raise  # CPU transcription failed, re-raise

                if not transcription_successful:
                    raise RuntimeError("Transcription failed on all attempts")

                log.info(
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
                            log.info(
                                f"Whisper progress: {progress}% "
                                f"({segment.end:.1f}/{video_duration:.1f}s)"
                            )

                # Final progress update
                update_whisper_progress(
                    args.job_id, 95, f"Transcription complete: {segment_count} segments"
                )
                log.info(f"Transcribed {segment_count} segments total")

                # Write SRT file atomically
                srt_tmp = srt_path + ".tmp"
                with open(srt_tmp, "w", encoding="utf-8") as f:
                    f.writelines(srt_lines)
                os.replace(srt_tmp, srt_path)

                log.info(
                    f"Faster-Whisper completed successfully, generated: {srt_path}"
                )

            except ImportError as e:
                log.error(
                    f"faster-whisper not installed: {e}. "
                    f"Install with: pip install faster-whisper"
                )
                sys.exit(1)
            except Exception as e:
                log.error(f"Faster-Whisper transcription failed: {e}")
                sys.exit(1)

        run_step(
            "whisper",
            _run_whisper,
            input_path=mpg_path,
            output_path=srt_path,
        )

    # Now preserve the original AFTER caption generation
    run_step(
        "file_copy",
        lambda: preserve_original(mpg_path, log),
        input_path=mpg_path,
        output_path=mpg_path + ".orig",
        misc_label="Preserving original",
    )

    if not srt_exists_and_valid(srt_path):
        log.error("Missing or invalid SRT file.")
        sys.exit(1)
    orig_path = mpg_path + ".orig"
    temp_av = mpg_path + ".av.mp4"
    temp_muxed = mpg_path + ".muxed.mp4"
    # Step 1: Encode A/V only
    run_step(
        "ffmpeg_encode",
        lambda: encode_av_only(orig_path, temp_av, log, args.job_id),
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
    # Step 3: Clamp SRT
    run_step(
        "clamp_srt",
        lambda: clamp_srt_to_end(srt_path, end_time, log),
        input_path=srt_path,
    )
    # Step 4: Mux subtitles
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
        log.info("Caption embedding complete.")
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
