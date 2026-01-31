#!/usr/bin/env python3
"""
embed_captions.py
Safely replace embedded/delayed captions in Channels DVR recordings with externally generated SRT captions.
Preserves Channels’ database identity and Android compatibility.
"""
import os
import sys
import time
import shutil
import subprocess
import logging
from pathlib import Path

# --- CONFIGURABLE ---
STABLE_INTERVAL = 10  # seconds between file size checks
STABLE_CONSECUTIVE = 3  # number of consecutive stable checks required
STABLE_TIMEOUT = 300  # max seconds to wait for stability (5 minutes)
LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()

logging.basicConfig(level=LOGLEVEL, format="[%(asctime)s] %(levelname)s: %(message)s")
log = logging.getLogger("embed_captions")

def wait_for_file_stability(
    path,
    interval=STABLE_INTERVAL,
    consecutive=STABLE_CONSECUTIVE,
    timeout=STABLE_TIMEOUT,
):
    """
    Wait until file size is stable for N consecutive checks, or abort after timeout.
    Logs size progression for debugging.
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
                f"File did not stabilize after {timeout} seconds. Last size: {size}. Aborting."
            )
            sys.exit(1)

def preserve_original(mpg_path):
    orig_path = mpg_path + ".orig"
    if not os.path.exists(orig_path):
        log.info(f"Preserving original: {mpg_path} -> {orig_path}")
        shutil.copy2(mpg_path, orig_path)
    else:
        orig_size = os.path.getsize(orig_path)
        mpg_size = os.path.getsize(mpg_path)
        if orig_size < mpg_size:
            log.warning(f"Refreshing stale .orig: {mpg_path} -> {orig_path}")
            shutil.copy2(mpg_path, orig_path)
        else:
            log.info(".orig already exists and is up to date.")

def srt_exists_and_valid(srt_path):
    return os.path.exists(srt_path) and os.path.getsize(srt_path) > 0

def probe_media_end_time(mpg_path):
    """Return max end time (seconds) of video/audio streams using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:a",
        "-show_entries", "stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", mpg_path
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
                end = h*3600 + m_*60 + s + ms/1000.0
                if end > last_end:
                    last_end = end
    return last_end

def validate_and_trim_srt(srt_path, max_end_time):
    """Trim last subtitle if it exceeds max_end_time."""
    import re
    lines = []
    timepat = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})")
    with open(srt_path, encoding="utf-8") as f:
        for line in f:
            m = timepat.match(line)
            if m:
                start, end = m.groups()
                h, m_, s, ms = map(int, re.split('[:,]', end))
                end_sec = h*3600 + m_*60 + s + ms/1000.0
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

def remux_with_ffmpeg(mpg_orig, srt_path, output_path):
    cmd = [
        "ffmpeg", "-y", "-i", mpg_orig, "-i", srt_path,
        "-map", "0", "-map", "1", "-c", "copy", "-scodec", "mov_text", output_path
    ]
    log.info(f"Running ffmpeg: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg failed: {e}")
        sys.exit(1)

def atomic_replace(src, dst):
    log.info(f"Replacing {dst} atomically.")
    tmp = dst + ".tmp"
    shutil.move(src, tmp)
    os.replace(tmp, dst)

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} /path/to/video.mpg /path/to/captions.srt")
        sys.exit(2)
    mpg_path = sys.argv[1]
    srt_path = sys.argv[2]
    wait_for_file_stability(mpg_path)
    preserve_original(mpg_path)
    if not srt_exists_and_valid(srt_path):
        log.error("Missing or invalid SRT file.")
        sys.exit(1)
    media_end = probe_media_end_time(mpg_path + ".orig")
    srt_end = probe_srt_end_time(srt_path)
    if srt_end > media_end:
        validate_and_trim_srt(srt_path, media_end)
    output_path = mpg_path + ".new"
    remux_with_ffmpeg(mpg_path + ".orig", srt_path, output_path)
    atomic_replace(output_path, mpg_path)
    log.info("Caption embedding complete.")

if __name__ == "__main__":
    main()
