#!/usr/bin/env bash
# setup-gpu-wsl.sh — one-shot installer for py-captions-for-channels with full NVIDIA GPU support
#
# Run this inside WSL2 Ubuntu (22.04 or 24.04).
# Re-running is safe — all steps are idempotent.
#
# Usage:
#   bash setup-gpu-wsl.sh
# ---------------------------------------------------------------------------

set -euo pipefail

REPO_URL="https://github.com/jay3702/py-captions-for-channels.git"
DEFAULT_DEPLOY_DIR="$HOME/py-captions-for-channels"
LOG=/tmp/py_captions_install.log
BT="py-captions-for-channels — GPU installer"
W=72
ISSUES_URL="https://github.com/jay3702/py-captions-for-channels/issues/new"
CURRENT_STEP="Initializing"

# ── ensure TERM is set so ncurses/whiptail can draw its TUI ─────────────────
export TERM="${TERM:-xterm-256color}"

# ── sanity checks ────────────────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    echo "Do not run as root. Run as your normal user." >&2; exit 1
fi
if ! grep -qi microsoft /proc/version 2>/dev/null; then
    echo "This script must be run inside WSL2." >&2; exit 1
fi

# ── prime sudo early so all later silent sudo calls don't hang ───────────────
echo "This installer needs sudo access for apt-get, Docker, and config files."
sudo -v

# ── ensure whiptail is available ─────────────────────────────────────────────
if ! command -v whiptail &>/dev/null; then
    echo "Installing whiptail..."
    sudo apt-get install -y -qq whiptail 2>/dev/null
fi

# ── detect LAN prefix for prompt defaults ────────────────────────────────────
# WSL2 mirrored networking: the real LAN IP appears in hostname -I.
# WSL2 NAT mode: ask Windows PowerShell for the host's LAN IP.
_detect_lan_prefix() {
    local ip
    # Mirrored mode — look for a non-loopback, non-link-local, non-WSL-NAT address
    ip=$(hostname -I 2>/dev/null | tr ' ' '\n' \
        | grep -Ev '^(127\.|169\.|172\.)' \
        | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
        | head -1)
    # NAT mode fallback — call PowerShell (always available in WSL2)
    if [[ -z "$ip" ]] && command -v powershell.exe &>/dev/null; then
        ip=$(powershell.exe -NoProfile -Command \
            "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.AddressState -eq 'Preferred' -and \$_.IPAddress -notmatch '^(127\.|169\.|172\.)' } | Sort-Object PrefixLength -Descending | Select-Object -First 1 -ExpandProperty IPAddress" \
            2>/dev/null | tr -d '\r')
    fi
    # Return the /24 prefix (e.g. "192.168.1.") or a bare class-C placeholder
    echo "$ip" | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+\.' 2>/dev/null || echo "192.168."
}
LAN_PREFIX=$(_detect_lan_prefix)

# ── dialog helpers ────────────────────────────────────────────────────────────
# All helpers write their result to stdout; return 1 on Cancel/Esc.
_wt() { whiptail --backtitle "$BT" "$@" 3>&1 1>&2 2>&3; }

wt_msg() {    # wt_msg   "Title" "Text" [height]
    whiptail --backtitle "$BT" --title "$1" --msgbox "$2" "${3:-10}" "$W"
}
wt_yesno() {  # wt_yesno "Title" "Text" [height]  — returns 0=yes 1=no
    whiptail --backtitle "$BT" --title "$1" --yesno "$2" "${3:-10}" "$W"
}
wt_input() {  # wt_input "Title" "Prompt" "default" [height]
    _wt --title "$1" --inputbox "$2" "${4:-9}" "$W" "$3"
}
wt_pass() {   # wt_pass  "Title" "Prompt"
    _wt --title "$1" --passwordbox "$2" 9 "$W" ""
}
wt_info() {   # wt_info  "Title" "Text" — no button, disappears when script continues
    whiptail --backtitle "$BT" --title "$1" --infobox "$2" 7 "$W" || true
}

cancelled() {
    wt_msg "Cancelled" "Setup cancelled.\n\nYou can re-run at any time — all completed steps will be skipped." 10 || true
    exit 0
}

