#!/bin/bash
# ============================================================================
# DEPRECATED: This shell script is deprecated in favor of embed_captions.py
# The Python version handles all caption generation and embedding.
# This file is kept for reference only - DO NOT USE IN PRODUCTION
# ============================================================================
#
# Embed captions into MPG for Channels DVR compatibility (subtitle stream, not burn-in)
#
# Usage: embed_captions.sh /path/to/video.mpg
#
# Key behaviors:
# - Preserves the first-seen original once as .mpg.orig (copy, never overwrite)
# - Always processes from .mpg.orig when present (idempotent reprocessing)
# - TWO-STEP pipeline for Android reliability:
#     1) Encode A/V only (NVENC + audio copy) -> av_only temp mp4
#     2) Probe encoded A/V duration, clamp SRT to that duration
#     3) Mux subtitles into av_only with -c copy (no re-encode) -> final temp mp4
# - Writes temp outputs in the SAME DIRECTORY as the target to allow atomic mv swap
# - Atomically replaces the target .mpg
#
# Environment variables:
#   WHISPER_MODEL (default: medium)
#   WHISPER_MODEL_DIR (default: /app/data/whisper)
#   WHISPER_ARGS (default: empty)
#   SKIP_CAPTION_GENERATION (default: false)
#
# Optional overrides:
#   FFMPEG (default: ffmpeg)
#   FFPROBE (default: ffprobe)
#   CLAMP_EPS_MS (default: 1)
#   KEEP_ORIG (default: true)  # if false, removes .orig after successful run (not recommended)

set -euo pipefail

VIDEO_PATH="${1:-}"
if [ -z "$VIDEO_PATH" ]; then
  echo "Usage: $0 /path/to/video.mpg"
  exit 2
fi
if [ ! -f "$VIDEO_PATH" ]; then
  echo "ERROR: Input file not found: $VIDEO_PATH"
  exit 3
fi

VIDEO_DIR="$(dirname "$VIDEO_PATH")"
VIDEO_BASE="$(basename "$VIDEO_PATH" .mpg)"

# We ALWAYS want captions at: <basename>.srt (no .mpg.srt nonsense)
SRT_PATH="${VIDEO_DIR}/${VIDEO_BASE}.srt"
ORIG_PATH="${VIDEO_PATH}.cc4chan.orig"

WHISPER_MODEL="${WHISPER_MODEL:-medium}"
WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-/app/data/whisper}"
WHISPER_ARGS="${WHISPER_ARGS:-}"
SKIP_CAPTION_GENERATION="${SKIP_CAPTION_GENERATION:-false}"

FFMPEG="${FFMPEG:-ffmpeg}"
FFPROBE="${FFPROBE:-ffprobe}"
CLAMP_EPS_MS="${CLAMP_EPS_MS:-1}"
KEEP_ORIG="${KEEP_ORIG:-true}"

PID="$$"
TS="$(date +%s)"

# Temp files in same directory as target for atomic replace
TMP_AV_PATH="${VIDEO_DIR}/${VIDEO_BASE}.cc4chan.tmp.${TS}.${PID}.av.mp4"
TMP_SRT_PATH="${VIDEO_DIR}/${VIDEO_BASE}.cc4chan.tmp.${TS}.${PID}.clamped.srt"
TMP_OUT_PATH="${VIDEO_DIR}/${VIDEO_BASE}.cc4chan.tmp.${TS}.${PID}.final.mp4"

cleanup() {
  rm -f "$TMP_AV_PATH" "$TMP_SRT_PATH" "$TMP_OUT_PATH" 2>/dev/null || true
}
trap cleanup EXIT

echo "FFMPEG: $FFMPEG"
echo "FFPROBE: $FFPROBE"
echo "Processing target: $VIDEO_PATH"
echo "Original preserve path: $ORIG_PATH"
echo "Skip caption generation: $SKIP_CAPTION_GENERATION"
echo "KEEP_ORIG: $KEEP_ORIG"

# --- Preserve original once (copy, never overwrite) ---
if [ ! -f "$ORIG_PATH" ]; then
  echo "Preserving original once..."
  cp -p "$VIDEO_PATH" "$ORIG_PATH"
  sync
  echo "Original preserved: $ORIG_PATH"
