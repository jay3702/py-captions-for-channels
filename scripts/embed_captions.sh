#!/bin/bash
# Embed captions into MP4 for Fire TV compatibility
#
# Usage: embed_captions.sh /path/to/video.mpg
#
# Environment variables:
#   KEEP_ORIGINAL: true (default) to archive original as .mpg.orig, false to delete
#
# This script:
# 1. Generates .srt captions with whisper
# 2. Transcodes to .mp4 with burned-in subtitles
# 3. Archives or deletes original .mpg (based on KEEP_ORIGINAL)
# 4. Renames .mp4 to .mpg

set -euo pipefail

VIDEO_PATH="$1"
VIDEO_DIR="$(dirname "$VIDEO_PATH")"
VIDEO_BASE="$(basename "$VIDEO_PATH" .mpg)"
#   WHISPER_MODEL: whisper model size (default: medium)
#   WHISPER_MODEL_DIR: cache dir for whisper models (default: /app/data/whisper)
#   WHISPER_ARGS: extra args to pass to whisper
SRT_PATH="${VIDEO_DIR}/${VIDEO_BASE}.srt"
MP4_PATH="${VIDEO_DIR}/${VIDEO_BASE}.mp4"
WHISPER_MODEL="${WHISPER_MODEL:-medium}"
WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-/app/data/whisper}"
WHISPER_ARGS="${WHISPER_ARGS:-}"
ORIG_PATH="${VIDEO_PATH}.orig"
KEEP_ORIGINAL="${KEEP_ORIGINAL:-true}"


# Optionally skip caption generation for debugging
SKIP_CAPTION_GENERATION="${SKIP_CAPTION_GENERATION:-false}"

echo "Whisper model: $WHISPER_MODEL"
echo "Whisper model dir: $WHISPER_MODEL_DIR"
echo "Processing: $VIDEO_PATH"
echo "Keep original: $KEEP_ORIGINAL"
echo "Skip caption generation: $SKIP_CAPTION_GENERATION"

if [ "$SKIP_CAPTION_GENERATION" != "true" ]; then
    mkdir -p "$WHISPER_MODEL_DIR"
    echo "Generating captions..."
    # Write to temp directory first to avoid CIFS mount permission issues
    TEMP_OUTPUT_DIR="/tmp/whisper_output_$$"
    mkdir -p "$TEMP_OUTPUT_DIR"
    if ! whisper --model "$WHISPER_MODEL" --model_dir "$WHISPER_MODEL_DIR" --language English --output_format srt --output_dir "$TEMP_OUTPUT_DIR" $WHISPER_ARGS "$VIDEO_PATH"; then
        echo "ERROR: Whisper failed for $VIDEO_PATH"
        rm -rf "$TEMP_OUTPUT_DIR"
        exit 1
    fi
    # Copy SRT from temp to final location
    TEMP_SRT="${TEMP_OUTPUT_DIR}/${VIDEO_BASE}.srt"
    if [ -f "$TEMP_SRT" ]; then
        cp "$TEMP_SRT" "$SRT_PATH"
        echo "Copied SRT from temp: $TEMP_SRT -> $SRT_PATH"
        rm -rf "$TEMP_OUTPUT_DIR"
    else
        echo "ERROR: Whisper did not create expected SRT file: $TEMP_SRT"
        rm -rf "$TEMP_OUTPUT_DIR"
        exit 1
    fi
else
    echo "Skipping caption generation as requested."
fi

if [ ! -f "$SRT_PATH" ]; then
    echo "ERROR: Caption file not created: $SRT_PATH"
    exit 1
fi
if [ -e /dev/nvidia0 ]; then
    echo "Transcoding to MP4 with NVIDIA GPU (nvenc)..."
    VIDEO_CODEC="-c:v h264_nvenc -preset fast -rc:v vbr -cq:v 23"
else
    echo "Transcoding to MP4 with CPU (libx264)..."
    VIDEO_CODEC="-c:v libx264 -preset veryfast -crf 23"
fi




echo "SRT_PATH: $SRT_PATH"
ls -l "$SRT_PATH" || echo "SRT file not found at: $SRT_PATH"

# Workaround for ffmpeg subtitles filter bug with apostrophes in SRT path
USE_SYMLINK=0
if [[ "$SRT_PATH" == *"'"* ]]; then
    SAFE_SRT_SYMLINK="/tmp/ffmpeg_safe_subs_$$.srt"
    echo "Apostrophe detected in SRT path. Creating symlink: $SAFE_SRT_SYMLINK -> $SRT_PATH"
    ln -sf "$SRT_PATH" "$SAFE_SRT_SYMLINK"
    SRT_PATH_FFMPEG="$SAFE_SRT_SYMLINK"
    USE_SYMLINK=1
else
    SRT_PATH_FFMPEG="$SRT_PATH"
fi

# Use the safe path for ffmpeg
ffmpeg -i "$VIDEO_PATH" \
    -vf "subtitles=$SRT_PATH_FFMPEG" \
    $VIDEO_CODEC \
    -c:a aac -b:a 128k \
    -movflags +faststart \
    -y \
    "$MP4_PATH"
FFMPEG_EXIT_CODE=$?
if [ $USE_SYMLINK -eq 1 ]; then
    echo "Removing symlink: $SAFE_SRT_SYMLINK"
    rm -f "$SAFE_SRT_SYMLINK"
fi
if [ $FFMPEG_EXIT_CODE -ne 0 ]; then
    echo "ffmpeg failed with exit code $FFMPEG_EXIT_CODE"
    exit $FFMPEG_EXIT_CODE
fi
echo "Captions created: $SRT_PATH"

if [ ! -f "$MP4_PATH" ]; then
    echo "ERROR: Transcoding failed, MP4 not created"
    exit 1
fi

echo "MP4 created: $MP4_PATH (size: $(du -h "$MP4_PATH" | cut -f1))"

# Step 3: Handle original file based on KEEP_ORIGINAL setting
if [ "$KEEP_ORIGINAL" = "true" ]; then
    echo "Archiving original..."
    mv "$VIDEO_PATH" "$ORIG_PATH"
    echo "? Original archived as: $ORIG_PATH"
else
    echo "Deleting original (KEEP_ORIGINAL=false)..."
    rm "$VIDEO_PATH"
    echo "? Original deleted to save disk space"
fi

# Step 4: Rename MP4 to MPG
echo "Renaming MP4 to MPG..."
mv "$MP4_PATH" "$VIDEO_PATH"

echo "? Complete! New file with embedded captions: $VIDEO_PATH"
echo "? Caption file: $SRT_PATH"

