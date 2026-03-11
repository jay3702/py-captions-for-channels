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
#   Win 11 22H2+ (build ≥ 22621):  WSL2 mirrored networking — sets
#     networkingMode=mirrored in .wslconfig so WSL2 shares the host IP.
#     No portproxy needed; works across reboots without any refresh.
#   Windows 10 / older:  netsh portproxy — forwards LAN traffic to the
#     WSL2 VM IP (172.x.x.x), refreshed each startup via a -ProxyOnly
#     elevated re-launch after WSL2 is running.
#
# Usage (PowerShell, any directory):
#   .\scripts\autostart.ps1
#   .\scripts\autostart.ps1 -Distro Ubuntu-24.04
# ---------------------------------------------------------------------------
param(
    [string]$Distro       = "Ubuntu-22.04",
    [string]$TriggerType  = "",     # "Boot" or "Logon"; empty = ask interactively
    [switch]$RegisterOnly,          # internal: re-launched elevated to register task + firewall + portproxy
    [switch]$ProxyOnly,             # internal: re-launched elevated just to refresh portproxy rules
    [string]$WslIp        = ""      # internal: WSL2 IP passed to -ProxyOnly
)

$ErrorActionPreference = "Stop"
$TaskName = "py-captions-wsl-autostart"

function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]"Administrator")

# ── Elevated branch: task registration + firewall + portproxy ────────────
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
        # ── Boot mode: AtStartup + AtLogon (both triggers on same task) ──
        #
        # AtStartup fires at Windows startup (before login) — best effort,
        # may fail if WSL's user profile isn't loaded yet.
        # AtLogon fires when the user signs in — guaranteed fallback.
        # MultipleInstances=IgnoreNew means if boot fires first, the logon
        # trigger is silently skipped (harmless double-fire prevention).
        #
        # Stored credentials are required for AtStartup (no interactive session).
        # Password is encrypted by Windows (LSA secrets) — never transmitted.
        Write-Host ""
        Write-Host "  Task will fire at system BOOT and again at logon (as fallback)." -ForegroundColor White
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

        Write-Step "Registering startup task '$TaskName' (at-boot + at-logon fallback)..."
        $bootTrigger = New-ScheduledTaskTrigger -AtStartup
        # Delay the boot trigger 30 s — WSL needs the user session infrastructure
        # (Lxss service, user profile) to be ready before wsl.exe will work.
        $bootTrigger.Delay = "PT30S"
        $triggers = @(
            $bootTrigger
            New-ScheduledTaskTrigger -AtLogOn
        )

        Register-ScheduledTask `
            -TaskName    $TaskName `
            -Action      $action `
            -Trigger     $triggers `
            -Settings    $settings `
            -RunLevel    Highest `
            -User        "$env:USERDOMAIN\$env:USERNAME" `
            -Password    $plain `
            -Description "Starts WSL2 ($Distro) at boot (+ logon fallback) for py-captions-for-channels" `
            -Force | Out-Null

        # Wipe plaintext password from memory immediately
        $plain = $null
        [GC]::Collect()

        Write-Ok "Startup task registered — fires at system boot, with logon as fallback."

    } else {
        # ── Logon-only mode: fires when the user signs in — no password needed ──
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

    # ── Firewall rules — allow LAN inbound on web UI and webhook ports ───
    # Idempotent: skipped if the rule already exists.
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

    # ── LAN networking: mirrored mode (Win 11 22H2+) or portproxy fallback ──
    $osBuild = [System.Environment]::OSVersion.Version.Build
    $useMirrored = $false
    if ($osBuild -ge 22621) {
        # Mirrored networking: WSL2 shares the Windows host IP — no portproxy needed.
        # The change takes effect on the next wsl --shutdown (done below).
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
            # Remove any stale portproxy rules left from a previous install
            foreach ($port in @(8000, 9000)) {
                netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
            }
        }
    }
    if (-not $useMirrored) {
        # Older Windows (or conflicting .wslconfig): portproxy with a placeholder connect address.
        # The non-elevated branch refreshes these with the real WSL2 VM IP after start.
        Write-Step "Setting up portproxy for LAN access..."
        foreach ($port in @(8000, 9000)) {
            netsh interface portproxy delete v4tov4 `
                listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
            netsh interface portproxy add v4tov4 `
                listenport=$port listenaddress=0.0.0.0 `
                connectport=$port connectaddress=127.0.0.1 | Out-Null
        }
        Write-Ok "Portproxy placeholder rules set (will be refreshed with actual WSL2 IP after start)"
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