else
  echo "Original already preserved: $ORIG_PATH"
fi

# Always process from preserved original
INPUT_FOR_PROCESSING="$ORIG_PATH"
if [ ! -f "$INPUT_FOR_PROCESSING" ]; then
  INPUT_FOR_PROCESSING="$VIDEO_PATH"
fi
echo "Input used for processing: $INPUT_FOR_PROCESSING"

# --- Caption generation (Whisper) ---
if [ "$SKIP_CAPTION_GENERATION" != "true" ]; then
  mkdir -p "$WHISPER_MODEL_DIR"
  echo "Generating captions with whisper..."
  if ! whisper --model "$WHISPER_MODEL" \
               --model_dir "$WHISPER_MODEL_DIR" \
               --language English \
               --output_format srt \
               --output_dir "$VIDEO_DIR" \
               $WHISPER_ARGS \
               "$INPUT_FOR_PROCESSING"; then
    echo "ERROR: Whisper failed for $INPUT_FOR_PROCESSING"
    exit 1
  fi

  # Whisper names output based on input filename, which may be *.mpg.orig -> *.mpg.orig.srt
  # Normalize to $SRT_PATH (basename.srt) and remove the odd variant(s).
  CANDIDATES=(
    "${INPUT_FOR_PROCESSING}.srt"          # e.g. X.mpg.orig.srt
    "${VIDEO_PATH}.srt"                   # e.g. X.mpg.srt (if whisper was run on X.mpg)
    "${VIDEO_DIR}/${VIDEO_BASE}.mpg.srt"  # e.g. X.mpg.srt (alternate pattern)
    "${SRT_PATH}"
  )

  FOUND=""
  for c in "${CANDIDATES[@]}"; do
    if [ -f "$c" ]; then
      FOUND="$c"
      break
    fi
  done

  if [ -z "$FOUND" ]; then
    echo "ERROR: Whisper did not produce an SRT we can find."
    echo "Tried:"
    printf '  %s\n' "${CANDIDATES[@]}"
    exit 1
  fi

  if [ "$FOUND" != "$SRT_PATH" ]; then
    echo "Normalizing Whisper output:"
    echo "  from: $FOUND"
    echo "  to:   $SRT_PATH"
    mv -f "$FOUND" "$SRT_PATH"
  fi

  # Clean up any lingering variants so we only keep *.srt
  for c in "${CANDIDATES[@]}"; do
    if [ -f "$c" ] && [ "$c" != "$SRT_PATH" ]; then
      rm -f "$c" 2>/dev/null || true
    fi
  done
else
  echo "Skipping caption generation as requested."
fi

if [ ! -f "$SRT_PATH" ]; then
  echo "ERROR: Caption file not found: $SRT_PATH"
  exit 1
fi

echo "SRT_PATH: $SRT_PATH"
ls -l "$SRT_PATH"

# --- Step 1: Encode A/V only ---
if [ -e /dev/nvidia0 ]; then
  echo "GPU detected (NVENC expected to be usable at runtime)."
else
  echo "No GPU detected (NVENC may fail; current pipeline still requests NVENC)."
fi

echo "Step 1: Encoding A/V only -> $TMP_AV_PATH"
"$FFMPEG" -y -hide_banner -loglevel info \
  -i "$INPUT_FOR_PROCESSING" \
  -map 0:v -map 0:a \
  -c:v h264_nvenc -preset fast \
  -c:a copy \
  -avoid_negative_ts make_zero \
  -movflags +faststart \
  "$TMP_AV_PATH"

# --- Step 2: Probe ENCODED A/V duration and clamp SRT to that ---
echo "Step 2: Probing encoded A/V duration..."
V_DUR="$("$FFPROBE" -v error -select_streams v:0 \
  -show_entries stream=duration -of default=nw=1:nk=1 "$TMP_AV_PATH" \
  | tr -d '\r' | sed -n '1p' | xargs || true)"

