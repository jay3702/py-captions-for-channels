#!/usr/bin/env bash
# setup-gpu-wsl.sh — one-shot installer for py-captions-for-channels with full NVIDIA GPU support
#
# Run this inside WSL2 Ubuntu (22.04 or 24.04).
# Re-running is safe — all steps are idempotent.
#
# Usage:
#   bash setup-gpu-wsl.sh
#   bash setup-gpu-wsl.sh --local-dvr   # skip NAS setup
# ---------------------------------------------------------------------------

set -euo pipefail

REPO_URL="https://github.com/jay3702/py-captions-for-channels.git"
DEFAULT_DEPLOY_DIR="$HOME/py-captions-for-channels"
LOG=/tmp/py_captions_install.log
BT="py-captions-for-channels — GPU installer"
W=72

# ── sanity checks ────────────────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    echo "Do not run as root. Run as your normal user." >&2; exit 1
fi
if ! grep -qi microsoft /proc/version 2>/dev/null; then
    echo "This script must be run inside WSL2." >&2; exit 1
fi

# ── ensure whiptail is available ─────────────────────────────────────────────
if ! command -v whiptail &>/dev/null; then
    echo "Installing whiptail..."
    sudo apt-get install -y -qq whiptail 2>/dev/null
fi

# ── argument parsing ──────────────────────────────────────────────────────────
LOCAL_DVR=false
for arg in "$@"; do [[ "$arg" == "--local-dvr" ]] && LOCAL_DVR=true; done

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

# Run a block of commands under a whiptail gauge.
# The caller provides a function name; that function:
#   - emits plain N (0-100) lines on stdout for progress
#   - redirects all command output to $LOG itself
# A temp file carries the exit status out of the subshell.
_STATUS=$(mktemp)
gauge() {    # gauge "Title" "Message" function_name
    local title="$1" msg="$2" fn="$3"
    echo 1 > "$_STATUS"
    {
        set +e
        $fn        # step function manages its own >> "$LOG" 2>&1 redirects
        echo $? > "$_STATUS"
        echo 100
    } | whiptail --backtitle "$BT" --title "$title" --gauge "$msg" 8 "$W" 0
    local rc; rc=$(cat "$_STATUS")
    if [[ "$rc" -ne 0 ]]; then
        wt_msg "Error" "Step failed (exit $rc).\n\nSee log for details:\n  $LOG" 11
        exit 1
    fi
}

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

# Deploy directory
DEPLOY_DIR=$(wt_input "Deploy Location" \
    "Where should the repository be stored?\n(Press Enter to use the default)" \
    "$DEFAULT_DEPLOY_DIR") || cancelled

# DVR URL
CHANNELS_DVR_URL=""
while [[ -z "$CHANNELS_DVR_URL" ]]; do
    CHANNELS_DVR_URL=$(wt_input "Channels DVR" \
        "Enter your Channels DVR server URL:" \
        "http://192.168.3.") || cancelled
    if [[ -z "$CHANNELS_DVR_URL" ]]; then
        wt_msg "Required" "Channels DVR URL is required." 8
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
        "192.168.") || cancelled

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
GPU_MSG=""
if docker run --rm --gpus all --runtime=nvidia nvidia/cuda:12.1.0-base-ubuntu22.04 \
        nvidia-smi -L >> "$LOG" 2>&1; then
    GPU_NAME=$(docker run --rm --gpus all --runtime=nvidia \
        nvidia/cuda:12.1.0-base-ubuntu22.04 \
        nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "GPU detected")
    GPU_MSG="GPU visible in container:\n     $GPU_NAME"
else
    GPU_MSG="GPU test failed — GPU may still work at runtime.\n\nCheck that nvidia-smi works in Windows PowerShell\nand your CUDA version is 12.2 or higher."
fi
wt_msg "GPU Test" "$GPU_MSG" 12

# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — NAS mount
# ════════════════════════════════════════════════════════════════════════════
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
_repo_step() {
    echo 10
    if [[ -d "$DEPLOY_DIR/.git" ]]; then
        git -C "$DEPLOY_DIR" pull --ff-only  >> "$LOG" 2>&1
    else
        git clone "$REPO_URL" "$DEPLOY_DIR" >> "$LOG" 2>&1
    fi
    echo 100
}
gauge "Repository" "Cloning repository to ${DEPLOY_DIR}..." _repo_step

# ════════════════════════════════════════════════════════════════════════════
# STEP 5 — Configure .env
# ════════════════════════════════════════════════════════════════════════════
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
set_env "DOCKER_RUNTIME"         "nvidia"
set_env "NVIDIA_VISIBLE_DEVICES" "all"
if [[ "$LOCAL_DVR" == false ]]; then
    set_env "DVR_MEDIA_HOST_PATH" "$MOUNT_POINT"
    set_env "DVR_MEDIA_MOUNT"     "$MOUNT_POINT"
    set_env "LOCAL_PATH_PREFIX"   "$MOUNT_POINT"
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 6 — Auto-start (~/.bashrc + sudoers)
# ════════════════════════════════════════════════════════════════════════════
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
    sudo mount -t cifs //${NAS_SERVER}/${NAS_SHARE} ${MOUNT_POINT} \\
        -o credentials=${CRED_FILE},uid=\$(id -u),gid=\$(id -g),iocharset=utf8 2>/dev/null
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
if [[ ! -f "$SUDOERS_FILE" ]]; then
    cat << SUDOERS | sudo tee "$SUDOERS_FILE" > /dev/null
# py-captions auto-start — passwordless commands
%docker ALL=(ALL) NOPASSWD: /usr/sbin/service docker start
%docker ALL=(ALL) NOPASSWD: /bin/mount -t cifs *
%docker ALL=(ALL) NOPASSWD: /bin/mount --make-shared *
SUDOERS
    sudo chmod 440 "$SUDOERS_FILE"
fi

# ════════════════════════════════════════════════════════════════════════════
# LAUNCH
# ════════════════════════════════════════════════════════════════════════════
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
# DONE
# ════════════════════════════════════════════════════════════════════════════
NEWGRP_NOTE=""
if ! groups | grep -q docker; then
    NEWGRP_NOTE="\n\nLog out and back in (or run 'newgrp docker')\n   to use Docker without sudo."
fi

wt_msg "Setup Complete" \
"py-captions-for-channels is running!

  Web dashboard : http://localhost:8000
  Deploy dir    : $DEPLOY_DIR
  Install log   : $LOG

Next steps:
  1. Open http://localhost:8000
  2. Run the Setup Wizard to verify recordings mount
  3. Go to Recordings and whitelist shows to caption
  4. Set DRY_RUN=false in .env when ready${NEWGRP_NOTE}" 20

rm -f "$_STATUS"
