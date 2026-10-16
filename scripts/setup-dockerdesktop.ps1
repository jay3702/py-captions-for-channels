# setup-dockerdesktop.ps1 — Windows installer for py-captions-for-channels (Docker Desktop path)
#
# Use this script when you already have Docker Desktop installed and do NOT
# need the full GPU/WSL2 setup wizard.  It is the simplest installation path:
#
#   * Works on Windows 10 and Windows 11
#   * Works with Docker Desktop (WSL2 or Hyper-V backend)
#   * GPU acceleration is optional and auto-detected
#   * No systemd, no NVIDIA Container Toolkit setup
#
# For full GPU / WSL2 control use setup-wsl.ps1 instead.
#
# Usage (PowerShell 5.1+):
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\setup-dockerdesktop.ps1
# ---------------------------------------------------------------------------
param(
    [string]$InstallDir    = "$env:USERPROFILE\py-captions-for-channels",
    [switch]$RegisterOnly,   # internal: elevated re-launch to set firewall + LAN
    [string]$WslIp         = "",
    [string]$Ports         = "8000,9000"  # internal: ports for -RegisterOnly to open
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/jay3702/py-captions-for-channels.git"

function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "✘ $msg" -ForegroundColor Red; exit 1 }

# ════════════════════════════════════════════════════════════════════════════
# ELEVATED BRANCH — firewall rules + LAN networking
# (Re-launched from the non-elevated section below when needed)
# ════════════════════════════════════════════════════════════════════════════
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]"Administrator")

