#!/usr/bin/env pwsh
# Reset Development Environment
# Clears all state and restarts containers for fresh testing

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Resetting Development Environment" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Stop containers
Write-Host "`n[1/4] Stopping containers..." -ForegroundColor Yellow
docker-compose --env-file .env.dev -f docker-compose.dev.yml down

# Clear state files
Write-Host "[2/4] Clearing state files..." -ForegroundColor Yellow
if (Test-Path ".\data-dev") {
    Remove-Item .\data-dev\* -Force -ErrorAction SilentlyContinue
    Write-Host "  - Removed state.json, executions.json" -ForegroundColor Gray
}
if (Test-Path ".\logs-dev") {
    Remove-Item .\logs-dev\* -Force -ErrorAction SilentlyContinue
    Write-Host "  - Removed app.log" -ForegroundColor Gray
}

# Clear any generated files in test-recordings (but keep .mpg files)
Write-Host "[3/4] Cleaning test-recordings..." -ForegroundColor Yellow
if (Test-Path ".\test-recordings") {
    Get-ChildItem -Path ".\test-recordings" -Recurse -Include "*.srt","*.orig" | Remove-Item -Force
    $count = (Get-ChildItem -Path ".\test-recordings" -Recurse -Include "*.srt","*.orig").Count
    Write-Host "  - Cleaned .srt and .orig files" -ForegroundColor Gray
}

# Restart containers
Write-Host "[4/4] Starting fresh containers..." -ForegroundColor Yellow
docker-compose --env-file .env.dev -f docker-compose.dev.yml up -d

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "Dev Environment Reset Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Copy a file from test-recordings/tmp/ to test-recordings/TV/ShowName/" -ForegroundColor White
Write-Host "  2. Wait 1-5 minutes for polling to detect it" -ForegroundColor White
Write-Host "  3. Monitor: docker logs -f py-captions-dev" -ForegroundColor White
Write-Host "  4. View UI: http://localhost:8001" -ForegroundColor White
Write-Host ""
