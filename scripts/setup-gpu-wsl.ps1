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

# ════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  py-captions-for-channels — pre-flight checks" -ForegroundColor White
Write-Host ""

# ── Virtualization enabled ────────────────────────────────────────────────
Write-Step "Checking CPU virtualization..."
try {
    $virtEnabled = (Get-ComputerInfo -Property HyperVRequirementVirtualizationFirmwareEnabled 2>$null).HyperVRequirementVirtualizationFirmwareEnabled
    if ($virtEnabled -eq $false) {
        Write-Fail "CPU virtualization is disabled in firmware.`n  WSL2 requires VT-x/AMD-V.`n  Enable it in your BIOS/UEFI settings, then re-run this script."
    }
} catch { <# ComputerInfo may not have this field on all SKUs — skip #> }
Write-Ok "CPU virtualization OK"

# ── Disk space (need ~15 GB for distro + Docker images) ──────────────────
Write-Step "Checking disk space..."
$drive = $env:SystemDrive
$disk  = Get-PSDrive ($drive.TrimEnd(':')) -ErrorAction SilentlyContinue
if ($disk -and $disk.Free -lt 15GB) {
    $freeGB = [math]::Round($disk.Free / 1GB, 1)
    Write-Warn "Only ${freeGB} GB free on $drive — recommend at least 15 GB for WSL2 + Docker images."
    $cont = Read-Host "  Continue anyway? [y/N]"
    if ($cont -notmatch "^[Yy]") { exit 0 }
} else {
    Write-Ok "Disk space OK"
}

# ── Network adapter profile (Public blocks inbound firewall rules) ─────────
Write-Step "Checking network adapter profile..."
$publicAdapters = Get-NetConnectionProfile -ErrorAction SilentlyContinue |
    Where-Object { $_.NetworkCategory -eq 'Public' }
if ($publicAdapters) {
    Write-Host ""
    Write-Warn "One or more network adapters are set to 'Public':"
    $publicAdapters | ForEach-Object { Write-Host "    $($_.InterfaceAlias) — $($_.Name)" -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "  Windows Firewall blocks inbound connections on Public networks" -ForegroundColor White
    Write-Host "  even with explicit Allow rules. Setting to Private enables LAN access." -ForegroundColor White
    Write-Host ""
    $fix = Read-Host "  Switch to Private now? [Y/n]"
    if ($fix -notmatch "^[Nn]") {
        $publicAdapters | ForEach-Object {
            Set-NetConnectionProfile -InterfaceAlias $_.InterfaceAlias -NetworkCategory Private -ErrorAction SilentlyContinue
        }
        Write-Ok "Network adapters set to Private"
    } else {
        Write-Warn "Skipped — LAN access to the web UI may not work."
    }
} else {
    Write-Ok "Network adapter profile OK"
}

# ── Ports 8000 / 9000 in use on Windows ──────────────────────────────────
Write-Step "Checking ports 8000 and 9000..."
$usedPorts = @()
foreach ($port in @(8000, 9000)) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { $usedPorts += $port }
}
if ($usedPorts) {
    Write-Warn "Port(s) already in use on Windows: $($usedPorts -join ', ')"
    Write-Warn "This usually means a previous py-captions install is still running."
    Write-Host ""
    Write-Host "  Options:" -ForegroundColor White
    Write-Host "    C = Clean up automatically (stop container + remove portproxy rules)" -ForegroundColor White
    Write-Host "    S = Skip / continue anyway" -ForegroundColor White
    Write-Host "    Q = Quit" -ForegroundColor White
    Write-Host ""
    $portChoice = Read-Host "  Choice [C/s/q]"
    if ($portChoice -match "^[Qq]") { Write-Host "  Aborted." -ForegroundColor Yellow; exit 0 }
    if ($portChoice -notmatch "^[Ss]") {
        # Auto-cleanup: stop the Docker container and remove portproxy rules.
        # Portproxy removal requires elevation; if we are not admin, re-launch elevated.
        Write-Step "Stopping py-captions container (inside WSL)..."
        $stopScript = 'cd ~/py-captions-for-channels 2>/dev/null && docker compose down 2>/dev/null; docker stop py-captions-for-channels 2>/dev/null; exit 0'
        wsl -d $Distro -- bash -c $stopScript 2>$null | Out-Null
        Write-Ok "Container stopped."

        $isAdminNow = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
                          [Security.Principal.WindowsBuiltInRole]"Administrator")
        if ($isAdminNow) {
            foreach ($port in @(8000, 9000)) {
                $existing = netsh interface portproxy show v4tov4 2>$null | Select-String "0\.0\.0\.0\s+$port"
                if ($existing) {
                    netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 | Out-Null
                }
            }
            Write-Ok "Portproxy rules for ports 8000 and 9000 removed."
        } else {
            Write-Step "Requesting administrator rights to remove portproxy rules..."
            $elevatedCmd = 'foreach ($p in @(8000,9000)) { $e = netsh interface portproxy show v4tov4 2>$null | Select-String "0\.0\.0\.0\s+$p"; if ($e) { netsh interface portproxy delete v4tov4 listenport=$p listenaddress=0.0.0.0 | Out-Null } }; Write-Host "Portproxy rules removed." -ForegroundColor Green; Start-Sleep 2'
            Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"$elevatedCmd`"" -Wait
        }

        # Re-check
        $stillUsed = @()
        foreach ($port in @(8000, 9000)) {
            $conn2 = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conn2) { $stillUsed += $port }
        }
        if ($stillUsed) {
            Write-Warn "Port(s) still in use: $($stillUsed -join ', ') — another process may be using them."
            $cont = Read-Host "  Continue anyway? [y/N]"
            if ($cont -notmatch "^[Yy]") { exit 0 }
        } else {
            Write-Ok "Ports 8000 and 9000 are now free."
        }
    }
} else {
    Write-Ok "Ports 8000 and 9000 are free"
}

