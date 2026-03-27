# setup-windows.ps1 — self-bootstrapping Windows installer for py-captions-for-channels
#
# This is the single-file entry point for Windows users.
# Run it once in an elevated (Administrator) PowerShell session and it will:
#   1. Download the installer scripts it needs (setup-wsl.ps1, setup-wsl.sh, autostart.ps1)
#   2. Hand off to setup-wsl.ps1, which installs WSL2, Docker, and the container
#
# Usage (one-liner — paste into an elevated PowerShell):
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   irm https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main/setup-windows.ps1 | iex
#
# Or save locally first, then run:
#   .\setup-windows.ps1
# ---------------------------------------------------------------------------
param(
    [string]$Distro    = "Ubuntu-22.04",
    [string]$DeployDir = ""  # Windows path to install into; defaults to caller's working directory
)

$ErrorActionPreference = "Stop"

$REPO_RAW = "https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main"

# ── When piped through iex, MyCommand.Path is null — re-run from a temp file
if (-not $MyInvocation.MyCommand.Path) {
    $tmpScript = Join-Path $env:TEMP "setup-windows.ps1"
    Write-Host "  Downloading setup-windows.ps1 to $tmpScript..." -ForegroundColor DarkGray
    Invoke-WebRequest -Uri "$REPO_RAW/setup-windows.ps1" -OutFile $tmpScript -UseBasicParsing
    # Preserve caller's working directory as the deploy location
    $callerDir = if ($DeployDir) { $DeployDir } else { $PWD.Path }
    & $tmpScript -Distro $Distro -DeployDir $callerDir
    return
}

$SCRIPTS_NEEDED = @(
    "scripts/setup-wsl.ps1",
    "scripts/setup-wsl.sh",
    "scripts/autostart.ps1"
)

function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "✘ $msg" -ForegroundColor Red; exit 1 }

# ── Require an elevated session ───────────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]"Administrator")
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "  This script must be run as Administrator." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Right-click PowerShell and choose 'Run as Administrator'," -ForegroundColor Yellow
    Write-Host "  then run the script again." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "  py-captions-for-channels — Windows setup" -ForegroundColor White
Write-Host ""

# ── Bootstrap: download required scripts if not already present ───────────
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptsDir = Join-Path $ScriptRoot "scripts"

$anyDownloaded = $false

foreach ($rel in $SCRIPTS_NEEDED) {
    $dest = Join-Path $ScriptRoot $rel
    if (Test-Path $dest) { continue }

    if (-not $anyDownloaded) {
        Write-Step "Downloading installer scripts..."
        New-Item -ItemType Directory -Force -Path $ScriptsDir | Out-Null
    }

    $url = "$REPO_RAW/$($rel -replace '\\', '/')"
    Write-Host "  Fetching $rel" -ForegroundColor DarkGray
    try {
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    } catch {
        Write-Fail "Failed to download ${rel}: $_`n  Check your internet connection and try again."
    }
    $anyDownloaded = $true
}

if ($anyDownloaded) {
    Write-Ok "Scripts downloaded to $ScriptsDir"
} else {
    Write-Ok "Installer scripts already present"
}

# ── Hand off to setup-wsl.ps1 ─────────────────────────────────────────────
$wslSetup = Join-Path $ScriptsDir "setup-wsl.ps1"

Write-Host ""
Write-Step "Launching setup-wsl.ps1..."
Write-Host ""

$setupArgs = @{ Distro = $Distro }
# Pass caller's working directory as the install target (like git clone)
$effectiveDeployDir = if ($DeployDir) { $DeployDir } else { $PWD.Path }
if ($effectiveDeployDir) { $setupArgs['DeployDir'] = $effectiveDeployDir }
& $wslSetup @setupArgs