A_DUR="$("$FFPROBE" -v error -select_streams a:0 \
  -show_entries stream=duration -of default=nw=1:nk=1 "$TMP_AV_PATH" \
  | tr -d '\r' | sed -n '1p' | xargs || true)"

if [ -z "${V_DUR}" ] || [ "${V_DUR}" = "N/A" ]; then
  echo "ERROR: Could not read encoded video duration via ffprobe."
  exit 4
fi
if [ -z "${A_DUR}" ] || [ "${A_DUR}" = "N/A" ]; then
  A_DUR="0"
fi

END="$(
V_DUR="$V_DUR" A_DUR="$A_DUR" python3 - <<'PY'
import os
print(max(float(os.environ["V_DUR"]), float(os.environ["A_DUR"])))
PY
)"

echo "Encoded video duration: $V_DUR"
echo "Encoded audio duration: $A_DUR"
echo "Clamp END: $END"

echo "Clamping SRT -> $TMP_SRT_PATH"
END="$END" CLAMP_EPS_MS="$CLAMP_EPS_MS" \
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

time_re = re.compile(r'(\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d,\d\d\d)(.*)')

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

# --- Step 3: Mux subtitles into encoded A/V with -c copy (no re-encode) ---
echo "Step 3: Muxing clamped subs into A/V -> $TMP_OUT_PATH"
"$FFMPEG" -y -hide_banner -loglevel info \
  -i "$TMP_AV_PATH" -i "$TMP_SRT_PATH" \
  -map 0 -map 1:0 \
  -c copy \
  -c:s mov_text \
  -metadata:s:s:0 language=eng \
  -movflags +faststart \
  "$TMP_OUT_PATH"

# --- Verification: ensure subs do not outlive A/V in FINAL output ---
echo "Verifying final durations..."
FV="$("$FFPROBE" -v error -select_streams v:0 -show_entries stream=duration -of default=nw=1:nk=1 "$TMP_OUT_PATH" | sed -n '1p' | xargs || true)"
FA="$("$FFPROBE" -v error -select_streams a:0 -show_entries stream=duration -of default=nw=1:nk=1 "$TMP_OUT_PATH" | sed -n '1p' | xargs || true)"
FS="$("$FFPROBE" -v error -select_streams s:0 -show_entries stream=duration -of default=nw=1:nk=1 "$TMP_OUT_PATH" | sed -n '1p' | xargs || true)"
if [ -z "$FV" ] || [ "$FV" = "N/A" ]; then FV="0"; fi
if [ -z "$FA" ] || [ "$FA" = "N/A" ]; then FA="0"; fi
if [ -z "$FS" ] || [ "$FS" = "N/A" ]; then FS="0"; fi

MAX_AV="$(
FV="$FV" FA="$FA" python3 - <<'PY'
import os
print(max(float(os.environ["FV"]), float(os.environ["FA"])))
PY
)"

echo "Final video duration: $FV"
echo "Final audio duration: $FA"
echo "Final subtitle duration: $FS"
echo "Final max(A/V): $MAX_AV"

OK="$(
MAX_AV="$MAX_AV" FS="$FS" python3 - <<'PY'
import os
max_av=float(os.environ["MAX_AV"])
fs=float(os.environ["FS"])
print("yes" if fs <= max_av + 0.002 else "no")
PY
)"
if [ "$OK" != "yes" ]; then
  echo "ERROR: Subtitle duration exceeds A/V duration (Android-risk). Refusing to replace target."
  echo "Keeping outputs for inspection:"
  echo "  $TMP_AV_PATH"
  echo "  $TMP_SRT_PATH"
  echo "  $TMP_OUT_PATH"
  exit 5
fi

# --- Atomic replace of the target .mpg ---
echo "Atomically replacing target file..."
mv -f "$TMP_OUT_PATH" "$VIDEO_PATH"

rm -f "$TMP_AV_PATH" "$TMP_SRT_PATH" 2>/dev/null || true

if [ "$KEEP_ORIG" = "false" ]; then
  echo "KEEP_ORIG=false: removing preserved original $ORIG_PATH"
  rm -f "$ORIG_PATH" 2>/dev/null || true
fi

trap - EXIT

echo "Complete!"
echo "New file: $VIDEO_h