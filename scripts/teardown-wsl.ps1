# teardown-wsl.ps1 — Remove the py-captions-for-channels installation
#
# Removes only py-captions artifacts — your WSL distro and everything
# else inside it are left completely untouched.
#
# What is removed:
#   Inside WSL:
#     - Docker container py-captions-for-channels + its volumes
#     - Deploy directory (default: ~/py-captions-for-channels)
#     - /etc/sudoers.d/py-captions
#     - ~/.bashrc autostart block added by the installer
#   On Windows:
#     - Task Scheduler task 'py-captions-wsl-autostart'
#     - Firewall rules (ports 8000, 9000)
#     - netsh portproxy rules (ports 8000, 9000)
#     - Optionally: the Windows clone directory
#
# The WSL distro itself is NEVER touched.
#
# Usage:
#   .\scripts\teardown-wsl.ps1
#   .\scripts\teardown-wsl.ps1 -Distro Ubuntu-24.04
#   .\scripts\teardown-wsl.ps1 -DeployDir "~/my-install-dir"
# ---------------------------------------------------------------------------
param(
    [string]$Distro    = "Ubuntu-22.04",
    [string]$DeployDir = "~/py-captions-for-channels",   # Linux path inside WSL
    [switch]$ElevatedOnly          # internal: re-launched elevated to do privileged removals
)

$ErrorActionPreference = "Stop"
$TaskName = "py-captions-wsl-autostart"

function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Skip($msg) { Write-Host "  $msg" -ForegroundColor DarkGray }

# Ensure Ctrl+C actually stops the script rather than being swallowed.
[Console]::TreatControlCAsInput = $false
trap { Write-Host ""; Write-Host "  Aborted." -ForegroundColor Yellow; exit 1 }

# If we are running from inside the clone directory, step out now.
# Trying to delete a directory that is an ancestor of the CWD fails on Windows.
$_scriptParent = Split-Path -Parent $PSCommandPath   # …/py-captions-for-channels/scripts
$_repoRoot     = Split-Path -Parent $_scriptParent    # …/py-captions-for-channels
if ($PWD.Path -like "$_repoRoot*") {
    Write-Host "  (Stepping out of repo directory before teardown)" -ForegroundColor DarkGray
    Set-Location (Split-Path -Parent $_repoRoot)
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]"Administrator")

# ── Elevated branch: remove firewall rules + portproxy ───────────────────
# Only enter this branch when explicitly re-launched with -ElevatedOnly.
# Checking $ElevatedOnly (not $isAdmin) ensures that a user who happens to
# run the script as admin still gets the full WSL-cleanup + clone-removal flow.
if ($ElevatedOnly) {
    # Scheduled task
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Ok "Scheduled task '$TaskName' removed."
    } else {
        Write-Skip "Scheduled task '$TaskName' — not found, skipping."
    }

    # Firewall rules
    foreach ($name in @("py-captions Web UI", "py-captions Webhook")) {
        if (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) {
            Remove-NetFirewallRule -DisplayName $name
            Write-Ok "Firewall rule '$name' removed."
        } else {
            Write-Skip "Firewall rule '$name' — not found, skipping."
        }
    }

    # Portproxy rules
    $proxyRemoved = $false
    foreach ($port in @(8000, 9000)) {
        $existing = netsh interface portproxy show v4tov4 2>$null |
                    Select-String "0\.0\.0\.0\s+$port"
        if ($existing) {
            netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 | Out-Null
            $proxyRemoved = $true
        }
    }
    if ($proxyRemoved) {
        Write-Ok "Portproxy rules for ports 8000 and 9000 removed."
    } else {
        Write-Skip "Portproxy rules — not found, skipping."
    }

    exit 0
}

# ── Non-elevated branch ───────────────────────────────────────────────────
Write-Host ""
Write-Host "  py-captions-for-channels — Teardown" -ForegroundColor Red
Write-Host ""
Write-Host "  This will remove:" -ForegroundColor White
Write-Host "    • Docker container 'py-captions-for-channels' (inside $Distro)" -ForegroundColor White
Write-Host "    • Deploy directory '$DeployDir' (inside $Distro)" -ForegroundColor White
Write-Host "    • Windows Task Scheduler task '$TaskName'" -ForegroundColor White
Write-Host "    • Windows Firewall rules (ports 8000, 9000)" -ForegroundColor White
Write-Host "    • netsh portproxy rules (ports 8000, 9000)" -ForegroundColor White
Write-Host ""
Write-Host "  Your WSL distro '$Distro' and its contents will NOT be touched." -ForegroundColor DarkGray
Write-Host ""
$confirm = Read-Host "  Type YES to continue"
if ($confirm -ne "YES") {
    Write-Host "  Aborted." -ForegroundColor Yellow
    exit 0
}
Write-Host ""

# ── Step 1: WSL-side cleanup (container + deploy dir) ────────────────────
$distroInstalled = wsl -l -q 2>&1 |
    ForEach-Object { ($_ -replace "`0", "").Trim() } |
    Where-Object { $_ -match [regex]::Escape($Distro) }

