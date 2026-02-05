# Diagnostic script to test each step of the caption embedding process
# This helps identify which step is failing

$baseDir = "test-recordings\TV\CNN News Central"
$baseName = "CNN News Central 2025-12-19-1200"
$mpgPath = "$baseDir\$baseName.mpg"
$origPath = "$mpgPath.orig"
$avPath = "$mpgPath.av.mp4"
$srtPath = "$baseDir\$baseName.srt"
$muxedPath = "$mpgPath.muxed.mp4"

Write-Host "`n=== Checking existing files ===" -ForegroundColor Cyan
Get-ChildItem $baseDir | Select-Object Name, Length | Format-Table

Write-Host "`n=== Step 2: Probe AV duration from .av.mp4 ===" -ForegroundColor Cyan
$vDur = ffprobe -v error -select_streams v:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "$avPath" 2>&1 | Select-Object -First 1
$aDur = ffprobe -v error -select_streams a:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "$avPath" 2>&1 | Select-Object -First 1
Write-Host "  Video duration: $vDur"
Write-Host "  Audio duration: $aDur"
$endTime = [Math]::Max([double]$vDur, [double]$aDur) - 0.050
Write-Host "  End time (max - 0.050): $endTime" -ForegroundColor Yellow

Write-Host "`n=== Step 3: Check SRT file ===" -ForegroundColor Cyan
$srtSize = (Get-Item $srtPath).Length
Write-Host "  SRT file size: $srtSize bytes"
Write-Host "  First 10 lines:"
Get-Content $srtPath -Head 10

Write-Host "`n=== Step 4: Mux subtitles into MP4 ===" -ForegroundColor Cyan
$muxCmd = "ffmpeg -y -i `"$avPath`" -i `"$srtPath`" -c:v copy -c:a copy -c:s mov_text -map 0:v -map 0:a? -map 1 -movflags +faststart `"$muxedPath`""
Write-Host "  Command: $muxCmd" -ForegroundColor Gray
Write-Host "  Running..." -ForegroundColor Yellow

ffmpeg -y -i "$avPath" -i "$srtPath" -c:v copy -c:a copy -c:s mov_text -map 0:v -map "0:a?" -map 1 -movflags +faststart "$muxedPath" 2>&1 | Tee-Object -Variable ffmpegOutput

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n  ERROR: FFmpeg failed with exit code $LASTEXITCODE" -ForegroundColor Red
    Write-Host "  Last 20 lines of output:" -ForegroundColor Red
    $ffmpegOutput | Select-Object -Last 20
    exit 1
}

Write-Host "`n  SUCCESS: Muxed file created" -ForegroundColor Green
$muxedSize = (Get-Item $muxedPath).Length
Write-Host "  Muxed file size: $muxedSize bytes"

Write-Host "`n=== Step 5: Verify muxed file durations ===" -ForegroundColor Cyan
$fvDur = ffprobe -v error -select_streams v:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "$muxedPath" 2>&1 | Select-Object -First 1
$faDur = ffprobe -v error -select_streams a:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "$muxedPath" 2>&1 | Select-Object -First 1
$fsDur = ffprobe -v error -select_streams s:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "$muxedPath" 2>&1 | Select-Object -First 1

Write-Host "  Final video duration: $fvDur"
Write-Host "  Final audio duration: $faDur"
Write-Host "  Final subtitle duration: $fsDur"

$maxAV = [Math]::Max([double]$fvDur, [double]$faDur)
Write-Host "`n  Max A/V: $maxAV"
Write-Host "  Max A/V + 0.050: $($maxAV + 0.050)"
Write-Host "  Subtitle duration: $fsDur"

if ([double]$fsDur -le ($maxAV + 0.050)) {
    Write-Host "`n  VERIFICATION PASSED" -ForegroundColor Green
    Write-Host "  Ready to replace original .mpg file" -ForegroundColor Green
} else {
    Write-Host "`n  VERIFICATION FAILED" -ForegroundColor Red
    Write-Host "  Subtitle duration exceeds max A/V + 0.050" -ForegroundColor Red
    Write-Host "  Difference: $([double]$fsDur - ($maxAV + 0.050)) seconds" -ForegroundColor Red
}

Write-Host "`n=== Final file listing ===" -ForegroundColor Cyan
Get-ChildItem $baseDir | Select-Object Name, Length | Format-Table
