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
# This script:
# 1. Generates .srt captions with whisper
# 2. Replaces subtitle stream in the video (no burn-in)
# 3. Atomically swaps file so Channels keeps identity
# 4. Archives or deletes original .mpg (based on KEEP_ORIGINAL)

set -euo pipefail

VIDEO_PATH="$1"
VIDEO_DIR="$(dirname "$VIDEO_PATH")"
VIDEO_BASE="$(basename "$VIDEO_PATH" .mpg)"

SRT_PATH="${VIDEO_DIR}/${VIDEO_BASE}.srt"
TMP_PATH="${VIDEO_PATH}.tmp"
ORIG_PATH="${VIDEO_PATH}.orig"

WHISPER_MODEL="${WHISPER_MODEL:-medium}"
WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-/app/data/whisper}"
WHISPER_ARGS="${WHISPER_ARGS:-}"
KEEP_ORIGINAL="${KEEP_ORIGINAL:-true}"
SKIP_CAPTION_GENERATION="${SKIP_CAPTION_GENERATION:-false}"

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

# Choose audio handling (keep your AAC transcode behavior)
if [ -e /dev/nvidia0 ]; then
    echo "GPU detected (but video is stream-copied, not re-encoded)."
else
    echo "No GPU detected (video is stream-copied, not re-encoded)."
fi

echo "Remuxing video and replacing subtitle stream..."

# ffmpeg -i "$VIDEO_PATH" -i "$SRT_PATH" \
#     -map 0:v -map 0:a -map 1:s \
#     -c:v copy \
#     -c:a aac -b:a 128k \
#     -c:s mov_text \
#     -movflags +faststart \
#     -y \
#     "$TMP_PATH"

# ffmpeg -i "$VIDEO_PATH" -i "$SRT_PATH" \
#     -map 0:v -map 0:a -map 1:0 \
#     -c copy \
#     -c:s mov_text \
#     -metadata:s:s:0 language=eng \
#     -f mpegts \
#     -y \
#     "$TMP_PATH"

ffmpeg -i "$VIDEO_PATH" -i "$SRT_PATH" \
  -map 0:v -map 0:a -map 1:0 \
  -c:v h264_nvenc -preset fast \
  -c:a copy \
  -c:s mov_text \
  -metadata:s:s:0 language=eng \
  "$TMP_PATH"

echo "Remux complete: $TMP_PATH (size: $(du -h "$TMP_PATH" | cut -f1))"

# Step 3: Handle original file based on KEEP_ORIGINAL setting
if [ "$KEEP_ORIGINAL" = "true" ]; then
    echo "Archiving original..."
    mv "$VIDEO_PATH" "$ORIG_PATH"
    echo "Original archived as: $ORIG_PATH"
else
    echo "Deleting original (KEEP_ORIGINAL=false)..."
    rm "$VIDEO_PATH"
    echo "Original deleted"
fi

# Step 4: Atomically replace with new file
echo "Replacing original with captioned file..."
mv "$TMP_PATH" "$VIDEO_PATH"

echo "Complete!"
echo "New file with embedded subtitle stream: $VIDEO_PATH"
echo "Caption file: $SRT_PATH"