# ── .wslconfig networkingMode conflict ────────────────────────────────────
Write-Step "Checking .wslconfig..."
$wslConfigPath = "$env:USERPROFILE\.wslconfig"
if (Test-Path $wslConfigPath) {
    $wslConfigRaw = Get-Content $wslConfigPath -Raw
    if ($wslConfigRaw -match 'networkingMode\s*=\s*(?!mirrored)(\S+)') {
        $currentMode = $Matches[1]
        Write-Warn ".wslconfig has networkingMode=$currentMode"
        Write-Host "  Mirrored networking is recommended for reliable LAN access." -ForegroundColor White
        $fix = Read-Host "  Switch networkingMode to mirrored? [Y/n]"
        if ($fix -notmatch "^[Nn]") {
            (Get-Content $wslConfigPath -Raw) -replace 'networkingMode\s*=\s*\S+', 'networkingMode=mirrored' |
                Set-Content $wslConfigPath
            Write-Ok ".wslconfig updated to networkingMode=mirrored"
        } else {
            Write-Warn "Kept networkingMode=$currentMode — portproxy will be used as fallback."
        }
    } elseif ($wslConfigRaw -notmatch 'networkingMode') {
        Write-Ok ".wslconfig exists (no networkingMode set — will be configured during install)"
    } else {
        Write-Ok ".wslconfig already has networkingMode=mirrored"
    }
} else {
    Write-Ok ".wslconfig not present (will be created during install)"
}

# ── systemd enabled in existing distro ───────────────────────────────────
$distroInstalled = wsl -l -q 2>&1 |
    ForEach-Object { ($_ -replace "`0","").Trim() } |
    Where-Object { $_ -match [regex]::Escape($Distro) }
if ($distroInstalled) {
    Write-Step "Checking systemd in $Distro..."
    $systemdEnabled = (wsl -d $Distro -- bash -c "grep -q 'systemd=true' /etc/wsl.conf 2>/dev/null && echo yes || echo no" 2>$null) -join ""
    if ($systemdEnabled.Trim() -eq "no") {
        Write-Warn "systemd is not enabled in $Distro (/etc/wsl.conf missing [boot] systemd=true)."
        Write-Host "  This is required for Docker to run reliably. The installer will fix this." -ForegroundColor White
        # The bash installer handles this — just flag it so user isn't surprised
    } else {
        Write-Ok "systemd is enabled in $Distro"
    }
}

Write-Host ""
Write-Ok "Pre-flight checks complete."
Write-Host ""

# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — Check WSL2 is available ──────────────────────────────────────
Write-Step "Checking WSL2..."
# Use 'wsl -l' rather than 'wsl --status': the latter can transiently fail
# right after 'wsl --shutdown', giving a false "not installed" signal.
$wslCheck = wsl -l 2>&1 | Out-String
$wslInstalled = ($LASTEXITCODE -eq 0) -or ($wslCheck -notmatch 'not enabled|optional component|0x8007019e')
if (-not $wslInstalled) {
    Write-Host ""
    Write-Host "  WSL2 is not installed on this machine." -ForegroundColor Yellow
    Write-Host "  This installer will now install the WSL kernel and components," -ForegroundColor White
    Write-Host "  then stop. You must REBOOT before continuing." -ForegroundColor White
    Write-Host ""
    Write-Host "  After rebooting, re-run this script:" -ForegroundColor White
    Write-Host "    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass" -ForegroundColor White
    Write-Host "    $PSCommandPath" -ForegroundColor White
    Write-Host ""
    Read-Host "  Press Enter to install WSL (a reboot prompt will follow)"
    Write-Host ""
    Write-Step "Installing WSL kernel and components..."
    Write-Host "  (Enabling Virtual Machine Platform + Windows Subsystem for Linux)" -ForegroundColor DarkGray
    wsl --install --no-distribution
    Write-Host ""
    Write-Ok "WSL components installed."
    Write-Warn "A reboot is required before WSL will work."
    Write-Host ""
    $reboot = Read-Host "  Reboot now? [Y/n]"
    if ($reboot -notmatch '^[Nn]') {
        Restart-Computer -Force
    }
    Write-Host "  Please reboot manually, then re-run this script." -ForegroundColor Yellow
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
    # Note: do NOT pass --no-launch; without an initial launch the distro is downloaded
    # but never initialized, so it won't appear in 'wsl -l' until it has been run at
    # least once.  wsl --install will open an Ubuntu terminal window for first-time setup.
    Write-Host ""
    Write-Host "  A new terminal window will open for Ubuntu first-time setup." -ForegroundColor Yellow
    Write-Host "  Create your Linux username and password there, then close that window." -ForegroundColor Yellow
    Write-Host "  Come back here and press Enter when done." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to start the Ubuntu installation"

    wsl --install -d $Distro

    Write-Host ""
    Read-Host "  Press Enter once you have finished Ubuntu first-time setup (created username + password)"

    # Confirm the distro is now visible
    $installed = wsl -l -q 2>&1 |
        ForEach-Object { ($_ -replace "`0", "").Trim() } |
        Where-Object { $_ -match [regex]::Escape($Distro) }

    if (-not $installed) {
        Write-Fail "'$Distro' still not found — please complete the Ubuntu setup in the terminal window that opened, then re-run this script."
    }

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
Read-Host "  The installer will ask for your Linux (sudo) password immediately when it starts.`n  Press Enter to launch the setup wizard"
Write-Host ""

# Run bash directly (not via `--`) so WSL allocates a proper PTY.
# Without a PTY, ncurses/whiptail cannot draw its TUI.
wsl -d $Distro bash "$WslBashPath"

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
