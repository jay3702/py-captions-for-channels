# autostart.ps1 — Register (or re-register) the Windows startup task for py-captions-for-channels
#
# This creates a Windows Task Scheduler task that wakes the WSL2 distro at
# every Windows logon, which in turn lets systemd start Docker and the container
# automatically — no terminal needed.
#
# Usage (PowerShell, any directory):
#   .\scripts\autostart.ps1
#   .\scripts\autostart.ps1 -Distro Ubuntu-24.04
#   .\scripts\autostart.ps1 -Restart    # also shuts down WSL so systemd takes effect
# ---------------------------------------------------------------------------
param(
    [string]$Distro  = "Ubuntu-22.04",
    [switch]$Restart                     # pass to force wsl --shutdown + relaunch
)

$ErrorActionPreference = "Stop"
$TaskName = "py-captions-wsl-autostart"

function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }

# ── Self-elevate if not already admin ─────────────────────────────────────
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]"Administrator")) {
    Write-Step "Requesting administrator rights to register the startup task..."
    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Distro `"$Distro`""
    if ($Restart) { $argList += " -Restart" }
    Start-Process powershell -Verb RunAs -ArgumentList $argList -Wait
    exit $LASTEXITCODE
}

# ── Register the scheduled task ───────────────────────────────────────────
Write-Step "Registering startup task '$TaskName' for distro '$Distro'..."

$action   = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $Distro -- true"
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -Description "Wakes WSL2 ($Distro) at logon so py-captions-for-channels runs without a terminal" `
    -Force | Out-Null

Write-Ok "Startup task registered."

# ── Restart WSL if systemd is not yet active as PID 1 ────────────────────
# Required the first time systemd=true is written, AND any subsequent run
# where WSL is still using the old init (WSL keeps whichever PID 1 it booted with).
$pid1 = (wsl -d $Distro -- bash -c "ps -p 1 -o comm= 2>/dev/null" 2>$null) -join "" 
$pid1 = $pid1.Trim()
$systemdActive = ($pid1 -match "systemd")

if (-not $systemdActive -or $Restart) {
    if (-not $systemdActive) {
        Write-Warn "systemd is not yet PID 1 (current: '$pid1') — restarting WSL to activate it..."
    } else {
        Write-Step "Restarting WSL as requested..."
    }
    wsl --shutdown
    Start-Sleep -Seconds 3
    Write-Step "Starting $Distro in background (Docker will follow via systemd)..."
    Start-Process "wsl.exe" -ArgumentList "-d $Distro -- true" -WindowStyle Hidden
    Write-Ok "WSL restarted. Docker and the container will be up in ~15 seconds."
    Write-Host ""
    Write-Host "  Web dashboard: http://localhost:8000" -ForegroundColor White
} else {
    Write-Ok "systemd is already active — no restart needed."
}
