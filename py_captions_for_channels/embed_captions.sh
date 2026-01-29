#!/bin/bash
# Embed captions into MPG for Channels DVR compatibility (subtitle stream, not burn-in)
#
# Usage: embed_captions.sh /path/to/video.mpg
#
# Environment variables:
#   KEEP_ORIGINAL: true (default) to archive original as .mpg.orig, false to delete
#   WHISPER_MODEL: whisper model size (default: medium)
#   WHISPER_MODEL_DIR: cache dir for whisper models (default: /app/data/whisper)
#   WHISPER_ARGS: extra args to pass to whisper
#   SKIP_CAPTION_GENERATION: true to skip whisper step
#
# Optional overrides:
#   FFMPEG: path to ffmpeg (default: ffmpeg)
#   FFPROBE: path to ffprobe (default: ffprobe)
#   CLAMP_EPS_MS: epsilon margin in ms when clamping (default: 1)
#
# This script:
# 1. Generates .srt captions with whisper
# 2. Clamps SRT so subtitles never outlive A/V duration (Android/ExoPlayer reliability)
# 3. Muxes into MP4 with mov_text subs + normalization flags
# 4. Atomically swaps file so Channels keeps identity
# 5. Archives or deletes original .mpg (based on KEEP_ORIGINAL)

set -euo pipefail

VIDEO_PATH="${1:-}"
if [ -z "$VIDEO_PATH" ]; then
  echo "Usage: $0 /path/to/video.mpg"
  exit 2
fi

VIDEO_DIR="$(dirname "$VIDEO_PATH")"
VIDEO_BASE="$(basename "$VIDEO_PATH" .mpg)"

SRT_PATH="${VIDEO_DIR}/${VIDEO_BASE}.srt"
# Unique temp names to avoid collisions and make failures less destructive
TMP_MP4_PATH="${VIDEO_DIR}/${VIDEO_BASE}.$$.mp4"
TMP_SRT_PATH="${VIDEO_DIR}/${VIDEO_BASE}.$$.clamped.srt"
ORIG_PATH="${VIDEO_PATH}.orig"

WHISPER_MODEL="${WHISPER_MODEL:-medium}"
WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-/app/data/whisper}"
WHISPER_ARGS="${WHISPER_ARGS:-}"
KEEP_ORIGINAL="${KEEP_ORIGINAL:-true}"
SKIP_CAPTION_GENERATION="${SKIP_CAPTION_GENERATION:-false}"

FFMPEG="${FFMPEG:-ffmpeg}"
FFPROBE="${FFPROBE:-ffprobe}"
CLAMP_EPS_MS="${CLAMP_EPS_MS:-1}"   # 1ms margin

cleanup() {
  # Only remove temps; never touch the input/output path here.
  rm -f "$TMP_MP4_PATH" "$TMP_SRT_PATH" 2>/dev/null || true
}
trap cleanup EXIT

echo "FFMPEG: $FFMPEG"
echo "FFPROBE: $FFPROBE"
echo "Whisper model: $WHISPER_MODEL"
echo "Whisper model dir: $WHISPER_MODEL_DIR"
echo "Processing: $VIDEO_PATH"
echo "Keep original: $KEEP_ORIGINAL"
echo "Skip caption generation: $SKIP_CAPTION_GENERATION"

if [ "$SKIP_CAPTION_GENERATION" != "true" ]; then
  mkdir -p "$WHISPER_MODEL_DIR"
  echo "Generating captions..."
  if ! whisper --model "$WHISPER_MODEL" \
               --model_dir "$WHISPER_MODEL_DIR" \
               --language English \
               --output_format srt \
               --output_dir "$VIDEO_DIR" \
               $WHISPER_ARGS \
               "$VIDEO_PATH"; then
    echo "ERROR: Whisper failed for $VIDEO_PATH"
    exit 1
  fi
else
  echo "Skipping caption generation as requested."
fi

if [ ! -f "$SRT_PATH" ]; then
  echo "ERROR: Caption file not created: $SRT_PATH"
  exit 1
fi

echo "SRT_PATH: $SRT_PATH"
ls -l "$SRT_PATH"

# --- Step 2: Compute A/V end time and clamp SRT deterministically ---

echo "Computing media duration (max(video,audio))..."
V_DUR="$("$FFPROBE" -v error -select_streams v:0 \
  -show_entries stream=duration -of default=nw=1:nk=1 "$VIDEO_PATH" \
  | tr -d '\r' | sed -n '1p' | xargs || true)"

A_DUR="$("$FFPROBE" -v error -select_streams a:0 \
  -show_entries stream=duration -of default=nw=1:nk=1 "$VIDEO_PATH" \
  | tr -d '\r' | sed -n '1p' | xargs || true)"

# Some sources can produce N/A; treat missing audio as 0
if [ -z "${V_DUR}" ] || [ "${V_DUR}" = "N/A" ]; then
  echo "ERROR: Could not read video duration via ffprobe."
  exit 1
fi
if [ -z "${A_DUR}" ] || [ "${A_DUR}" = "N/A" ]; then
  A_DUR="0"
fi

