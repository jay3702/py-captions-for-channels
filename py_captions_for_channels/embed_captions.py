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
    orig_path = mpg_path + ".orig"
    tmp_path = orig_path + ".tmp"
    needs_refresh = False
    if not os.path.exists(orig_path):
        log.info(f"Preserving original: {mpg_path} -> {orig_path}")
        shutil.copy2(mpg_path, tmp_path)
        os.replace(tmp_path, orig_path)
        return
    # Check for staleness
    orig_size = os.path.getsize(orig_path)
    mpg_size = os.path.getsize(mpg_path)
    if orig_size < 0.95 * mpg_size:
        log.warning(f".orig is stale (size {orig_size} < 95% of {mpg_size})")
        needs_refresh = True
    else:
        orig_dur = probe_duration(orig_path, log)
        mpg_dur = probe_duration(mpg_path, log)
        if orig_dur < 0.95 * mpg_dur:
            log.warning(
                f".orig is stale (duration {orig_dur:.2f}s < 95% of {mpg_dur:.2f}s)"
            )
            needs_refresh = True
    if needs_refresh:
        log.info(f"Refreshing .orig atomically: {mpg_path} -> {orig_path}")
        shutil.copy2(mpg_path, tmp_path)
        os.replace(tmp_path, orig_path)
    else:
        log.info(".orig already exists and is up to date.")


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


def encode_av_only(mpg_orig, temp_av, log):
    """Step 1: Encode video (NVENC if available, else CPU), copy audio, no subs."""
    # Detect if content is VFR (Chrome capture) or CFR (broadcast TV)
    is_vfr = detect_variable_frame_rate(mpg_orig, log)

    # Build base command for NVENC
    cmd_nvenc = [
        "ffmpeg",
        "-y",
        "-i",
        mpg_orig,
        "-c:v",
        "h264_nvenc",
        "-preset",
        "fast",
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
        subprocess.check_call(cmd_nvenc)
        return
    except subprocess.CalledProcessError:
        log.warning("NVENC failed, falling back to CPU (libx264)")

    # Fallback to CPU with same VFR handling
    cmd_cpu = [
        "ffmpeg",
        "-y",
        "-i",
        mpg_orig,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
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
        subprocess.check_call(cmd_cpu)
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg failed: {e}")
        sys.exit(1)


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


def mux_subs(av_path, srt_path, output_path, log):
    """Step 4: Mux subtitles into MP4 with mov_text, +faststart."""
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
        "-movflags",
        "+faststart",
        output_path,
    ]
    log.info(f"Muxing subs: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
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

    def run_step(step_name, func, input_path=None, output_path=None, misc_label=None):
        step_tracker.start(step_name, input_path=input_path, output_path=output_path)
        if misc_label:
            update_misc_progress(job_id, 0.0, misc_label)
        try:
            result = func()
            step_tracker.finish(step_name, status="completed")
            return result
        except SystemExit:
            step_tracker.finish(step_name, status="failed")
            raise
        except Exception:
            step_tracker.finish(step_name, status="failed")
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

    # Generate captions with Whisper if needed (BEFORE preserving original)
    if args.skip_caption_generation:
        log.info("Skipping caption generation step (using existing SRT)")
        step_tracker.finish("whisper", status="skipped")
    else:
        log.info(f"Generating captions with Whisper model: {args.model}")
        whisper_cmd = [
            "whisper",
            mpg_path,
            "--model",
            args.model,
            "--output_format",
            "srt",
            "--output_dir",
            str(Path(srt_path).parent),
            "--language",
            "en",
        ]
        log.info(f"Running Whisper: {' '.join(whisper_cmd)}")

        def _run_whisper():
            try:
                subprocess.check_call(whisper_cmd)
                log.info(f"Whisper completed successfully, generated: {srt_path}")
            except subprocess.CalledProcessError as e:
                log.error(f"Whisper failed: {e}")
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
        lambda: encode_av_only(orig_path, temp_av, log),
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
        lambda: mux_subs(temp_av, srt_path, temp_muxed, log),
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
        log.info("Caption embedding complete.")
    else:
        log.error(
            f"Verification failed: subtitle_duration={s_dur:.3f}s > "
            f"max_av+0.050={max_av+0.050:.3f}s. Not replacing target file."
        )
        log.error(f"Temp files kept for inspection: {temp_av}, {temp_muxed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
