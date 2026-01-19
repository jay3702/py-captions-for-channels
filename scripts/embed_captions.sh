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
SRT_PATH="${VIDEO_DIR}/${VIDEO_BASE}.srt"
MP4_PATH="${VIDEO_DIR}/${VIDEO_BASE}.mp4"
ORIG_PATH="${VIDEO_PATH}.orig"
KEEP_ORIGINAL="${KEEP_ORIGINAL:-true}"

echo "Processing: $VIDEO_PATH"
echo "Keep original: $KEEP_ORIGINAL"

# Step 1: Generate SRT captions
echo "Generating captions..."
whisper --model medium --output_format srt --output_dir "$VIDEO_DIR" "$VIDEO_PATH"

if [ ! -f "$SRT_PATH" ]; then
    echo "ERROR: Caption file not created: $SRT_PATH"
    exit 1
fi

echo "Captions created: $SRT_PATH"

# Step 2: Transcode to MP4 with burned-in subtitles
echo "Transcoding to MP4 with embedded captions using NVIDIA GPU (this will take 2-3 minutes)..."
ffmpeg -i "$VIDEO_PATH" \
    -vf "subtitles=$SRT_PATH" \
    -c:v h264_nvenc -preset fast -rc:v vbr -cq:v 23 \
    -c:a aac -b:a 128k \
    -movflags +faststart \
    -y \
    "$MP4_PATH"

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