if ($isAdmin -and $RegisterOnly) {
    # ── Firewall rules ────────────────────────────────────────────────────
    foreach ($port in ($Ports -split ',' | ForEach-Object { [int]$_ })) {
        $ruleName = switch ($port) {
            8000    { "py-captions Web UI" }
            9000    { "py-captions Webhook" }
            default { "py-captions TCP $port" }
        }
        if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound `
                -Protocol TCP -LocalPort $port -Action Allow | Out-Null
            Write-Ok "Firewall: allowed inbound TCP $port ($ruleName)"
        } else {
            Write-Ok "Firewall rule for port $port already exists"
        }
    }

    # ── LAN networking ────────────────────────────────────────────────────
    # Docker Desktop on Windows exposes ports on the host's real IP directly
    # (no portproxy / WSL VM bridge needed).
    # On Windows 11 22H2+ with WSL2 backend + mirrored mode, same applies.
    # Nothing to configure here — firewall rules above are all that's needed.

    Write-Ok "Firewall configured for LAN access"
    exit 0
}

# ════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  py-captions-for-channels — Docker Desktop setup" -ForegroundColor White
Write-Host ""

# ── Docker Desktop installed ──────────────────────────────────────────────
Write-Step "Checking Docker Desktop..."
$dockerDesktopPath = @(
    "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
    "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $dockerDesktopPath) {
    Write-Host ""
    Write-Host "  Docker Desktop is not installed." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Download it from:  https://www.docker.com/products/docker-desktop/" -ForegroundColor White
    Write-Host "  After installing, make sure Docker Desktop is RUNNING (whale icon in tray)," -ForegroundColor White
    Write-Host "  then re-run this script." -ForegroundColor White
    Write-Host ""
    $open = Read-Host "  Open the Docker Desktop download page now? [Y/n]"
    if ($open -notmatch "^[Nn]") {
        Start-Process "https://www.docker.com/products/docker-desktop/"
    }
    exit 1
}
Write-Ok "Docker Desktop found"

# ── Docker daemon running ─────────────────────────────────────────────────
Write-Step "Checking Docker daemon..."
$dockerReady = $false
for ($i = 0; $i -lt 5; $i++) {
    $result = & docker info 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
    if ($i -eq 0) {
        Write-Host "  Docker daemon not responding — waiting for Docker Desktop to start..." -ForegroundColor DarkGray
        Start-Process $dockerDesktopPath
    }
    Start-Sleep 6
}
if (-not $dockerReady) {
    Write-Fail "Docker daemon is not responding.`n  Make sure Docker Desktop is running (whale icon in the system tray), then re-run."
}
Write-Ok "Docker daemon is running"

# ── Disk space ────────────────────────────────────────────────────────────
Write-Step "Checking disk space..."
$drive = $env:SystemDrive
$disk  = Get-PSDrive ($drive.TrimEnd(':')) -ErrorAction SilentlyContinue
if ($disk -and $disk.Free -lt 10GB) {
    $freeGB = [math]::Round($disk.Free / 1GB, 1)
    Write-Warn "Only ${freeGB} GB free on $drive — recommend at least 10 GB (container image + Whisper models)."
    $cont = Read-Host "  Continue anyway? [y/N]"
    if ($cont -notmatch "^[Yy]") { exit 0 }
} else {
    Write-Ok "Disk space OK"
}

# ── Network adapter profile ───────────────────────────────────────────────
Write-Step "Checking network adapter profile..."
$publicAdapters = Get-NetConnectionProfile -ErrorAction SilentlyContinue |
    Where-Object { $_.NetworkCategory -eq 'Public' }
if ($publicAdapters) {
    Write-Host ""
    Write-Warn "One or more network adapters are set to 'Public':"
    $publicAdapters | ForEach-Object { Write-Host "    $($_.InterfaceAlias) — $($_.Name)" -ForegroundColor Yellow }
    Write-Host "  Windows Firewall blocks inbound connections on Public profiles" -ForegroundColor White
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

# ── Existing instances ────────────────────────────────────────────────────
# Several instances (one per Channels DVR) can share this PC's GPU, each with
# its own folder, ports and container name — see docs/MULTI_INSTANCE.md.
function Invoke-Docker {
    $ErrorActionPreference = "Continue"   # native stderr must not be fatal here
    try { & docker @args 2>$null } catch { }
}
# Templates use Go's backtick strings, never double quotes: Windows
# PowerShell 5.1 strips embedded double quotes from native-command arguments.
$existing = @(@(Invoke-Docker ps -a --filter "label=com.docker.compose.service=py-captions" `
    --format '{{.Names}}|{{.Label `com.docker.compose.project.working_dir`}}') | Where-Object { $_ })
$addInstance = $false
$containerName = ""
$instanceName = ""
if ($existing) {
    Write-Host ""
    Write-Host "  py-captions-for-channels is already installed on this PC:" -ForegroundColor White
    $existing | ForEach-Object { Write-Host "    • $(($_ -split '\|')[0])" -ForegroundColor White }
    $add = Read-Host "  Add another instance for a different Channels DVR? [Y/n]"
    if ($add -notmatch "^[Nn]") {
        $addInstance = $true
        while (-not $instanceName) {
            $instanceName = (Read-Host "  Name for this instance (e.g. Bedroom DVR)") -replace '[|"\\]', ''
        }
        $slug = ($instanceName.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')
        if ($slug.Length -gt 24) { $slug = $slug.Substring(0, 24).Trim('-') }
        if (-not $slug) { $slug = "dvr2" }
        $containerName = "py-captions-$slug"
        $names = $existing | ForEach-Object { ($_ -split '\|')[0] }
        while ($names -contains $containerName) { $containerName = "$containerName-2" }
        $InstallDir = Join-Path (Split-Path -Parent $InstallDir) $containerName
    }
}

# ── Ports — skip ones in use, or reserved by other (even stopped) containers
Write-Step "Choosing ports..."
$reserved = @()
$ids = @(@(Invoke-Docker ps -aq) | Where-Object { $_ })
if ($ids) {
    $tmpl = '{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}{{.HostPort}} {{end}}{{end}}'
    $reserved = @(((Invoke-Docker inspect --format $tmpl @ids) -join " ") -split '\s+' |
        Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ })
}
function Get-FreePort([int]$Start) {
    $p = $Start
    while (($reserved -contains $p) -or
           (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) { $p++ }
    return $p
}
$webPort = Get-FreePort 8000
$webhookPort = Get-FreePort 9000
$glancesPort = Get-FreePort 61208
Write-Ok "Web UI port $webPort, webhook port $webhookPort"

# ── NVIDIA GPU (optional) ─────────────────────────────────────────────────
Write-Step "Checking for NVIDIA GPU..."
$gpuAvailable = $false
try {
    $nvsmi = & nvidia-smi --query-gpu=name --format=csv,noheader 2>&1
    if ($LASTEXITCODE -eq 0) {
        $gpuAvailable = $true
        Write-Ok "NVIDIA GPU detected: $($nvsmi | Select-Object -First 1)"
    }
} catch { }
if (-not $gpuAvailable) {
    Write-Host "  No NVIDIA GPU detected — will run Whisper on CPU (slower, but fully functional)." -ForegroundColor DarkGray
}

# ════════════════════════════════════════════════════════════════════════════
# INSTALL DIRECTORY
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Step "Where should the repository be cloned?"
Write-Host "  Default: $InstallDir" -ForegroundColor DarkGray
$customDir = Read-Host "  Press Enter to accept, or type a different path"
if ($customDir.Trim()) { $InstallDir = $customDir.Trim() }

# ════════════════════════════════════════════════════════════════════════════
# CLONE / UPDATE REPOSITORY
# ════════════════════════════════════════════════════════════════════════════
if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Step "Repository already exists — pulling latest changes..."
    Push-Location $InstallDir
    git pull --ff-only 2>&1 | Out-Null
    Pop-Location
    Write-Ok "Repository up to date"
} elseif (Test-Path $InstallDir) {
    Write-Warn "$InstallDir exists but is not a git repo."
    $overwrite = Read-Host "  Remove it and clone fresh? [y/N]"
    if ($overwrite -notmatch "^[Yy]") { exit 0 }
    Remove-Item -Recurse -Force $InstallDir
    Write-Step "Cloning repository..."
    git clone $RepoUrl $InstallDir 2>&1 | Out-Null
    Write-Ok "Repository cloned to $InstallDir"
} else {
    Write-Step "Cloning repository..."
    git clone $RepoUrl $InstallDir 2>&1 | Out-Null
    Write-Ok "Repository cloned to $InstallDir"
}

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURE .env
# ════════════════════════════════════════════════════════════════════════════
$envFile = Join-Path $InstallDir ".env"
$envExample = Join-Path $InstallDir ".env.example"

if (Test-Path $envFile) {
    Write-Ok ".env already exists — skipping config (edit manually to change settings)"
    Write-Host "  $envFile" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Step "Configuring .env..."

    # ── Channels DVR URL ──────────────────────────────────────────────────
    Write-Host ""
    Write-Host "  Channels DVR URL (e.g. http://192.168.1.50:8089):" -ForegroundColor White
    $dvrUrl = ""
    while ($dvrUrl -notmatch "^https?://") {
        $dvrUrl = Read-Host "  DVR URL"
        if ($dvrUrl -notmatch "^https?://") {
            Write-Warn "  Must start with http:// or https://"
        }
    }

    # ── DVR recordings path ───────────────────────────────────────────────
    Write-Host ""
    Write-Host "  Path to Channels DVR recordings on THIS machine:" -ForegroundColor White
    Write-Host "  (Use a drive letter like C:\DVR\recordings or a UNC path)" -ForegroundColor DarkGray
    $recordingsPath = ""
    while (-not $recordingsPath.Trim()) {
        $recordingsPath = Read-Host "  Recordings path"
    }
    # Normalise backslashes to forward for Docker
    $recordingsPathDocker = $recordingsPath -replace '\\', '/'
    # If it's a Windows path like C:/..., Docker Desktop accepts that directly as a host path
    # We store it as DVR_MEDIA_HOST_PATH (Docker Desktop bind-mount path)

    # ── GPU ───────────────────────────────────────────────────────────────
    $dockerRuntime = "runc"
    $nvidiaDevices = ""
    if ($gpuAvailable) {
        Write-Host ""
        $useGpu = Read-Host "  Enable NVIDIA GPU acceleration for Whisper? [Y/n]"
        if ($useGpu -notmatch "^[Nn]") {
            $dockerRuntime = "nvidia"
            $nvidiaDevices = "all"
        }
    }

    # ── Timezone ──────────────────────────────────────────────────────────
    $tzId = [System.TimeZoneInfo]::Local.Id
    # Convert Windows TZ ID to IANA (best-effort)
    $tzIana = try {
        [System.TimeZoneInfo]::FindSystemTimeZoneById($tzId).Id
    } catch { $tzId }

    # ── Write .env ────────────────────────────────────────────────────────
    $envLines = @(
        "# py-captions-for-channels — generated by setup-dockerdesktop.ps1",
        "",
        "CHANNELS_DVR_URL=$dvrUrl",
        "",
        "# Recordings path on the Windows host (Docker Desktop bind mount)",
        "DVR_MEDIA_HOST_PATH=$recordingsPathDocker",
        "DVR_MEDIA_MOUNT=/mnt/recordings",
        "",
        "TZ=$tzIana",
        "SERVER_TZ=$tzIana",
        "",
        "WEB_UI_PORT=$webPort",
        "WEBHOOK_PORT=$webhookPort",
        ""
    )
    if ($addInstance) {
        $envLines += @(
            "# Additional instance: names and ports that don't collide with the others",
            "CONTAINER_NAME=$containerName",
            "GLANCES_PORT=$glancesPort",
            "INSTANCE_NAME=$instanceName",
            ""
        )
    }
    if ($dockerRuntime -eq "nvidia") {
        $envLines += @(
            "DOCKER_RUNTIME=nvidia",
            "NVIDIA_VISIBLE_DEVICES=$nvidiaDevices",
            ""
        )
    }
    $envLines | Set-Content $envFile
    Write-Ok ".env written to $InstallDir\.env"
}

# An existing .env (re-run on an installed folder) keeps its own ports
foreach ($pair in @(@("WEB_UI_PORT", "webPort"), @("WEBHOOK_PORT", "webhookPort"))) {
    $m = Select-String -Path $envFile -Pattern "^$($pair[0])=(\d+)" | Select-Object -First 1
    if ($m) { Set-Variable -Name $pair[1] -Value ([int]$m.Matches[0].Groups[1].Value) }
    elseif (-not $addInstance) { Set-Variable -Name $pair[1] -Value $(if ($pair[0] -eq "WEB_UI_PORT") { 8000 } else { 9000 }) }
}

# ════════════════════════════════════════════════════════════════════════════
# PULL IMAGE + START CONTAINER
# ════════════════════════════════════════════════════════════════════════════
Push-Location $InstallDir
Write-Host ""
Write-Step "Pulling latest container image..."
docker compose pull 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }

Write-Step "Starting container..."
docker compose up -d 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Write-Fail "docker compose up failed. Check the output above and your .env settings."
}
Pop-Location
Write-Ok "Container started"

# Instances installed before GPU sharing don't take turns on the GPU until
# they run the current docker-compose.yml.
if ($addInstance) {
    foreach ($entry in $existing) {
        $name, $dir = $entry -split '\|', 2
        $shares = (Invoke-Docker inspect $name --format '{{range .Mounts}}{{if eq .Destination `/gpu-slots`}}yes{{end}}{{end}}') -join ""
        if ($shares -match "yes") { continue }
        if ($dir -and (Test-Path (Join-Path $dir ".git"))) {
            $upd = Read-Host "  Update '$name' so it takes turns on the GPU with this one (git pull + restart)? [Y/n]"
            if ($upd -notmatch "^[Nn]") {
                Push-Location $dir
                git pull --ff-only 2>&1 | Out-Null
                docker compose up -d 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
                Pop-Location
                continue
            }
        }
        Write-Warn "'$name' won't take turns on the GPU until it's updated: in its folder run"
        Write-Warn "  git pull; docker compose pull; docker compose up -d"
    }
}

# ════════════════════════════════════════════════════════════════════════════
# FIREWALL RULES (requires elevation)
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Step "Configuring Windows Firewall (requires Administrator)..."
$scriptPath = $MyInvocation.MyCommand.Path
Start-Process powershell -Verb RunAs -Wait -ArgumentList `
    "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -RegisterOnly -Ports $webPort,$webhookPort"
Write-Ok "Firewall rules applied"

# ════════════════════════════════════════════════════════════════════════════
# AUTOSTART — Docker Desktop option
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Step "Auto-start on Windows startup..."
Write-Host "  Docker Desktop can start containers automatically when Windows starts." -ForegroundColor White
Write-Host "  To enable:" -ForegroundColor White
Write-Host "    1. Open Docker Desktop → Settings (gear icon)" -ForegroundColor DarkGray
Write-Host "    2. General → ✔ Start Docker Desktop when you log in" -ForegroundColor DarkGray
Write-Host "    3. The container uses 'restart: unless-stopped' — it starts automatically" -ForegroundColor DarkGray
Write-Host "       whenever the Docker daemon starts." -ForegroundColor DarkGray

# ════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════════
$hostIp = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notmatch '^(127\.|169\.|172\.)' } |
    Sort-Object PrefixLength -Descending |
    Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  py-captions-for-channels is running!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
Write-Host "  Web UI (this machine):  http://localhost:$webPort" -ForegroundColor White
if ($hostIp) {
    Write-Host "  Web UI (LAN):           http://${hostIp}:$webPort" -ForegroundColor White
}
if ($addInstance) {
    Write-Host "  Instance:               $instanceName ($containerName)" -ForegroundColor White
}
Write-Host ""
Write-Host "  Repository:  $InstallDir" -ForegroundColor DarkGray
Write-Host "  Config:      $envFile" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Useful commands (run from $InstallDir):" -ForegroundColor DarkGray
Write-Host "    docker compose logs -f     # stream logs" -ForegroundColor DarkGray
Write-Host "    docker compose restart     # restart after .env changes" -ForegroundColor DarkGray
Write-Host "    docker compose pull && docker compose up -d   # update image" -ForegroundColor DarkGray
Write-Host ""