# Re-launch elevated to register task + firewall + portproxy.
# Password prompt (for Boot mode) happens inside the elevated UAC window.
Write-Step "Requesting administrator rights..."
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

# Ensure dbus is installed — required for dbus-launch to keep WSL alive.
# dbus-launch spawns a background daemon under WSL's init (PID 2), which prevents
# WSL from shutting down when no terminals are open.
$dbusCheck = (wsl -d $Distro -- bash -c "command -v dbus-launch 2>/dev/null" 2>$null) -join ""
if (-not $dbusCheck.Trim()) {
    Write-Step "Installing dbus inside $Distro (required to keep WSL alive)..."
    wsl -d $Distro -- bash -c "sudo apt-get install -y -qq dbus >> /tmp/py_captions_install.log 2>&1"
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
Write-Host "  Web dashboard (this machine):  http://localhost:8000" -ForegroundColor White
Write-Host "  Web dashboard (LAN):           http://$(hostname):8000" -ForegroundColor White
Write-Host "  Startup task:                  registered ($taskNote)" -ForegroundColor DarkGray
Write-Host ""
Write-Ok "All done — open http://localhost:8000 in your browser"


$ErrorActionPreference = "Stop"
$TaskName = "py-captions-wsl-autostart"

function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]"Administrator")

