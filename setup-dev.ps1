# Quick setup for local testing environment (Windows)

Write-Host "Setting up local development environment..." -ForegroundColor Green

# Create .env.dev if it doesn't exist
if (-not (Test-Path .env.dev)) {
    @"
# Local Development Configuration
CHANNELS_API_URL=http://192.168.3.150:8089
USE_POLLING=true
USE_WEBHOOK=false
DRY_RUN=false
LOCAL_TEST_DIR=/recordings
POLL_INTERVAL_SECONDS=120
POLL_MAX_AGE_HOURS=2
LOG_VERBOSITY=VERBOSE
"@ | Out-File -FilePath .env.dev -Encoding utf8
    Write-Host "Created .env.dev file" -ForegroundColor Cyan
} else {
    Write-Host ".env.dev already exists" -ForegroundColor Yellow
}

# Create test directory structure
$dirs = @(
    "test-recordings\TV\CNN News Central",
    "test-recordings\TV\Amanpour",
    "test-recordings\Movies"
)
foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Copy sample recordings from niu to test-recordings/TV/CNN News Central/"
Write-Host "   Example: Copy CNN News Central 2026-02-04-*.mpg files"
Write-Host ""
Write-Host "2. Start dev environment:"
Write-Host "   docker-compose --env-file .env.dev -f docker-compose.dev.yml up -d"
Write-Host ""
Write-Host "3. View logs:"
Write-Host "   docker logs -f py-captions-dev"
