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
# Also configures Windows Firewall and LAN access so the web UI is reachable
# from other devices on the LAN (e.g. http://koa:8000 from another PC).
#
# LAN strategy (auto-selected):
#   Win 11 22H2+ (build >= 22621):  WSL2 mirrored networking — sets
#     networkingMode=mirrored in .wslconfig so WSL2 shares the host IP.
#     No portproxy needed; works across reboots without any refresh.
#   Windows 10 / older:  netsh portproxy — forwards LAN traffic to the
#     WSL2 VM IP (172.x.x.x), refreshed each startup via a -ProxyOnly
#     elevated re-launch after WSL2 is running.
#
# Must be run in an elevated (Administrator) PowerShell session.
# Right-click PowerShell and choose "Run as Administrator", then re-run:
#   .\scripts\autostart.ps1
#   .\scripts\autostart.ps1 -Distro Ubuntu-24.04
# ---------------------------------------------------------------------------
param(
    [string]$Distro      = "Ubuntu-22.04",
    [string]$TriggerType = "",   # "Boot" or "Logon"; empty = ask interactively
    [switch]$ProxyOnly,          # internal: re-launched elevated just to refresh portproxy rules
    [string]$WslIp       = ""    # internal: WSL2 IP passed to -ProxyOnly
)

$ErrorActionPreference = "Stop"
$TaskName = "py-captions-wsl-autostart"

function Write-Ok($msg)   { Write-Host "OK  $msg" -ForegroundColor Green }
function Write-Step($msg) { Write-Host ">>> $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "!   $msg" -ForegroundColor Yellow }

# ── Require an elevated session — exit clearly if not Administrator ─────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]"Administrator")
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "  This script must be run as Administrator." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Right-click PowerShell and choose 'Run as Administrator'," -ForegroundColor Yellow
    Write-Host "  then run the script again:" -ForegroundColor Yellow
    Write-Host "    .\scripts\autostart.ps1" -ForegroundColor White
    Write-Host ""
    exit 1
}

# ── ProxyOnly: refresh portproxy rules with the current WSL2 VM IP ────────
if ($ProxyOnly) {
    if (-not $WslIp) { exit 1 }
    Write-Step "Refreshing portproxy rules (WSL2 IP: $WslIp)..."
    foreach ($port in @(8000, 9000)) {
        netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
        netsh interface portproxy add    v4tov4 listenport=$port listenaddress=0.0.0.0 `
            connectport=$port connectaddress=$WslIp | Out-Null
    }
    Write-Ok "Portproxy: LAN:8000 and LAN:9000 -> WSL2 ($WslIp)"
    exit 0
}

# ═══════════════════════════════════════════════════════════════════════════
# From here we are running elevated (either directly or via self-elevation).
# WSL commands work fine — self-elevation preserves the user identity so the
# distro is accessible.  Start-Process "wsl.exe" spawns a detached process
# that survives when this elevated window closes.
# ═══════════════════════════════════════════════════════════════════════════

# ── Ask Boot vs Logon ────────────────────────────────────────────────────
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

# ── Firewall rules ────────────────────────────────────────────────────────
foreach ($entry in @(
    @{ Port = 8000; Name = "py-captions Web UI" },
    @{ Port = 9000; Name = "py-captions Webhook" }
)) {
    if (-not (Get-NetFirewallRule -DisplayName $entry.Name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $entry.Name -Direction Inbound `
            -Protocol TCP -LocalPort $entry.Port -Action Allow | Out-Null
        Write-Ok "Firewall: allowed inbound TCP $($entry.Port) ($($entry.Name))"
    }
}

