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
if ($isAdmin) {
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

# ── Step 1: Shut down WSL first ───────────────────────────────────────────
# Kill Docker, unmount NAS shares, and release all file locks before we try
# to delete anything.  WSL restarts automatically when we run the next wsl command.
Write-Step "Shutting down WSL (stops Docker and releases all file locks)..."
wsl --shutdown 2>$null | Out-Null
Start-Sleep -Seconds 3
Write-Ok "WSL stopped."

# ── Step 2: WSL-side file cleanup (deploy dir + sudoers + .bashrc) ────────
if ($distroInstalled) {
    Write-Step "Removing deploy directory '$DeployDir' (inside $Distro)..."
    wsl -d $Distro -- bash -c "rm -rf '$DeployDir' 2>/dev/null; exit 0" 2>$null | Out-Null
    Write-Ok "Deploy directory removed."

    Write-Step "Removing .bashrc autostart block (inside $Distro)..."
    wsl -d $Distro -- bash -c "sed -i '/# .*py-captions auto-start/,/# -\{20,\}/d' ~/.bashrc 2>/dev/null; exit 0" 2>$null | Out-Null
    Write-Ok ".bashrc cleaned."
    Write-Skip "(leaving /etc/sudoers.d/py-captions — it is harmless and overwritten on reinstall)"
} else {
    Write-Skip "Distro '$Distro' not installed — skipping WSL-side cleanup."
}

# ── Step 3: Elevated removals (task + firewall + portproxy) ──────────────
Write-Step "Requesting administrator rights to remove task, firewall rules, and portproxy..."
Start-Process powershell -Verb RunAs `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Distro `"$Distro`" -ElevatedOnly" `
    -Wait

# Offer to remove the Windows clone directory
Write-Host ""
$cloneDir = "$env:USERPROFILE\Documents\py-captions-for-channels"
if (Test-Path $cloneDir) {
    $rmClone = Read-Host "  Remove Windows clone directory '$cloneDir'? [y/N]"
    if ($rmClone -match "^[Yy]$") {
        # Step out to USERPROFILE in case CWD is still inside the clone dir.
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
Write-Host "    .\scripts\setup-gpu-wsl.ps1" -ForegroundColor DarkGray
Write-Host ""
