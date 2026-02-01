# Setup pre-commit hook to run linters automatically
$sourcePath = "hooks/pre-commit"
$destPath = ".git/hooks/pre-commit"

if (-not (Test-Path $sourcePath)) {
    Write-Host "❌ Source hook not found: $sourcePath" -ForegroundColor Red
    exit 1
}

if (Test-Path $destPath) {
    Write-Host "Pre-commit hook already exists. Updating..." -ForegroundColor Yellow
}

# Copy hook from tracked location
Copy-Item -Path $sourcePath -Destination $destPath -Force

Write-Host "✅ Pre-commit hook installed!" -ForegroundColor Green
Write-Host "Linters will run automatically before each commit." -ForegroundColor Cyan
Write-Host "To bypass: git commit --no-verify" -ForegroundColor Yellow