MEDIA_END="$(
V_DUR="$V_DUR" A_DUR="$A_DUR" python3 - <<'PY'
import os
v=float(os.environ["V_DUR"])
a=float(os.environ["A_DUR"])
print(max(v,a))
PY
)"

echo "Video duration: $V_DUR"
echo "Audio duration: $A_DUR"
echo "Clamp END (max A/V): $MEDIA_END"

echo "Clamping SRT to media duration..."
END="$MEDIA_END" CLAMP_EPS_MS="$CLAMP_EPS_MS" \
python3 - "$SRT_PATH" > "$TMP_SRT_PATH" <<'PY'
import os, re, sys

if len(sys.argv) != 2:
    sys.exit("Usage: clamp.py input.srt")

srt_path = sys.argv[1]

end = float(os.environ["END"])
eps_ms = int(os.environ.get("CLAMP_EPS_MS", "1"))
eps = eps_ms / 1000.0

def to_sec(ts: str) -> float:
    h,m,sms = ts.split(':')
    s,ms = sms.split(',')
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

def to_ts(x: float) -> str:
    if x < 0: x = 0.0
    h = int(x//3600); x -= h*3600
    m = int(x//60);   x -= m*60
    s = int(x);       ms = int(round((x - s)*1000))
    if ms == 1000:
        s += 1; ms = 0
    if s == 60:
        m += 1; s = 0
    if m == 60:
        h += 1; m = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

with open(srt_path, "r", encoding="utf-8") as f:
    src = f.read().replace('\r\n', '\n')

blocks = re.split(r'\n\s*\n', src.strip(), flags=re.M)
out = []
idx = 1
dropped = 0
clamped = 0

time_re = re.compile(
    r'(\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d,\d\d\d)(.*)'
)

for b in blocks:
    lines = b.splitlines()
    if len(lines) < 2:
        continue

    tline_i = 1 if lines[0].strip().isdigit() else 0
    m = time_re.match(lines[tline_i].strip())
    if not m:
        continue

    start = to_sec(m.group(1))
    stop  = to_sec(m.group(2))
    tail  = m.group(3)

    if start >= end:
        dropped += 1
        continue

    if stop > end:
        stop = max(start + eps, end - eps)
        clamped += 1

    if stop <= start:
        stop = start + eps
        clamped += 1

    out.append(str(idx))
    out.append(f"{to_ts(start)} --> {to_ts(stop)}{tail}")
    out.extend(lines[tline_i+1:])
    out.append("")
    idx += 1

sys.stderr.write(f"Clamped SRT: dropped={dropped}, clamped={clamped}, end={end}\n")
sys.stdout.write("\n".join(out).rstrip() + "\n")
PY

echo "Clamped SRT written: $TMP_SRT_PATH"
ls -l "$TMP_SRT_PATH"

# --- Step 3: Mux with normalization flags ---

if [ -e /dev/nvidia0 ]; then
  echo "GPU detected (NVENC expected to be usable at runtime)."
else
  echo "No GPU detected (NVENC may fail if used; current command still requests NVENC)."
fi

echo "Muxing video + audio + clamped subtitles..."

"$FFMPEG" -y -hide_banner -loglevel info \
  -i "$VIDEO_PATH" -i "$TMP_SRT_PATH" \
  -map 0:v -map 0:a -map 1:0 \
  -c:v h264_nvenc -preset fast \
  -c:a copy \
  -c:s mov_text \
  -metadata:s:s:0 language=eng \
  -shortest \
  -avoid_negative_ts make_zero \
  -movflags +faststart \
  -max_interleave_delta 0 \
  "$TMP_MP4_PATH"

echo "Mux complete: $TMP_MP4_PATH (size: $(du -h "$TMP_MP4_PATH" | cut -f1))"

# Post-mux verification: durations + last subtitle end time
echo "Post-mux ffprobe summary (durations):"
"$FFPROBE" -v error -show_entries stream=index,codec_type,duration \
  -of default=nw=1 "$TMP_MP4_PATH" | sed 's/^/  /'

echo "Last subtitle packets (tail):"
"$FFPROBE" -v error -select_streams s:0 \
  -show_entries packet=pts_time,duration_time -of csv=p=0 "$TMP_MP4_PATH" | tail -n 5 | sed 's/^/  /'

# --- Step 4: Swap-in while preserving Channels filename identity ---

if [ "$KEEP_ORIGINAL" = "true" ]; then
  echo "Archiving original..."
  mv "$VIDEO_PATH" "$ORIG_PATH"
  echo "Original archived as: $ORIG_PATH"
else
  echo "Deleting original (KEEP_ORIGINAL=false)..."
  rm -f "$VIDEO_PATH"
  echo "Original deleted"
fi

echo "Replacing original with captioned file (renaming .mp4 back to .mpg)..."
mv "$TMP_MP4_PATH" "$VIDEO_PATH"

# Success: prevent trap cleanup from deleting the now-moved output
trap - EXIT

# Remove the clamped SRT temp; keep the original SRT
rm -f "$TMP_SRT_PATH" 2>/dev/null || true

echo "Complete!"
echo "New file: $VIDEO_PATH"
echo "Caption file: $SRT_PATH"