# ── Step 1a: Stop and remove the Docker container while WSL is still up ──
# Must happen BEFORE wsl --shutdown.  If we just shutdown WSL, Docker records
# the container as "stopped unexpectedly" and restart: unless-stopped fires it
# again on the next WSL start — leaving a stale container running before setup.
if ($distroInstalled) {
    Write-Step "Stopping and removing py-captions container and volumes (inside $Distro)..."
    wsl -d $Distro -- bash -c "
        if command -v docker &>/dev/null; then
            docker stop  py-captions-for-channels 2>/dev/null || true
            docker rm    py-captions-for-channels 2>/dev/null || true
            docker rmi   ghcr.io/jay3702/py-captions-for-channels:latest 2>/dev/null || true
            # Remove the named media volume — it stores driver_opts (device path) at creation
            # time and does NOT update when .env changes.  Stale device paths cause
            # 'no such file or directory' on the next compose up.
            docker volume rm py-captions-for-channels_channels_media 2>/dev/null || true
        fi
        exit 0" 2>$null | Out-Null
    Write-Ok "Container, image, and media volume removed."
}

# ── Step 1b: Shut down WSL ────────────────────────────────────────────────
# Kill Docker, unmount NAS shares, and release all file locks before we try
# to delete anything.  WSL restarts automatically when we run the next wsl command.
Write-Step "Shutting down WSL (releases file locks)..."
wsl --shutdown 2>$null | Out-Null
Start-Sleep -Seconds 3
Write-Ok "WSL stopped."

# ── Step 2: WSL-side file cleanup (deploy dir + sudoers + .bashrc) ────────
if ($distroInstalled) {
    # Replace leading ~ with $HOME so bash expands it correctly.
    # Tilde is NOT expanded inside single-quoted bash strings.
    $LinuxDeployDir = $DeployDir -replace '^~', '$HOME'

    Write-Step "Removing deploy directory '$DeployDir' (inside $Distro)..."
    # Access via the Windows \\wsl.localhost path — no need to start systemd or sudo.
    # Convert ~/foo  →  \\wsl.localhost\Distro\home\user\foo
    $wslUser = (wsl -d $Distro -- bash -c "echo \$USER" 2>$null) -join "" | ForEach-Object { $_.Trim() }
    $linuxRelPath = ($DeployDir -replace '^~/', "home/$wslUser/") -replace '/', '\'
    $winPath = "\\wsl.localhost\$Distro\$linuxRelPath"
    if (Test-Path $winPath) {
        Remove-Item -Recurse -Force $winPath -ErrorAction SilentlyContinue
        if (Test-Path $winPath) {
            # Some files may be owned by root (Docker data/) — fall back to wsl rm
            wsl -d $Distro -- bash -c "rm -rf `"$LinuxDeployDir`" 2>/dev/null; exit 0" 2>$null | Out-Null
        }
    }
    Write-Ok "Deploy directory removed."

    Write-Step "Removing .bashrc autostart block (inside $Distro)..."
    wsl -d $Distro -- bash -c "sed -i '/# .*py-captions auto-start/,/# -\{20,\}/d' ~/.bashrc 2>/dev/null; exit 0" 2>$null | Out-Null
    Write-Ok ".bashrc cleaned."
    Write-Skip "(leaving /etc/sudoers.d/py-captions — it is harmless and overwritten on reinstall)"
} else {
    Write-Skip "Distro '$Distro' not installed — skipping WSL-side cleanup."
}

# ── Step 3: Elevated removals (task + firewall + portproxy) ──────────────
if ($isAdmin) {
    # Already elevated — run inline rather than spawning a redundant UAC prompt.
    Write-Step "Removing task, firewall rules, and portproxy..."
    & $PSCommandPath -Distro $Distro -ElevatedOnly
} else {
    Write-Step "Requesting administrator rights to remove task, firewall rules, and portproxy..."
    Start-Process powershell -Verb RunAs `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Distro `"$Distro`" -ElevatedOnly" `
        -Wait
}

# Offer to remove the Windows clone directory.
# Use $_repoRoot (where this script actually lives) rather than a hardcoded path.
Write-Host ""
$cloneDir = $_repoRoot
if (Test-Path $cloneDir) {
    $rmClone = Read-Host "  Remove Windows clone directory '$cloneDir'? [Y/n]"
    if ($rmClone -notmatch "^[Nn]") {
        Set-Location $env:USERPROFILE
        Remove-Item -Recurse -Force $cloneDir
        Write-Ok "Clone directory removed."
    } else {
        Write-Skip "Clone directory kept."
    }
}

Write-Host ""
Write-Ok "Teardown complete."
Write-Host "  Your WSL distro '$Distro' is intact." -ForegroundColor DarkGray
Write-Host "  To reinstall, run:" -ForegroundColor DarkGray
Write-Host "    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass" -ForegroundColor DarkGray
Write-Host "    .\scripts\setup-wsl.ps1" -ForegroundColor DarkGray
Write-Host ""
