# Diagnostic script to test caption embedding steps inside Docker container
# This runs the same steps as embed_captions.py but with detailed logging

$baseName = "CNN News Central 2025-12-19-1200"

Write-Host "`n=== Running diagnostic inside Docker container ===" -ForegroundColor Cyan

$script = @"
#!/bin/bash
set -e

BASE_DIR='/recordings/TV/CNN News Central'
BASE_NAME='$baseName'
MPG_PATH="\$BASE_DIR/\$BASE_NAME.mpg"
ORIG_PATH="\$MPG_PATH.orig"
AV_PATH="\$MPG_PATH.av.mp4"
SRT_PATH="\$BASE_DIR/\$BASE_NAME.srt"
MUXED_PATH="\$MPG_PATH.muxed.mp4"

echo ""
echo "=== Checking existing files ==="
ls -lh "\$BASE_DIR"

echo ""
echo "=== Step 2: Probe AV duration from .av.mp4 ==="
V_DUR=\$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "\$AV_PATH" 2>&1)
A_DUR=\$(ffprobe -v error -select_streams a:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "\$AV_PATH" 2>&1)
echo "  Video duration: \$V_DUR"
echo "  Audio duration: \$A_DUR"

END_TIME=\$(python3 -c "print(max(float('\$V_DUR'), float('\$A_DUR')) - 0.050)")
echo "  End time (max - 0.050): \$END_TIME"

echo ""
echo "=== Step 3: Check SRT file ==="
echo "  SRT file size: \$(stat -c%s "\$SRT_PATH") bytes"
echo "  First 10 lines:"
head -10 "\$SRT_PATH"

echo ""
echo "=== Step 4: Mux subtitles into MP4 ==="
echo "  Running ffmpeg mux command..."
if ffmpeg -y -i "\$AV_PATH" -i "\$SRT_PATH" -c:v copy -c:a copy -c:s mov_text -map 0:v -map 0:a? -map 1 -movflags +faststart "\$MUXED_PATH" 2>&1 | tee /tmp/ffmpeg_output.log; then
    echo ""
    echo "  SUCCESS: Muxed file created"
    ls -lh "\$MUXED_PATH"
else
    echo ""
    echo "  ERROR: FFmpeg failed with exit code \$?"
    echo "  Last 30 lines of output:"
    tail -30 /tmp/ffmpeg_output.log
    exit 1
fi

echo ""
echo "=== Step 5: Verify muxed file durations ==="
FV_DUR=\$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "\$MUXED_PATH" 2>&1)
FA_DUR=\$(ffprobe -v error -select_streams a:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "\$MUXED_PATH" 2>&1)
FS_DUR=\$(ffprobe -v error -select_streams s:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "\$MUXED_PATH" 2>&1)

echo "  Final video duration: \$FV_DUR"
echo "  Final audio duration: \$FA_DUR"
echo "  Final subtitle duration: \$FS_DUR"

MAX_AV=\$(python3 -c "print(max(float('\$FV_DUR'), float('\$FA_DUR')))")
MAX_AV_PLUS=\$(python3 -c "print(float('\$MAX_AV') + 0.050)")

echo ""
echo "  Max A/V: \$MAX_AV"
echo "  Max A/V + 0.050: \$MAX_AV_PLUS"
echo "  Subtitle duration: \$FS_DUR"

if python3 -c "import sys; sys.exit(0 if float('\$FS_DUR') <= float('\$MAX_AV_PLUS') else 1)"; then
    echo ""
    echo "  ✓ VERIFICATION PASSED"
    echo "  Ready to replace original .mpg file"
else
    echo ""
    echo "  ✗ VERIFICATION FAILED"
    echo "  Subtitle duration exceeds max A/V + 0.050"
    DIFF=\$(python3 -c "print(float('\$FS_DUR') - float('\$MAX_AV_PLUS'))")
    echo "  Difference: \$DIFF seconds"
fi

echo ""
echo "=== Final file listing ==="
ls -lh "\$BASE_DIR"
"@

# Write script to temp file and execute in Docker
$script | docker exec -i py-captions-dev bash