# ── error reporting ───────────────────────────────────────────────────────────
_ERROR_SHOWN=false
_show_error() {
    local step="$1" rc="$2"
    _ERROR_SHOWN=true
    local log_tail=""
    [[ -f "$LOG" ]] && log_tail=$(tail -8 "$LOG" 2>/dev/null | sed 's/[\x00-\x08\x0b-\x1f\x7f]//g')
    local ai_prompt="I ran the py-captions-for-channels GPU installer on WSL2 Ubuntu and it failed. Step: '${step}'. Exit code: ${rc}. Last log: $(tail -3 \"$LOG\" 2>/dev/null | tr '\n' ' ' | cut -c1-200)"
    wt_msg "Setup Failed — ${step}" \
"Step '${step}' failed (exit code: ${rc}).

Last log output:
${log_tail}

For self-help, paste this into ChatGPT or Claude:
-----------------------------------------------
${ai_prompt:0:260}
-----------------------------------------------
Or open a GitHub issue:
  ${ISSUES_URL}

Full log: ${LOG}" 30 || true
}

_die() {
    local rc=$? ln=$1
    [[ "$_ERROR_SHOWN" == true ]] && exit "$rc"
    _show_error "${CURRENT_STEP} (line ${ln})" "$rc"
    exit "$rc"
}
trap '_die $LINENO' ERR

# Run a block of commands under a whiptail gauge.
# The caller provides a function name; that function:
#   - emits plain N (0-100) lines on stdout for progress
#   - redirects all command output to $LOG itself
# A temp file carries the exit status out of the subshell.
_STATUS=$(mktemp)
gauge() {    # gauge "Title" "Message" function_name
    local title="$1" msg="$2" fn="$3"
    CURRENT_STEP="$title"
    echo 1 > "$_STATUS"
    {
        set +e
        $fn        # step function manages its own >> "$LOG" 2>&1 redirects
        echo $? > "$_STATUS"
        echo 100
    } | whiptail --backtitle "$BT" --title "$title" --gauge "$msg" 8 "$W" 0
    local rc; rc=$(cat "$_STATUS")
    if [[ "$rc" -ne 0 ]]; then
        _show_error "$title" "$rc"
        exit 1
    fi
}

# ════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS  (run before Welcome so problems surface immediately)
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Pre-flight checks"
_PREFLIGHT_WARN=()

# ── Docker snap conflict ──────────────────────────────────────────────────────
# snap-installed Docker runs in a confined sandbox; NVIDIA GPU passthrough and
# the standard /var/run/docker.sock path both break inside a snap jail.
# Must remove it before installing Docker Engine (apt).
if command -v snap &>/dev/null && snap list docker &>/dev/null; then
    wt_msg "Pre-flight: Snap Docker Detected" \
"A snap-packaged version of Docker is installed.

It conflicts with Docker Engine (apt) which this installer needs for
NVIDIA GPU passthrough to work correctly.

To fix this, close this dialog and run:
  sudo snap remove docker

Then re-run this installer." 16 || true
    exit 1
fi

# ── Ports 8000 / 9000 already in use ─────────────────────────────────────────
_busy_ports=()
for _p in 8000 9000; do
    if ss -tlnH "sport = :${_p}" 2>/dev/null | grep -q ":${_p}"; then
        _busy_ports+=("$_p")
    fi
