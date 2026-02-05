#!/usr/bin/env pwsh
# Quick status check for Whisper processing

Write-Host "`n=== Whisper Processing Status ===" -ForegroundColor Green
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n" -ForegroundColor Cyan

# Check if Whisper process is running
$proc = docker exec py-captions-dev ps aux 2>$null | Select-String "whisper.*\.mpg"

if ($proc) {
    $parts = $proc -split '\s+'
    Write-Host "STATUS: Processing..." -ForegroundColor Yellow
    Write-Host "  CPU: $($parts[2])%" -ForegroundColor White
    Write-Host "  Memory: $($parts[3])%" -ForegroundColor White
    Write-Host "  Runtime: $($parts[9])" -ForegroundColor White
    Write-Host "`nNote: Whisper typically takes 10-20 minutes for a 1-hour video" -ForegroundColor Gray
} else {
    Write-Host "STATUS: Not running" -ForegroundColor White
    
    # Check if recently completed
    $recentLogs = docker logs py-captions-dev --tail 50 2>&1 | Select-String "Whisper|completed|failed"
    if ($recentLogs) {
        Write-Host "`nRecent Whisper activity:" -ForegroundColor Cyan
        $recentLogs | Select-Object -First 3
    }
}

# Check for generated files
Write-Host "`n=== Generated Files ===" -ForegroundColor Green
$files = Get-ChildItem "test-recordings\TV\CNN News Central\*" -Include *.srt,*.orig -ErrorAction SilentlyContinue

if ($files) {
    $files | Format-Table Name, @{Label="Size (MB)";Expression={[math]::Round($_.Length/1MB, 2)}}, LastWriteTime -AutoSize
} else {
    Write-Host "No .srt or .orig files found yet" -ForegroundColor Gray
}

Write-Host ""
