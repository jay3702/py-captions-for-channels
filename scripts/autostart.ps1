# autostart.ps1 — Register (or re-register) the Windows startup task for py-captions-for-channels
#
# This creates a Windows Task Scheduler task that wakes the WSL2 distro at
# every Windows logon, which in turn lets systemd start Docker and the container
# automatically — no terminal needed.
#
# Usage (PowerShell, any directory):
#   .\scripts\autostart.ps1
#   .\scripts\autostart.ps1 -Distro Ubuntu-24.04
# ---------------------------------------------------------------------------
param(
    [string]$Distro       = "Ubuntu-22.04",
    [switch]$RegisterOnly   # internal: used when re-launching elevated
)

$ErrorActionPreference = "Stop"
$TaskName = "py-captions-wsl-autostart"

function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]"Administrator")

# ── Elevated branch: ONLY register the task, then exit ───────────────────
# We must not touch WSL from the elevated process — WSL launched from an
# Admin context runs in an isolated session and dies when the window closes.
if ($isAdmin) {
    Write-Step "Registering startup task '$TaskName' for distro '$Distro'..."

    $action   = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "--distribution $Distro --exec dbus-launch true"
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
    exit 0
}

# ── Non-elevated branch: request elevation for task registration, then ────
# handle WSL restart ourselves (so WSL runs in the correct user session).
Write-Step "Requesting administrator rights to register the startup task..."
Start-Process powershell -Verb RunAs `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Distro `"$Distro`" -RegisterOnly" `
    -Wait

# ── Restart WSL if systemd is not yet PID 1 ──────────────────────────────
$pid1 = (wsl -d $Distro -- bash -c "ps -p 1 -o comm= 2>/dev/null" 2>$null) -join ""
$pid1 = $pid1.Trim()
$systemdActive = ($pid1 -match "systemd")

if (-not $systemdActive) {
    Write-Warn "systemd is not yet PID 1 (current: '$pid1') — restarting WSL..."
    wsl --shutdown
    Start-Sleep -Seconds 3
}

# Start WSL in the user session. We are already in the non-elevated branch so
# Start-Process here correctly targets the user's session (not admin-isolated).
Write-Step "Starting WSL in background (user session)..."
Start-Process "wsl.exe" -ArgumentList "--distribution $Distro --exec dbus-launch true" -WindowStyle Hidden
Start-Sleep -Seconds 5

# Wait for systemd, then enable+start Docker and bring the stack up.
Write-Step "Waiting for systemd to initialize inside $Distro (up to 60 s)..."
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 3
    $state = (wsl -d $Distro -- bash -c "systemctl is-system-running 2>/dev/null" 2>$null) -join ""
    if ($state -match "running|degraded") { $ready = $true; break }
}

if ($ready) {
    # Confirm systemd is actually PID 1 (not just sysvinit reporting "running")
    $finalPid1 = (wsl -d $Distro -- bash -c "ps -p 1 -o comm= 2>/dev/null" 2>$null) -join ""
    $finalPid1 = $finalPid1.Trim()
    if ($finalPid1 -notmatch "systemd") {
        Write-Warn "systemd still not PID 1 — check that /etc/wsl.conf contains [boot] / systemd=true"
        Write-Warn "Run: wsl -d $Distro -- cat /etc/wsl.conf"
    } else {
        Write-Ok "systemd is PID 1."
    }
    Write-Step "Enabling and starting Docker service..."
    wsl -d $Distro -- bash -c "sudo systemctl enable --now docker >> /tmp/py_captions_install.log 2>&1"
    Start-Sleep -Seconds 5
    Write-Step "Starting container..."
    wsl -d $Distro -- bash -c "DEPLOY=`$(grep -o 'AUTOSTART_DEPLOY_DIR=[^ ]*' ~/.bashrc 2>/dev/null | head -1 | cut -d= -f2); [ -d `"`$DEPLOY`" ] && docker compose -f `"`$DEPLOY/docker-compose.yml`" up -d >> /tmp/py_captions_install.log 2>&1 || true"
    Write-Ok "Docker is running. py-captions-for-channels will be up in ~15 seconds."
} else {
    Write-Warn "systemd did not report ready within 60 s — Docker may need a moment."
}

Write-Host ""
Write-Host "  Web dashboard:         http://localhost:8000" -ForegroundColor White
Write-Host "  Startup task:          registered (runs at every Windows login)" -ForegroundColor DarkGray
Write-Host ""
Write-Ok "All done — open http://localhost:8000 in your browser"
