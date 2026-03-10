# autostart.ps1 — Register (or re-register) the Windows startup task for py-captions-for-channels
#
# Creates a Windows Task Scheduler task that starts the WSL2 distro automatically,
# either at system BOOT (before anyone logs in) or at user LOGON.
#
#   Boot mode:  fires at Windows startup — best for always-on / server machines.
#               Requires storing your Windows password (encrypted in LSA secrets).
#               Note: WSL2 distros are registered per-user, so the task must run
#               as your Windows account — a dedicated service account won't work.
#
#   Logon mode: fires when you sign in — simpler, no password needed.
#
# Usage (PowerShell, any directory):
#   .\scripts\autostart.ps1
#   .\scripts\autostart.ps1 -Distro Ubuntu-24.04
# ---------------------------------------------------------------------------
param(
    [string]$Distro      = "Ubuntu-22.04",
    [string]$TriggerType = "",     # "Boot" or "Logon"; empty = ask interactively
    [switch]$RegisterOnly          # internal: re-launched elevated to register task
)

$ErrorActionPreference = "Stop"
$TaskName = "py-captions-wsl-autostart"

function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]"Administrator")

# ── Elevated branch: ONLY register the task, then exit ───────────────────
# We must not touch WSL from this elevated process — WSL launched from an Admin
# context runs in an isolated session and dies when the UAC window closes.
if ($isAdmin) {
    $action   = New-ScheduledTaskAction -Execute "wsl.exe" `
                    -Argument "--distribution $Distro --exec dbus-launch true"
    $settings = New-ScheduledTaskSettingsSet `
                    -StartWhenAvailable `
                    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
                    -MultipleInstances IgnoreNew

    if ($TriggerType -eq "Boot") {
        # ── At-boot: fires before anyone logs in ─────────────────────────
        # Task Scheduler needs stored credentials because there is no interactive
        # session at boot time.  The password is encrypted by Windows (LSA secrets)
        # and never transmitted anywhere.
        Write-Host ""
        Write-Host "  Task will fire at system BOOT, before anyone logs in." -ForegroundColor White
        Write-Host ""
        Write-Host "  WSL2 distros are registered per-user, so the task must run as:" -ForegroundColor DarkGray
        Write-Host "    $env:USERDOMAIN\$env:USERNAME" -ForegroundColor White
        Write-Host "  Your password will be stored encrypted by Windows (LSA secrets)." -ForegroundColor DarkGray
        Write-Host ""

        # Prompt and validate Windows password
        Add-Type -AssemblyName System.DirectoryServices.AccountManagement
        $ctx = [System.DirectoryServices.AccountManagement.PrincipalContext]::new(
                   [System.DirectoryServices.AccountManagement.ContextType]::Machine)

        $plain     = $null
        $validated = $false
        while (-not $validated) {
            $secPwd = Read-Host "  Windows password for $env:USERNAME" -AsSecureString
            $bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPwd)
            $plain  = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

            $validated = $ctx.ValidateCredentials($env:USERNAME, $plain)
            if (-not $validated) { Write-Warn "Incorrect password — try again." }
        }

        Write-Step "Registering at-boot startup task '$TaskName'..."
        $trigger = New-ScheduledTaskTrigger -AtStartup

        Register-ScheduledTask `
            -TaskName    $TaskName `
            -Action      $action `
            -Trigger     $trigger `
            -Settings    $settings `
            -RunLevel    Highest `
            -User        "$env:USERDOMAIN\$env:USERNAME" `
            -Password    $plain `
            -Description "Starts WSL2 ($Distro) at system boot for py-captions-for-channels (runs before login)" `
            -Force | Out-Null

        # Wipe plaintext password from memory immediately
        $plain = $null
        [GC]::Collect()

        Write-Ok "Startup task registered — fires at system boot (before login)."

    } else {
        # ── At-logon: fires when the user signs in — no password needed ──
        Write-Step "Registering at-logon startup task '$TaskName'..."
        $trigger = New-ScheduledTaskTrigger -AtLogOn

        Register-ScheduledTask `
            -TaskName    $TaskName `
            -Action      $action `
            -Trigger     $trigger `
            -Settings    $settings `
            -Description "Wakes WSL2 ($Distro) at logon so py-captions-for-channels runs without a terminal" `
            -Force | Out-Null

        Write-Ok "Startup task registered — fires at Windows logon."
    }

    exit 0
}

# ── Non-elevated branch ───────────────────────────────────────────────────

# Ask when the task should fire, unless already decided (e.g. called from setup script)
if (-not $TriggerType) {
    Write-Host ""
    Write-Host "  When should py-captions-for-channels start after a reboot?" -ForegroundColor White
    Write-Host ""
    Write-Host "  [B] At system BOOT  (recommended for always-on / server machines)" -ForegroundColor Cyan
    Write-Host "      Starts before anyone logs in." -ForegroundColor DarkGray
    Write-Host "      Requires storing your Windows password in Task Scheduler" -ForegroundColor DarkGray
    Write-Host "      (encrypted by Windows, never leaves this machine)." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  [L] At LOGON  (simpler — no password needed)" -ForegroundColor Cyan
    Write-Host "      Starts when you sign in to Windows." -ForegroundColor DarkGray
    Write-Host ""
    $choice = ""
    while ($choice -notmatch "^[BbLl]$") {
        $choice = Read-Host "  Enter B or L"
    }
    $TriggerType = if ($choice -match "^[Bb]$") { "Boot" } else { "Logon" }
}

# Re-launch elevated to register the task.
# Password prompt (for Boot mode) happens inside the elevated UAC window.
Write-Step "Requesting administrator rights to register the startup task..."
Start-Process powershell -Verb RunAs `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Distro `"$Distro`" -TriggerType `"$TriggerType`" -RegisterOnly" `
    -Wait

# ── Restart WSL if systemd is not yet PID 1 ──────────────────────────────
$pid1 = (wsl -d $Distro -- bash -c "ps -p 1 -o comm= 2>/dev/null" 2>$null) -join ""
$pid1 = $pid1.Trim()

if ($pid1 -notmatch "systemd") {
    Write-Warn "systemd is not yet PID 1 (current: '$pid1') — restarting WSL..."
    wsl --shutdown
    Start-Sleep -Seconds 3
}

# Start WSL in the user session (non-elevated = correct session, won't die on window close).
Write-Step "Starting WSL in background (user session)..."
Start-Process "wsl.exe" -ArgumentList "--distribution $Distro --exec dbus-launch true" -WindowStyle Hidden
Start-Sleep -Seconds 5

# Wait for systemd to become ready.
Write-Step "Waiting for systemd to initialize inside $Distro (up to 60 s)..."
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 3
    $state = (wsl -d $Distro -- bash -c "systemctl is-system-running 2>/dev/null" 2>$null) -join ""
    if ($state -match "running|degraded") { $ready = $true; break }
}

if ($ready) {
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

$taskNote = if ($TriggerType -eq "Boot") { "at system boot (before login)" } else { "at Windows logon" }
Write-Host ""
Write-Host "  Web dashboard:  http://localhost:8000" -ForegroundColor White
Write-Host "  Startup task:   registered ($taskNote)" -ForegroundColor DarkGray
Write-Host ""
Write-Ok "All done — open http://localhost:8000 in your browser"