# ── .wslconfig — mirrored networking (Win 11 22H2+) ──────────────────────
$osBuild = [System.Environment]::OSVersion.Version.Build
$useMirrored = $false
if ($osBuild -ge 22621) {
    $wslConfigPath = "$env:USERPROFILE\.wslconfig"
    if (Test-Path $wslConfigPath) {
        $existing = Get-Content $wslConfigPath -Raw
        if ($existing -match 'networkingMode\s*=\s*mirrored') {
            Write-Ok "WSL2 mirrored networking already set in .wslconfig"
            $useMirrored = $true
        } elseif ($existing -match 'networkingMode\s*=') {
            Write-Warn ".wslconfig has a different networkingMode — leaving it unchanged. Portproxy will be used instead."
        } elseif ($existing -match '\[wsl2\]') {
            Set-Content $wslConfigPath ($existing -replace '(\[wsl2\])', "`$1`nnetworkingMode=mirrored")
            Write-Ok "Added networkingMode=mirrored to existing .wslconfig"
            $useMirrored = $true
        } else {
            Add-Content $wslConfigPath "`n[wsl2]`nnetworkingMode=mirrored`n"
            Write-Ok "Appended [wsl2] / networkingMode=mirrored to .wslconfig"
            $useMirrored = $true
        }
    } else {
        Set-Content $wslConfigPath "[wsl2]`nnetworkingMode=mirrored`n"
        Write-Ok "Created .wslconfig with networkingMode=mirrored"
        $useMirrored = $true
    }
    if ($useMirrored) {
        foreach ($port in @(8000, 9000)) {
            netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
        }
    }
}
if (-not $useMirrored) {
    Write-Step "Setting up portproxy placeholder rules for LAN access..."
    foreach ($port in @(8000, 9000)) {
        netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
        netsh interface portproxy add v4tov4 listenport=$port listenaddress=0.0.0.0 `
            connectport=$port connectaddress=127.0.0.1 | Out-Null
    }
    Write-Ok "Portproxy placeholder rules set (will be refreshed with actual WSL2 IP after start)"
}

# ── Register the scheduled task ───────────────────────────────────────────
$action   = New-ScheduledTaskAction -Execute "wsl.exe" `
                -Argument "--distribution $Distro --exec dbus-launch true"
$settings = New-ScheduledTaskSettingsSet `
                -StartWhenAvailable `
                -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
                -MultipleInstances IgnoreNew

if ($TriggerType -eq "Boot") {
    Write-Host ""
    Write-Host "  Task will fire at system BOOT and again at logon (as fallback)." -ForegroundColor White
    Write-Host ""
    Write-Host "  WSL2 distros are registered per-user, so the task must run as:" -ForegroundColor DarkGray
    Write-Host "    $env:USERDOMAIN\$env:USERNAME" -ForegroundColor White
    Write-Host "  Your password will be stored encrypted by Windows (LSA secrets)." -ForegroundColor DarkGray
    Write-Host "  Use your Windows sign-in password — not your PIN." -ForegroundColor Yellow
    Write-Host ""

    $plain      = $null
    $registered = $false
    $attempts   = 0
    while (-not $registered) {
        $attempts++
        if ($attempts -gt 3) {
            Write-Warn "Too many failed attempts — falling back to logon-only mode."
            break
        }
        $secPwd = Read-Host "  Windows password for $env:USERNAME" -AsSecureString
        $bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPwd)
        $plain  = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

        $bootTrigger = New-ScheduledTaskTrigger -AtStartup
        # Delay the boot trigger 30 s — WSL needs the user session infrastructure
        # (Lxss service, user profile) to be ready before wsl.exe will work.
        $bootTrigger.Delay = "PT30S"
        $triggers = @($bootTrigger, (New-ScheduledTaskTrigger -AtLogOn))

        try {
            Register-ScheduledTask `
                -TaskName    $TaskName `
                -Action      $action `
                -Trigger     $triggers `
                -Settings    $settings `
                -RunLevel    Highest `
                -User        "$env:USERDOMAIN\$env:USERNAME" `
                -Password    $plain `
                -Description "Starts WSL2 ($Distro) at boot (+ logon fallback) for py-captions-for-channels" `
                -Force -ErrorAction Stop | Out-Null
            $registered = $true
        } catch {
            Write-Warn "Registration failed: $_"
            Write-Warn "Wrong password? Try again (attempt $attempts/3)."
        }
    }
    $plain = $null; [GC]::Collect()

    if ($registered) {
        Write-Ok "Startup task registered — fires at system boot, with logon as fallback."
        $TriggerType = "Boot"
    } else {
        # Fall back to logon-only
        Register-ScheduledTask `
            -TaskName    $TaskName `
            -Action      $action `
            -Trigger     (New-ScheduledTaskTrigger -AtLogOn) `
            -Settings    $settings `
            -Description "Starts WSL2 ($Distro) at logon for py-captions-for-channels" `
            -Force | Out-Null
        Write-Warn "Registered logon-only task (boot mode requires Windows account password)."
        $TriggerType = "Logon"
    }
} else {
    Register-ScheduledTask `
        -TaskName    $TaskName `
        -Action      $action `
        -Trigger     (New-ScheduledTaskTrigger -AtLogOn) `
        -Settings    $settings `
        -Description "Starts WSL2 ($Distro) at logon for py-captions-for-channels" `
        -Force | Out-Null
    Write-Ok "Startup task registered — fires at Windows logon."
}

# ── Restart WSL to pick up .wslconfig changes, then start container ───────
Write-Step "Restarting WSL to apply configuration..."
wsl --shutdown
Start-Sleep -Seconds 3

$dbusCheck = (wsl -d $Distro -- bash -c "command -v dbus-launch 2>/dev/null" 2>$null) -join ""
if (-not $dbusCheck.Trim()) {
    Write-Step "Installing dbus inside $Distro (required to keep WSL alive)..."
    wsl -d $Distro -- bash -c "sudo apt-get install -y -qq dbus >> /tmp/py_captions_install.log 2>&1"
}

# Start WSL as a detached process — survives when this elevated window closes.
Write-Step "Starting WSL..."
Start-Process "wsl.exe" -ArgumentList "--distribution $Distro --exec dbus-launch true" -WindowStyle Hidden
Start-Sleep -Seconds 5

Write-Step "Waiting for systemd to initialize inside $Distro (up to 60 s)..."
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 3
    $state = (wsl -d $Distro -- bash -c "systemctl is-system-running 2>/dev/null" 2>$null) -join ""
    if ($state -match "running|degraded") { $ready = $true; break }
}

if ($ready) {
    $pid1 = (wsl -d $Distro -- bash -c "ps -p 1 -o comm= 2>/dev/null" 2>$null) -join ""
    if ($pid1.Trim() -notmatch "systemd") {
        Write-Warn "systemd still not PID 1 — check /etc/wsl.conf contains [boot] / systemd=true"
    } else {
        Write-Ok "systemd is PID 1."
    }
    Write-Step "Enabling and starting Docker service..."
    wsl -d $Distro -- bash -c "sudo systemctl enable --now docker >> /tmp/py_captions_install.log 2>&1"
    Start-Sleep -Seconds 5
    # Use bash -i (interactive) so ~/.bashrc is sourced — the py-captions block in
    # .bashrc re-mounts the CIFS share and runs 'mount --make-shared' before
    # 'docker compose up -d'.
    Write-Step "Remounting NAS share and starting container..."
    wsl -d $Distro -- bash -i -c "DEPLOY=`$(grep -o 'AUTOSTART_DEPLOY_DIR=[^ ]*' ~/.bashrc 2>/dev/null | head -1 | cut -d= -f2); [ -d `"`$DEPLOY`" ] && docker compose -f `"`$DEPLOY/docker-compose.yml`" up -d >> /tmp/py_captions_install.log 2>&1 || true"
    Write-Step "Verifying recordings are visible in container..."
    Start-Sleep -Seconds 15
    $chkDep = (wsl -d $Distro -- bash -c "grep -o 'AUTOSTART_DEPLOY_DIR=[^ ]*' ~/.bashrc 2>/dev/null | head -1 | cut -d= -f2" 2>$null) -join ""; $chkDep = $chkDep.Trim()
    if ($chkDep) {
        $chkMmt = (wsl -d $Distro -- bash -c "grep '^DVR_MEDIA_HOST_PATH=' '$chkDep/.env' 2>/dev/null | head -1 | cut -d= -f2-" 2>$null) -join ""; $chkMmt = $chkMmt.Trim().Trim('"')
        if (-not $chkMmt) { $chkMmt = "/mnt/channels" }
        $chkVis = (wsl -d $Distro -- bash -c "docker exec py-captions-for-channels sh -c 'ls $chkMmt 2>/dev/null | wc -l' 2>/dev/null" 2>$null) -join ""; $chkVis = $chkVis.Trim()
        if ($chkVis -eq "0" -and (wsl -d $Distro -- bash -c "mountpoint -q '$chkMmt' 2>/dev/null && echo yes" 2>$null) -match "yes") {
            Write-Warn "Recordings not visible in container ($chkMmt) — CIFS arrived after start. Restarting..."
            wsl -d $Distro -- bash -c "cd '$chkDep' && docker compose down 2>/dev/null && docker compose up -d 2>/dev/null" 2>&1 | Out-Null
            Start-Sleep -Seconds 15
        }
    }
    Write-Ok "Docker is running. py-captions-for-channels will be up in ~15 seconds."
} else {
    Write-Warn "systemd did not report ready within 60 s — Docker may need a moment."
}

# ── Portproxy refresh (non-mirrored only) ─────────────────────────────────
if (-not $useMirrored) {
    Write-Step "Refreshing LAN portproxy rules..."
    $wslIp = ""
    for ($i = 0; $i -lt 10; $i++) {
        $raw = (wsl -d $Distro -- bash -c "hostname -I 2>/dev/null | awk '{print `$1}'" 2>$null) -join ""
        $raw = $raw.Trim()
        if ($raw -match '^\d+\.\d+\.\d+\.\d+$') { $wslIp = $raw; break }
        Start-Sleep -Seconds 3
    }
    if ($wslIp) {
        foreach ($port in @(8000, 9000)) {
            netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
            netsh interface portproxy add    v4tov4 listenport=$port listenaddress=0.0.0.0 `
                connectport=$port connectaddress=$wslIp | Out-Null
        }
        Write-Ok "LAN access configured — other devices can reach http://$(hostname):8000"
    } else {
        Write-Warn "Could not determine WSL2 IP — portproxy skipped. LAN access may not work."
    }
} else {
    Write-Ok "LAN access ready — WSL2 mirrored networking is active (host IP: $(hostname))"
}

$taskNote = if ($TriggerType -eq "Boot") { "at system boot (before login)" } else { "at Windows logon" }
Write-Host ""
Write-Host "  Web dashboard (this machine):  http://localhost:8000" -ForegroundColor White
Write-Host "  Web dashboard (LAN):           http://$(hostname):8000" -ForegroundColor White
Write-Host "  Startup task:                  registered ($taskNote)" -ForegroundColor DarkGray
Write-Host ""
Write-Ok "All done — open http://localhost:8000 in your browser"
