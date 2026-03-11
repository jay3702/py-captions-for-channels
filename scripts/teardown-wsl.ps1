# teardown-wsl.ps1 — Completely remove the py-captions-for-channels WSL installation
#
# Removes everything the installer set up:
#   - Windows Task Scheduler task
#   - Windows Firewall rules
#   - netsh portproxy rules
#   - The WSL2 distro (wsl --unregister) — DESTROYS all data inside it
#   - Optionally: the Windows clone directory
#
# Usage:
#   .\scripts\teardown-wsl.ps1
#   .\scripts\teardown-wsl.ps1 -Distro Ubuntu-24.04
#   .\scripts\teardown-wsl.ps1 -KeepDistro   # remove everything except the WSL distro
# ---------------------------------------------------------------------------
param(
    [string]$Distro      = "Ubuntu-22.04",
    [switch]$KeepDistro,           # skip wsl --unregister (keep WSL distro intact)
    [switch]$ElevatedOnly          # internal: re-launched elevated to do privileged removals
)

$ErrorActionPreference = "Stop"
$TaskName = "py-captions-wsl-autostart"

function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Skip($msg) { Write-Host "  $msg" -ForegroundColor DarkGray }

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
Write-Host "  py-captions-for-channels — Full Teardown" -ForegroundColor Red
Write-Host ""
Write-Host "  This will remove:" -ForegroundColor White
Write-Host "    • Windows Task Scheduler task '$TaskName'" -ForegroundColor White
Write-Host "    • Windows Firewall rules (ports 8000, 9000)" -ForegroundColor White
Write-Host "    • netsh portproxy rules (ports 8000, 9000)" -ForegroundColor White
if (-not $KeepDistro) {
    Write-Host "    • WSL2 distro '$Distro' and ALL data inside it" -ForegroundColor Red
}
Write-Host ""
$confirm = Read-Host "  Type YES to continue"
if ($confirm -ne "YES") {
    Write-Host "  Aborted." -ForegroundColor Yellow
    exit 0
}
Write-Host ""

# Stop WSL first so the distro isn't locked during unregister
Write-Step "Shutting down WSL..."
wsl --shutdown 2>$null | Out-Null
Start-Sleep -Seconds 2
Write-Ok "WSL stopped."

# Elevated removals (task + firewall + portproxy)
Write-Step "Requesting administrator rights to remove task, firewall rules, and portproxy..."
Start-Process powershell -Verb RunAs `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Distro `"$Distro`" -ElevatedOnly" `
    -Wait

# Unregister the WSL distro (destroys all data)
if (-not $KeepDistro) {
    $installed = wsl -l -q 2>&1 |
        ForEach-Object { ($_ -replace "`0", "").Trim() } |
        Where-Object { $_ -match [regex]::Escape($Distro) }

    if ($installed) {
        Write-Step "Unregistering WSL2 distro '$Distro' (this destroys all data inside it)..."
        wsl --unregister $Distro
        Write-Ok "WSL2 distro '$Distro' removed."
    } else {
        Write-Skip "WSL2 distro '$Distro' — not found, skipping."
    }
} else {
    Write-Skip "WSL2 distro '$Distro' — kept (--KeepDistro specified)."
}

# Offer to remove the Windows clone directory
Write-Host ""
$cloneDir = "$env:USERPROFILE\Documents\py-captions-for-channels"
if (Test-Path $cloneDir) {
    $rmClone = Read-Host "  Remove Windows clone directory '$cloneDir'? [y/N]"
    if ($rmClone -match "^[Yy]$") {
        Remove-Item -Recurse -Force $cloneDir
        Write-Ok "Clone directory removed."
    } else {
        Write-Skip "Clone directory kept."
    }
}

Write-Host ""
Write-Ok "Teardown complete. The system is back to a clean state."
Write-Host "  To reinstall, clone the repo and run:" -ForegroundColor DarkGray
Write-Host "    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass" -ForegroundColor DarkGray
Write-Host "    .\scripts\setup-gpu-wsl.ps1" -ForegroundColor DarkGray
Write-Host ""