done
if [[ ${#_busy_ports[@]} -gt 0 ]]; then
    _PREFLIGHT_WARN+=("Port(s) ${_busy_ports[*]} are already in use inside WSL.")
fi

# ── ufw status ────────────────────────────────────────────────────────────────
# If ufw is active, ports 8000/9000 must be open or Docker Compose will still
# bind them on the container side but Windows-side portproxy connections will
# be refused at the Linux kernel level.
if command -v ufw &>/dev/null && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
    _ufw_missing=()
    for _p in 8000 9000; do
        if ! sudo ufw status 2>/dev/null | grep -qE "^${_p}[/ ]"; then
            _ufw_missing+=("$_p")
        fi
    done
    if [[ ${#_ufw_missing[@]} -gt 0 ]]; then
        _PREFLIGHT_WARN+=("ufw is active but port(s) ${_ufw_missing[*]} are not open.")
        if wt_yesno "Pre-flight: ufw Ports" \
"ufw (firewall) is active and port(s) ${_ufw_missing[*]} are not open.

This will block inbound connections to the web UI.

Allow these ports now?" 12; then
            for _p in "${_ufw_missing[@]}"; do
                sudo ufw allow "$_p/tcp" >> "$LOG" 2>&1 || true
            done
            _PREFLIGHT_WARN=( "${_PREFLIGHT_WARN[@]/ufw is active*/}" )  # clear that warning
        fi
    fi
fi

# ── Stale container ───────────────────────────────────────────────────────────
if command -v docker &>/dev/null && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^py-captions$"; then
    if wt_yesno "Pre-flight: Existing Container" \
"A Docker container named 'py-captions' already exists.

This may be a leftover from a previous install. Remove it now so
docker compose can start a fresh container?" 12; then
        docker rm -f py-captions >> "$LOG" 2>&1 || true
    else
        _PREFLIGHT_WARN+=("Existing container 'py-captions' kept — docker compose may fail.")
    fi
fi

# ── Disk space (~5 GB needed for images + model cache) ───────────────────────
_free_kb=$(df --output=avail "$HOME" 2>/dev/null | tail -1)
if [[ -n "$_free_kb" && "$_free_kb" -lt $((5 * 1024 * 1024)) ]]; then
    _free_gb=$(awk "BEGIN { printf \"%.1f\", $_free_kb / 1048576 }" 2>/dev/null || echo "?")
    _PREFLIGHT_WARN+=("Only ${_free_gb} GB free in \$HOME — Docker images + Whisper models need ~5 GB.")
fi

# ── Show accumulated warnings ─────────────────────────────────────────────────
if [[ ${#_PREFLIGHT_WARN[@]} -gt 0 ]]; then
    _warn_text=""
    for _w in "${_PREFLIGHT_WARN[@]}"; do
        [[ -n "$_w" ]] && _warn_text+="  • $_w\n"
    done
    if [[ -n "$_warn_text" ]]; then
        wt_msg "Pre-flight Warnings" \
"The following issues were detected:

${_warn_text}
You can continue, but these may cause problems.
To abort and fix them first, press Cancel on the next dialog." 18 || true
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
# WELCOME
# ════════════════════════════════════════════════════════════════════════════
wt_msg "Welcome" \
"This installer configures full NVIDIA GPU acceleration for
py-captions-for-channels on WSL2:

  * Docker Engine + NVIDIA Container Toolkit
  * NAS share mount (CIFS)
  * Repository clone and .env configuration
  * Auto-start on WSL2 launch

You will be asked a few questions, then the install runs
unattended. Re-running is safe — completed steps are skipped." 16

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — gather all inputs upfront
# ════════════════════════════════════════════════════════════════════════════
LOCAL_DVR=false

# Deploy directory
DEPLOY_DIR=$(wt_input "Deploy Location" \
    "Where should the repository be stored?\n(Press Enter to use the default)" \
    "$DEFAULT_DEPLOY_DIR") || cancelled

# DVR URL
CHANNELS_DVR_URL=""
while [[ -z "$CHANNELS_DVR_URL" ]]; do
    CHANNELS_DVR_URL=$(wt_input "Channels DVR" \
        "Enter your Channels DVR server URL (port required):\n\nExample:  http://192.168.1.5:8089\n\nTip: open http://localhost:57000 on the DVR machine to find the address." \
        "http://${LAN_PREFIX}") || cancelled

    if [[ -z "$CHANNELS_DVR_URL" ]]; then
        wt_msg "Required" "Channels DVR URL is required." 8
        continue
    fi

    # ── Format check ──────────────────────────────────────────────────────
    # Must be http(s)://host-or-ip:port
    if ! echo "$CHANNELS_DVR_URL" | grep -qE '^https?://[^/:]+:[0-9]{2,5}(/.*)?$'; then
        wt_msg "Invalid URL" \
            "URL must include a port number.\n\nGood:  http://192.168.1.5:8089\nBad:   http://192.168.1.5\n\nPlease re-enter." 12
        CHANNELS_DVR_URL=""
        continue
    fi

    # ── IPv4 octet sanity check ────────────────────────────────────────────
    # If the host portion looks like an IP, make sure it has exactly four octets.
    _host=$(echo "$CHANNELS_DVR_URL" | grep -oE '//[^/:]+' | tr -d '/')
    if echo "$_host" | grep -qE '^[0-9]+(\.[0-9]+)*$'; then
        _octets=$(echo "$_host" | tr -cd '.' | wc -c)
        if [[ "$_octets" -ne 3 ]]; then
            wt_msg "Invalid IP" \
                "That IP address doesn't look right:\n  $_host\n\nA valid IPv4 address has four parts separated by dots.\n\nExample:  192.168.1.5\n\nPlease re-enter." 14
            CHANNELS_DVR_URL=""
            continue
        fi
    fi

    # ── Reachability test ─────────────────────────────────────────────────
    if curl -fsS --max-time 5 "${CHANNELS_DVR_URL%/}/dvr" >/dev/null 2>&1; then
        wt_info "Channels DVR" "✔ Connected to Channels DVR at\n  $CHANNELS_DVR_URL"
    else
        if ! wt_yesno "Cannot Reach Server" \
            "Could not connect to:\n  $CHANNELS_DVR_URL\n\nCommon causes:\n  • Wrong IP address or port\n  • Channels DVR not running\n  • Firewall blocking the connection\n\nContinue anyway? (Yes = use this URL, No = re-enter)" 16; then
            CHANNELS_DVR_URL=""   # re-prompt
        fi
        # If Yes, proceed with the URL as-is (might be intentional / DVR offline temporarily)
    fi
done

# NAS or local?
if [[ "$LOCAL_DVR" == false ]]; then
    if wt_yesno "Recordings Location" \
        "Are your DVR recordings on a NAS or remote server?\n\n  Yes = NAS / network share\n  No  = recordings are on this machine" 12; then
        USE_NAS=true
    else
        USE_NAS=false
        LOCAL_DVR=true
    fi
fi

NAS_SERVER="" NAS_SHARE="" MOUNT_POINT="/mnt/channels" CRED_FILE="/etc/cifs-credentials-py-captions"

if [[ "$LOCAL_DVR" == false ]]; then
    NAS_SERVER=$(wt_input "NAS -- Server" \
        "NAS server address (hostname or IP):" \
        "${LAN_PREFIX}") || cancelled

    NAS_SHARE=$(wt_input "NAS -- Share Name" \
        "Share name on ${NAS_SERVER}:" \
        "Channels") || cancelled

    MOUNT_POINT=$(wt_input "NAS -- Mount Point" \
        "Mount point for the share inside WSL2:" \
        "/mnt/channels") || cancelled
fi

# ── Confirm summary ────────────────────────────────────────────────────────
if [[ "$LOCAL_DVR" == false ]]; then
    NAS_LINE="\n  NAS share  : //${NAS_SERVER}/${NAS_SHARE} -> ${MOUNT_POINT}"
else
    NAS_LINE="\n  NAS        : none (local DVR)"
fi

wt_yesno "Confirm" \
"Ready to install with these settings:

  Deploy dir : $DEPLOY_DIR
  DVR URL    : $CHANNELS_DVR_URL${NAS_LINE}

Proceed?" 16 || cancelled

# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — Docker Engine
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Docker Engine"
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    wt_info "Docker Engine" "Docker already installed — skipping."
    sleep 1
else
    _docker_install() {
        echo 5
        sudo apt-get update -qq                             >> "$LOG" 2>&1
        echo 12
        sudo apt-get install -y -qq \
            ca-certificates curl gnupg lsb-release         >> "$LOG" 2>&1
        echo 20
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            | sudo gpg --dearmor \
                -o /etc/apt/keyrings/docker.gpg 2>/dev/null
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        echo 30
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
            | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        echo 35
        sudo apt-get update -qq                             >> "$LOG" 2>&1
        echo 50
        sudo apt-get install -y -qq \
            docker-ce docker-ce-cli containerd.io \
            docker-buildx-plugin docker-compose-plugin      >> "$LOG" 2>&1
        echo 90
        sudo usermod -aG docker "$USER"                     >> "$LOG" 2>&1
        sudo service docker start                           >> "$LOG" 2>&1
        echo 100
    }
    gauge "Docker Engine" "Installing Docker Engine — please wait..." _docker_install
fi

# Ensure daemon is running
if ! docker info &>/dev/null 2>&1; then
    wt_info "Docker Engine" "Starting Docker daemon..."
    sudo service docker start; sleep 2
fi

# Fix compose plugin symlink if needed
if ! docker compose version &>/dev/null 2>&1; then
    APT_COMPOSE="$(find /usr/libexec/docker/cli-plugins /usr/lib/docker/cli-plugins \
        -name docker-compose 2>/dev/null | head -1 || true)"
    if [[ -n "$APT_COMPOSE" ]]; then
        sudo mkdir -p /usr/local/lib/docker/cli-plugins
        sudo ln -sf "$APT_COMPOSE" /usr/local/lib/docker/cli-plugins/docker-compose
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — NVIDIA Container Toolkit
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="NVIDIA Container Toolkit"
if docker info 2>/dev/null | grep -q 'nvidia'; then
    wt_info "NVIDIA Toolkit" "nvidia runtime already registered — skipping."
    sleep 1
else
    _nvidia_install() {
        echo 10
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            | sudo gpg --dearmor \
                -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
        echo 25
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
            | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
        echo 35
        sudo apt-get update -qq                             >> "$LOG" 2>&1
        echo 55
        sudo apt-get install -y -qq nvidia-container-toolkit >> "$LOG" 2>&1
        echo 80
        (sudo nvidia-ctk runtime configure --runtime=docker --set-as-default \
            || sudo nvidia-ctk runtime configure --runtime=docker) >> "$LOG" 2>&1
        echo 92
        sudo service docker restart                         >> "$LOG" 2>&1
        sleep 2
        echo 100
    }
    gauge "NVIDIA Container Toolkit" "Installing nvidia-container-toolkit — please wait..." _nvidia_install
fi

# GPU sanity test
wt_info "GPU Test" "Testing GPU passthrough inside Docker..."
GPU_OK=false
if docker run --rm --gpus all --runtime=nvidia nvidia/cuda:12.1.0-base-ubuntu22.04 \
        nvidia-smi -L >> "$LOG" 2>&1; then
    GPU_OK=true
    GPU_NAME=$(docker run --rm --gpus all --runtime=nvidia \
        nvidia/cuda:12.1.0-base-ubuntu22.04 \
        nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "GPU detected")
    wt_msg "GPU Test" "✔ GPU visible in container:\n  $GPU_NAME\n\nGPU acceleration will be enabled." 12
else
    wt_msg "GPU Test" \
        "GPU test failed.\n\nThe container will run in CPU mode (slower transcription).\n\nTo fix later:\n  1. Ensure 'nvidia-smi' works in Windows PowerShell\n  2. Ensure CUDA 12.2+ driver is installed\n  3. Re-run this installer — it is safe to run again." 16
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — NAS mount
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="NAS Mount"
if [[ "$LOCAL_DVR" == false ]]; then
    sudo apt-get install -y -qq cifs-utils >> "$LOG" 2>&1
    sudo mkdir -p "$MOUNT_POINT"

    if mountpoint -q "$MOUNT_POINT"; then
        wt_info "NAS Mount" "${MOUNT_POINT} already mounted — skipping."
        sleep 1
    else
        # Credential + mount retry loop
        while true; do
            NAS_USER=$(wt_input "NAS Credentials" \
                "Username for //${NAS_SERVER}/${NAS_SHARE}\n(Leave blank for guest/no auth):" \
                "") || cancelled

            if [[ -n "$NAS_USER" ]]; then
                NAS_PASS=$(wt_pass "NAS Credentials" \
                    "Password for ${NAS_USER}@${NAS_SERVER}:") || cancelled
                printf "username=%s\npassword=%s\n" "$NAS_USER" "$NAS_PASS" \
                    | sudo tee "$CRED_FILE" > /dev/null
                MOUNT_OPTS="credentials=${CRED_FILE},uid=$(id -u),gid=$(id -g),iocharset=utf8"
            else
                printf "username=guest\npassword=\n" | sudo tee "$CRED_FILE" > /dev/null
                MOUNT_OPTS="guest,uid=$(id -u),gid=$(id -g),iocharset=utf8"
            fi
            sudo chmod 600 "$CRED_FILE"

            wt_info "NAS Mount" "Mounting //${NAS_SERVER}/${NAS_SHARE} ..."

            if sudo mount -t cifs "//${NAS_SERVER}/${NAS_SHARE}" "$MOUNT_POINT" \
                    -o "$MOUNT_OPTS" 2>/tmp/py_captions_mount_err; then
                break   # success
            fi

            MOUNT_ERR=$(cat /tmp/py_captions_mount_err 2>/dev/null)
            if echo "$MOUNT_ERR" | grep -qiE "permission denied|NT_STATUS_LOGON_FAILURE|error.13.|invalid credentials"; then
                wt_msg "Authentication Failed" \
                    "Wrong username or password for //${NAS_SERVER}/${NAS_SHARE}.\n\nPlease try again." 10
            elif echo "$MOUNT_ERR" | grep -qiE "no such host|connection refused|error.113.|error.111."; then
                NAS_SERVER=$(wt_input "NAS Unreachable" \
                    "Cannot reach ${NAS_SERVER}. Check the address.\n\nNAS server address:" \
                    "$NAS_SERVER") || cancelled
                NAS_SHARE=$(wt_input "NAS Unreachable" \
                    "Share name on ${NAS_SERVER}:" \
                    "$NAS_SHARE") || cancelled
            else
                if ! wt_yesno "Mount Error" \
                    "Mount failed:\n\n${MOUNT_ERR}\n\nRetry?" 14; then
                    cancelled
                fi
            fi
        done

        sudo mount --make-shared "$MOUNT_POINT"
        ENTRY_COUNT=$(ls "$MOUNT_POINT" 2>/dev/null | wc -l)
        wt_msg "NAS Mount" \
            "Mounted //${NAS_SERVER}/${NAS_SHARE}\n   at ${MOUNT_POINT}\n\n   ${ENTRY_COUNT} entries visible." 11
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — Clone / update repo
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Repository Clone"
_repo_step() {
    echo 10
    if [[ -d "$DEPLOY_DIR/.git" ]]; then
        # Existing valid clone — just update it
        git -C "$DEPLOY_DIR" pull --ff-only >> "$LOG" 2>&1
    else
        # Directory exists but has no .git (leftover from failed/partial install) — remove it.
        # Use sudo because Docker may have created data/ files owned by root.
        if [[ -d "$DEPLOY_DIR" ]]; then
            sudo rm -rf "$DEPLOY_DIR" >> "$LOG" 2>&1
        fi
        git clone "$REPO_URL" "$DEPLOY_DIR" >> "$LOG" 2>&1
    fi
    echo 100
}
gauge "Repository" "Cloning repository to ${DEPLOY_DIR}..." _repo_step

# ════════════════════════════════════════════════════════════════════════════
# STEP 5 — Configure .env
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Configuration (.env)"
ENV_FILE="$DEPLOY_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$DEPLOY_DIR/.env.example.nvidia" "$ENV_FILE"
fi

set_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    elif grep -q "^#\s*${key}=" "$ENV_FILE"; then
        sed -i "s|^#\s*${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
}

set_env "CHANNELS_DVR_URL"       "$CHANNELS_DVR_URL"
if [[ "$GPU_OK" == true ]]; then
    set_env "DOCKER_RUNTIME"         "nvidia"
    set_env "NVIDIA_VISIBLE_DEVICES" "all"
else
    set_env "DOCKER_RUNTIME"         "runc"
    set_env "NVIDIA_VISIBLE_DEVICES" ""
fi

# WSL2 NVENC: libnvidia-encode.so.1 lives at /usr/lib/wsl/lib on the WSL host
# but is NOT automatically mounted by the nvidia container runtime.
# Bind-mount that path into the container so ffmpeg can find it.
if [[ -d /usr/lib/wsl/lib ]]; then
    set_env "WSL_LIB_PATH" "/usr/lib/wsl/lib"
else
    set_env "WSL_LIB_PATH" "/tmp"
fi
if [[ "$LOCAL_DVR" == false ]]; then
    set_env "DVR_MEDIA_HOST_PATH"  "$MOUNT_POINT"
    set_env "DVR_MEDIA_MOUNT"      "$MOUNT_POINT"
    set_env "LOCAL_PATH_PREFIX"    "$MOUNT_POINT"
    set_env "DVR_RECORDINGS_PATH" "$MOUNT_POINT"

    # ── Auto-detect DVR_PATH_PREFIX ───────────────────────────────────────
    # The prefix is the portion of the DVR's recording paths that comes
    # before the Channels category folders (TV/, Movies/, etc.).
    # It must be stripped so local mount paths line up with API-returned paths.
    _DVR_PREFIX_PY=$(mktemp --suffix=.py)
    cat > "$_DVR_PREFIX_PY" << 'PYEOF'
import json, re, sys, os.path, urllib.request

dvr_url = sys.argv[1].rstrip('/')
prefix = ''

# Strategy 1 – ask /dvr for its storage path
try:
    with urllib.request.urlopen(dvr_url + '/dvr', timeout=5) as r:
        d = json.loads(r.read())
    for k in ('StoragePath', 'storage_path', 'Path', 'MediaFolder'):
        v = d.get(k, '')
        if v and len(v) > 1:
            prefix = v.rstrip('/\\')
            break
except Exception:
    pass

# Strategy 2 – split first recording path on known category folder names
# Strategy 3 – longest common prefix across first 20 paths (fallback)
if not prefix:
    try:
        with urllib.request.urlopen(dvr_url + '/api/v1/all', timeout=10) as r:
            recs = json.loads(r.read())
        paths = [r.get('path') or r.get('Path', '') for r in recs
                 if r.get('path') or r.get('Path')]
        pat = re.compile(
            r'(?:^|[/\\])'
            r'(TV|Movies?|Sports?|Kids|Other|TV Shows?|TV Series'
            r'|Documentar(?:y|ies)|News|Comedy|Drama|Music|Fitness)'
            r'[/\\]',
            re.I,
        )
        for p in paths:
            m = pat.search(p)
            if m:
                pfx = p[:m.start()].rstrip('/\\')
                if pfx:
                    prefix = pfx
                    break
        if not prefix and paths:
            norm = [p.replace('\\', '/') for p in paths[:20]]
            try:
                common = os.path.commonpath(norm)
                if common and common not in ('/', ''):
                    prefix = common.rstrip('/')
            except Exception:
                pass
    except Exception:
        pass

if prefix:
    print(prefix)
PYEOF

    wt_info "Path Detection" "Querying Channels DVR to detect media folder path prefix…"
    _DETECTED_PREFIX=$(python3 "$_DVR_PREFIX_PY" "$CHANNELS_DVR_URL" 2>/dev/null || true)
    rm -f "$_DVR_PREFIX_PY"

    if [[ -n "$_DETECTED_PREFIX" ]]; then
        _DVR_PREFIX=$(wt_input "DVR Media Folder Path" \
"Detected DVR media folder prefix — confirm or edit:

  $_DETECTED_PREFIX

This is stripped from DVR file paths so they map correctly
to the local mount at $MOUNT_POINT.
(Leave as-is unless your DVR uses a different base path.)" \
            "$_DETECTED_PREFIX") || _DVR_PREFIX="$_DETECTED_PREFIX"
    else
        _DVR_PREFIX=$(wt_input "DVR Media Folder Path" \
"Could not auto-detect the DVR media folder prefix.

Enter the base path that Channels DVR uses for its recordings
(e.g.  /tank/AllMedia/Channels  or  /media/DVR).

Leave empty to configure later via the web UI Settings." \
            "") || true
    fi

    [[ -n "$_DVR_PREFIX" ]] && set_env "DVR_PATH_PREFIX" "$_DVR_PREFIX"
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 6 — Auto-start (~/.bashrc + sudoers)
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Auto-start setup"

# dbus-launch is required to keep the WSL VM alive after all terminals close.
# It spawns a dbus-daemon as a background process under WSL's init (PID 2),
# which prevents WSL from shutting down when the last terminal exits.
if ! command -v dbus-launch &>/dev/null; then
    sudo apt-get install -y -qq dbus >> "$LOG" 2>&1
fi

MARKER="# ── py-captions auto-start"
if ! grep -q "$MARKER" ~/.bashrc 2>/dev/null; then
    cat >> ~/.bashrc << BASHRC

${MARKER} ─────────────────────────────────────────
AUTOSTART_DEPLOY_DIR="${DEPLOY_DIR}"
if ! pgrep -x dockerd > /dev/null; then
    sudo service docker start 2>/dev/null
fi
BASHRC

    if [[ "$LOCAL_DVR" == false ]]; then
        cat >> ~/.bashrc << BASHRC
if ! mountpoint -q ${MOUNT_POINT}; then
    # Ensure the mount point directory exists — Docker volume creation fails with
    # "no such file or directory" if the target dir is missing, even on retries.
    sudo mkdir -p ${MOUNT_POINT}
    # Retry up to 3 times — WSL networking may not be ready immediately after restart
    for _pcc_try in 1 2 3; do
        sudo mount -t cifs //${NAS_SERVER}/${NAS_SHARE} ${MOUNT_POINT} \\
            -o credentials=${CRED_FILE},uid=\$(id -u),gid=\$(id -g),iocharset=utf8 2>/dev/null \\
            && break
        [ \$_pcc_try -lt 3 ] && sleep \$(( _pcc_try * 2 ))
    done
    unset _pcc_try
fi
sudo mount --make-shared ${MOUNT_POINT} 2>/dev/null
BASHRC
    fi

    cat >> ~/.bashrc << 'BASHRC'
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q py-captions-for-channels; then
    (cd "$AUTOSTART_DEPLOY_DIR" && docker compose up -d 2>/dev/null)
fi
# ──────────────────────────────────────────────────────────────────────────
BASHRC
fi

SUDOERS_FILE="/etc/sudoers.d/py-captions"
# Always (re)write so new entries are picked up on re-runs
cat << SUDOERS | sudo tee "$SUDOERS_FILE" > /dev/null
# py-captions auto-start — passwordless commands
%docker ALL=(ALL) NOPASSWD: /usr/sbin/service docker start
%docker ALL=(ALL) NOPASSWD: /bin/systemctl start docker
%docker ALL=(ALL) NOPASSWD: /bin/systemctl enable docker
%docker ALL=(ALL) NOPASSWD: /bin/systemctl enable --now docker
%docker ALL=(ALL) NOPASSWD: /bin/mount -t cifs *
%docker ALL=(ALL) NOPASSWD: /bin/mount --make-shared *
SUDOERS
sudo chmod 440 "$SUDOERS_FILE"

# ════════════════════════════════════════════════════════════════════════════
# STEP 7 — Persistent service (systemd + Windows startup task)
# ════════════════════════════════════════════════════════════════════════════
# Goal: keep py-captions running 24/7 without a WSL terminal open.
#
# How:
#   1. Enable systemd in /etc/wsl.conf  → Docker runs as a proper service;
#      systemd as PID 1 keeps the WSL VM alive even with no terminal open.
#   2. Enable docker.service in systemd → Docker starts on WSL boot.
#   3. Register a Windows Task Scheduler task → starts this WSL distro at
#      Windows login so it comes up automatically after a reboot.
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Persistent Service"
WSL_CONF=/etc/wsl.conf
WSL_RESTART_NEEDED=false

# 1. Enable systemd
if ! grep -q 'systemd=true' "$WSL_CONF" 2>/dev/null; then
    WSL_RESTART_NEEDED=true
    if grep -q '^\[boot\]' "$WSL_CONF" 2>/dev/null; then
        sudo sed -i '/^\[boot\]/a systemd=true' "$WSL_CONF"
    else
        printf '\n[boot]\nsystemd=true\n' | sudo tee -a "$WSL_CONF" > /dev/null
    fi
fi

# 2. Enable Docker as a systemd service
#    (safe to run even if systemd isn't PID 1 yet — takes effect after restart)
sudo systemctl enable docker >> "$LOG" 2>&1 || true

# 3. Leave a flag for the PowerShell launcher to pick up — it will create the
#    Windows scheduled task (requires admin rights, so done from PS1 side).
if [[ "$WSL_RESTART_NEEDED" == true ]]; then
    touch /tmp/py_captions_needs_restart
else
    rm -f /tmp/py_captions_needs_restart
fi

# ════════════════════════════════════════════════════════════════════════════
# LAUNCH
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Docker Launch"
DOCKER_CMD="docker"
if ! groups | grep -q docker; then DOCKER_CMD="sg docker -c docker"; fi

_launch_step() {
    echo 5
    cd "$DEPLOY_DIR"
    $DOCKER_CMD compose pull  >> "$LOG" 2>&1
    echo 85
    $DOCKER_CMD compose up -d >> "$LOG" 2>&1
    echo 100
}
gauge "Starting" "Pulling image and starting container (~5 GB first run)..." _launch_step

# ════════════════════════════════════════════════════════════════════════════
# WAIT FOR HEALTHY STARTUP
# ════════════════════════════════════════════════════════════════════════════
WEB_UI_PORT=$(grep -m1 'WEB_UI_PORT' "$DEPLOY_DIR/.env" 2>/dev/null \
    | grep -oE '[0-9]+$' || echo "8000")
WEB_UI_URL="http://localhost:${WEB_UI_PORT}"

_STARTUP_RESULT=$(mktemp)
{
    _max=90 _interval=3 _elapsed=0
    while (( _elapsed < _max )); do
        printf '%d\n' $(( _elapsed * 100 / _max ))
        if curl -fsS --max-time 2 "$WEB_UI_URL" > /dev/null 2>&1; then
            printf '100\n'
            echo ok > "$_STARTUP_RESULT"
            break
        fi
        sleep $_interval
        (( _elapsed += _interval ))
    done
    printf '100\n'
} | whiptail --backtitle "$BT" --title "Verifying Startup" \
    --gauge "Checking web UI at ${WEB_UI_URL} every 3 s (up to 90 s)..." \
    8 "$W" 0

if [[ "$(cat "$_STARTUP_RESULT")" == "ok" ]]; then
    STARTUP_STATUS="\n\nWeb UI is up and responding at ${WEB_UI_URL}"
else
    # Container may still work (image pull took long, slow host, etc.) — warn but don't fail.
    STARTUP_LOGS=$(docker logs --tail 20 py-captions-for-channels 2>&1 | tail -20)
    wt_msg "Startup Warning" \
        "The web UI did not respond within 90 seconds.\n\nLast container log lines:\n\n${STARTUP_LOGS}\n\nSetup is otherwise complete. Try opening\n${WEB_UI_URL} in a moment, or run:\n  docker logs py-captions-for-channels" 24 || true
    STARTUP_STATUS="\n\nNOTE: Web UI did not respond during setup — check logs."
fi
rm -f "$_STARTUP_RESULT"
NEWGRP_NOTE=""
if ! groups | grep -q docker; then
    NEWGRP_NOTE="\n\nLog out and back in (or run 'newgrp docker')\n   to use Docker without sudo."
fi

WSL_RESTART_NOTE=""
if [[ "$WSL_RESTART_NEEDED" == true ]]; then
    WSL_RESTART_NOTE="\n\nNOTE: systemd was just enabled — the PowerShell\nscript will restart WSL automatically when this closes."
fi

wt_msg "Setup Complete" \
"py-captions-for-channels is running!${STARTUP_STATUS}

  Web dashboard : ${WEB_UI_URL}
  Deploy dir    : $DEPLOY_DIR
  Install log   : $LOG

Next steps:
  1. Open ${WEB_UI_URL}
  2. Run the Setup Wizard to verify recordings mount
  3. Go to Recordings and whitelist shows to caption
  4. Set DRY_RUN=false in .env when ready${NEWGRP_NOTE}${WSL_RESTART_NOTE}" 26

rm -f "$_STATUS"
