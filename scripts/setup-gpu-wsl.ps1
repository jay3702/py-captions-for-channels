# setup-gpu-wsl.ps1 — Windows launcher for the py-captions GPU installer
#
# Run this in PowerShell (7+ recommended) on Windows.
# It ensures WSL2 + Ubuntu are set up, then runs the interactive bash installer inside WSL2.
#
# Usage:
#   .\scripts\setup-gpu-wsl.ps1
#   .\scripts\setup-gpu-wsl.ps1 -Distro Ubuntu-24.04
# ---------------------------------------------------------------------------
param(
    [string]$Distro = "Ubuntu-22.04"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg)    { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Fail($msg)    { Write-Host "✘ $msg" -ForegroundColor Red; exit 1 }

# ── STEP 1 — Check WSL2 is available ──────────────────────────────────────
Write-Step "Checking WSL2..."
$wslOutput = wsl --status 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -and -not ($wslOutput -match "WSL")) {
    Write-Step "WSL2 not found — installing..."
    wsl --install --no-distribution
    Write-Warn "WSL2 kernel installed. A reboot may be required."
    Write-Warn "After rebooting, re-run this script."
    Write-Warn "  powershell -File `"$PSCommandPath`""
    exit 0
}
Write-Ok "WSL2 is available"

# ── STEP 2 — Check / install the target distro ────────────────────────────
Write-Step "Checking for $Distro..."
# wsl -l -q outputs UTF-16 LE; PowerShell reads it as ASCII with embedded nulls.
# Strip them before trying to match.
$installed = wsl -l -q 2>&1 | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ -match [regex]::Escape($Distro) }
if (-not $installed) {
    Write-Step "$Distro not found — installing..."
    wsl --install -d $Distro --no-launch

    # The WSL service can take a few seconds to register a freshly installed distro.
    # Poll until it appears in 'wsl -l -q' (up to ~10 s) before trying to use it.
    $retries = 0
    do {
        Start-Sleep -Seconds 2
        $installed = wsl -l -q 2>&1 |
            ForEach-Object { ($_ -replace "`0", "").Trim() } |
            Where-Object { $_ -match [regex]::Escape($Distro) }
        $retries++
    } while (-not $installed -and $retries -lt 5)

    if (-not $installed) {
        Write-Fail "'$Distro' still not found after install — try rebooting and re-running this script."
    }

    # First-run setup requires interactive input (new Linux username + password).
    # Running with '-- echo' bypasses the setup wizard; open an interactive session instead.
    Write-Step "Starting $Distro for first-time setup (set a username and password when prompted)..."
    Write-Host "  Enter your new Linux username and password, then type 'exit' to return here." -ForegroundColor Yellow
    wsl -d $Distro
    Write-Ok "$Distro installed"
} else {
    Write-Ok "$Distro is already installed"
}

# Ensure WSL2 version
$versionLine = wsl -l -v 2>&1 | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ -match [regex]::Escape($Distro) }
if ($versionLine -match "1\s*$") {
    Write-Step "Upgrading $Distro to WSL2..."
    wsl --set-version $Distro 2
}

# ── STEP 3 — Check NVIDIA driver on Windows ───────────────────────────────
Write-Step "Checking NVIDIA driver..."
try {
    $smi = & nvidia-smi 2>&1 | Out-String
    if ($smi -match "Driver Version") {
        $driverMatch = [regex]::Match($smi, "Driver Version:\s+([\d.]+)")
        $cudaMatch   = [regex]::Match($smi, "CUDA Version:\s+([\d.]+)")
        Write-Ok ("NVIDIA driver {0} — CUDA {1}" -f $driverMatch.Groups[1].Value, $cudaMatch.Groups[1].Value)

        $cudaVer = [version]($cudaMatch.Groups[1].Value)
        if ($cudaVer -lt [version]"12.2") {
            Write-Warn ("CUDA {0} detected — 12.2+ recommended. GPU may fall back to CPU." -f $cudaMatch.Groups[1].Value)
            Write-Warn "Download latest driver: https://www.nvidia.com/Download/index.aspx"
        }
    }
} catch {
    Write-Warn "nvidia-smi not found in PATH — make sure NVIDIA drivers are installed on Windows."
    Write-Warn "Download: https://www.nvidia.com/Download/index.aspx"
    $cont = Read-Host "Continue anyway? [y/N]"
    if ($cont -notmatch "^[Yy]") { exit 0 }
}

# ── STEP 4 — Run installer inside WSL2 ───────────────────────────────────
Write-Step "Preparing bash installer..."

# The bash script lives next to this PowerShell script (in scripts/)
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$BashScript = Join-Path $ScriptDir "setup-gpu-wsl.sh"

if (-not (Test-Path $BashScript)) {
    Write-Fail "setup-gpu-wsl.sh not found at: $BashScript`nMake sure both scripts are in the same directory."
}

# Convert Windows path to WSL2 path without calling wslpath (avoids quoting issues)
# e.g. C:\Users\jay\...  →  /mnt/c/Users/jay/...
$drive       = $BashScript[0].ToString().ToLower()
$winRelPath  = $BashScript.Substring(3).Replace('\', '/')
$WslBashPath = "/mnt/$drive/$winRelPath"

Write-Ok "Launching installer inside $Distro..."
Write-Host ""
Read-Host "  The installer will ask for your Linux (sudo) password when it starts.`n  Press Enter to launch the setup wizard"
Write-Host ""

wsl -d $Distro -- bash "$WslBashPath"

if ($LASTEXITCODE -ne 0) {
    Write-Fail "Installer exited with code $LASTEXITCODE"
}

# ── STEP 5 — Register Windows startup task (runs natively here, not from WSL) ──
Write-Host ""
Read-Host "  Next: registering the Windows auto-start task.`n  A UAC (administrator) prompt will appear — click Yes to allow it.`n  Press Enter when ready"
Write-Host ""
Write-Step "Registering Windows startup task..."
$AutostartScript = Join-Path $ScriptDir "autostart.ps1"

if (Test-Path $AutostartScript) {
    & $AutostartScript -Distro $Distro
} else {
    Write-Warn "autostart.ps1 not found — run it manually later to enable auto-start:"
    Write-Warn "  .\scripts\autostart.ps1"
}

Write-Host ""
Write-Ok "All done — open http://localhost:8000 in your browser"