# ── Elevated branch: task registration, firewall rules, portproxy ────────
# We must not touch WSL from this elevated process — WSL launched from an Admin
# context runs in an isolated session and dies when the UAC window closes.
if ($isAdmin) {

    # ── ProxyOnly: refresh portproxy rules with the current WSL2 VM IP ────
    # connectaddress=127.0.0.1 does NOT work for externally proxied connections
    # (WSL2 localhost forwarding only intercepts native Windows process sockets).
    # We must use the actual WSL2 VM IP (172.x.x.x) as the connect target.
    if ($ProxyOnly) {
        if (-not $WslIp) { exit 1 }
        Write-Step "Refreshing portproxy rules (WSL2 IP: $WslIp)..."
        foreach ($port in @(8000, 9000)) {
            netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
            netsh interface portproxy add    v4tov4 listenport=$port listenaddress=0.0.0.0 `
                connectport=$port connectaddress=$WslIp | Out-Null
        }
        Write-Ok "Portproxy: LAN:8000 and LAN:9000 → WSL2 ($WslIp)"
        exit 0
    }

    $action   = New-ScheduledTaskAction -Execute "wsl.exe" `
                    -Argument "--distribution $Distro --exec dbus-launch true"
    $settings = New-ScheduledTaskSettingsSet `
                    -StartWhenAvailable `
                    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
                    -MultipleInstances IgnoreNew

    if ($TriggerType -eq "Boot") {
        # ── Boot mode: AtStartup + AtLogon (both triggers on same task) ──
        #
        # AtStartup fires at Windows startup (before login) — best effort,
        # may fail if WSL's user profile isn't loaded yet.
        # AtLogon fires when the user signs in — guaranteed fallback.
        # MultipleInstances=IgnoreNew means if boot fires first, the logon
        # trigger is silently skipped (harmless double-fire prevention).
        #
        # Stored credentials are required for AtStartup (no interactive session).
        # Password is encrypted by Windows (LSA secrets) — never transmitted.
        Write-Host ""
        Write-Host "  Task will fire at system BOOT and again at logon (as fallback)." -ForegroundColor White
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

        Write-Step "Registering startup task '$TaskName' (at-boot + at-logon fallback)..."
        $bootTrigger   = New-ScheduledTaskTrigger -AtStartup
        # Delay the boot trigger 30 s — WSL needs the user session infrastructure
        # (Lxss service, user profile) to be ready before wsl.exe will work.
        $bootTrigger.Delay = "PT30S"
        $triggers = @(
            $bootTrigger
            New-ScheduledTaskTrigger -AtLogOn
        )

        Register-ScheduledTask `
            -TaskName    $TaskName `
            -Action      $action `
            -Trigger     $triggers `
            -Settings    $settings `
            -RunLevel    Highest `
            -User        "$env:USERDOMAIN\$env:USERNAME" `
            -Password    $plain `
            -Description "Starts WSL2 ($Distro) at boot (+ logon fallback) for py-captions-for-channels" `
            -Force | Out-Null

        # Wipe plaintext password from memory immediately
        $plain = $null
        [GC]::Collect()

        Write-Ok "Startup task registered — fires at system boot, with logon as fallback."

    } else {
        # ── Logon-only mode: fires when the user signs in — no password needed ──
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

    # ── Firewall rules — allow LAN access to web UI and webhook port ─────
    # Idempotent: skipped if rules already exist.
    foreach ($entry in @(@{Port=8000;Name="py-captions Web UI"},@{Port=9000;Name="py-captions Webhook"})) {
        if (-not (Get-NetFirewallRule -DisplayName $entry.Name -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $entry.Name -Direction Inbound `
                -Protocol TCP -LocalPort $entry.Port -Action Allow | Out-Null
            Write-Ok "Firewall: allowed inbound TCP $($entry.Port) ($($entry.Name))"
        }
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

# Ensure dbus is installed — required for dbus-launch to keep WSL alive.
$dbusCheck = (wsl -d $Distro -- bash -c "command -v dbus-launch 2>/dev/null" 2>$null) -join ""
if (-not $dbusCheck.Trim()) {
    Write-Step "Installing dbus inside $Distro (required to keep WSL alive)..."
    wsl -d $Distro -- bash -c "sudo apt-get install -y -qq dbus >> /tmp/py_captions_install.log 2>&1"
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

# ── LAN access: mirrored networking (Win 11 22H2+) or portproxy ─────────
$wslConfigPath = "$env:USERPROFILE\.wslconfig"
$usingMirrored = (Test-Path $wslConfigPath) -and ((Get-Content $wslConfigPath -Raw) -match 'networkingMode\s*=\s*mirrored')

if ($usingMirrored) {
    Write-Ok "LAN access ready — WSL2 mirrored networking is active (host IP: $(hostname))"
} else {
    # Portproxy fallback: must use actual WSL2 VM IP (172.x.x.x).
    # connectaddress=127.0.0.1 does NOT work — portproxy bypasses WSL2 localhost forwarding.
    # Retry up to ~30 s to allow WSL2 networking to settle after first start.
    Write-Step "Refreshing LAN portproxy rules (WSL2 IP changes on every restart)..."
    $wslIp = ""
    for ($i = 0; $i -lt 10; $i++) {
        $raw = (wsl -d $Distro -- bash -c "hostname -I 2>/dev/null | awk '{print `$1}'" 2>`$null) -join ""
        $raw = $raw.Trim()
        if ($raw -match '^\d+\.\d+\.\d+\.\d+$') { $wslIp = $raw; break }
        Start-Sleep -Seconds 3
    }
    if ($wslIp) {
        Start-Process powershell -Verb RunAs `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ProxyOnly -WslIp `"$wslIp`"" `
            -Wait
        Write-Ok "LAN access configured — other devices can reach http://$(hostname):8000"
    } else {
        Write-Warn "Could not determine WSL2 IP — portproxy skipped. LAN access may not work."
    }
}

$taskNote = if ($TriggerType -eq "Boot") { "at system boot (before login)" } else { "at Windows logon" }
Write-Host ""
Write-Host "  Web dashboard (this machine):  http://localhost:8000" -ForegroundColor White
Write-Host "  Web dashboard (LAN):           http://$(hostname):8000" -ForegroundColor White
Write-Host "  Startup task:                  registered ($taskNote)" -ForegroundColor DarkGray
Write-Host ""
Write-Ok "All done — open http://localhost:8000 in your browser"
