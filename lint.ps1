# Run linters before committing
Write-Host "Running Black formatter..." -ForegroundColor Cyan
black .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Black formatting failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Running flake8..." -ForegroundColor Cyan
flake8 . --max-line-length=88 --extend-ignore=E203,W503
if ($LASTEXITCODE -ne 0) {
    Write-Host "Flake8 checks failed!" -ForegroundColor Red
    exit 1
}

Write-Host "All linters passed! ✨" -ForegroundColor Green
