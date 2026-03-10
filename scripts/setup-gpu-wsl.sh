#!/usr/bin/env bash
# setup-gpu-wsl.sh — one-shot installer for py-captions-for-channels with full NVIDIA GPU support
#
# Run this inside WSL2 Ubuntu (22.04 or 24.04).
# It installs Docker Engine, nvidia-container-toolkit, mounts your NAS, clones the repo,
# configures .env, sets up auto-start, and launches the container.
#
# Usage (run as your normal user, not root):
#   bash setup-gpu-wsl.sh
#   bash setup-gpu-wsl.sh --local-dvr   # skip NAS setup (DVR on same LAN, recordings via API path)
#
# Re-running is safe — all steps are idempotent.
# ---------------------------------------------------------------------------

set -euo pipefail

# ── colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}▶ $*${NC}"; }
success() { echo -e "${GREEN}✔ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠ $*${NC}"; }
error()   { echo -e "${RED}✘ $*${NC}" >&2; }
ask()     { echo -e "${YELLOW}? $*${NC}"; }   # prompt prefix

# ── sanity checks ──────────────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    error "Do not run as root. Run as your normal user — sudo will be used where needed."
    exit 1
fi

if ! grep -qi microsoft /proc/version 2>/dev/null; then
    error "This script must be run inside WSL2. Run it from your Ubuntu terminal."
    exit 1
fi

WSL_VERSION=$(wslcat /proc/version 2>/dev/null | grep -oP '(?<=WSL)[0-9]' || true)
# Fallback detection
if [[ -z "$WSL_VERSION" ]] && grep -qi "WSL2" /proc/version 2>/dev/null; then WSL_VERSION=2; fi

# ── argument parsing ───────────────────────────────────────────────────────
LOCAL_DVR=false
for arg in "$@"; do
    [[ "$arg" == "--local-dvr" ]] && LOCAL_DVR=true
done

# ── deploy location ────────────────────────────────────────────────────────
# Default: inside WSL2 home (fast I/O).  The user can override.
DEFAULT_DEPLOY_DIR="$HOME/py-captions-for-channels"
REPO_URL="https://github.com/jay3702/py-captions-for-channels.git"

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║     py-captions-for-channels — GPU installer (WSL2)             ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════════════════════════════
# STEP 0 — Gather inputs upfront so the install doesn't interrupt midway
# ══════════════════════════════════════════════════════════════════════════
echo "── Configuration ───────────────────────────────────────────────────"
echo ""

# Deploy directory
ask "Where should the repo be deployed? [${DEFAULT_DEPLOY_DIR}]"
read -r DEPLOY_DIR_INPUT
DEPLOY_DIR="${DEPLOY_DIR_INPUT:-$DEFAULT_DEPLOY_DIR}"

# DVR URL
ask "Channels DVR URL (e.g. http://192.168.3.X:8089):"
read -r CHANNELS_DVR_URL
while [[ -z "$CHANNELS_DVR_URL" ]]; do
    warn "CHANNELS_DVR_URL is required."
    ask "Channels DVR URL:"
    read -r CHANNELS_DVR_URL
done

# NAS setup
if [[ "$LOCAL_DVR" == false ]]; then
    echo ""
    ask "Is your DVR recordings folder on a NAS or remote server? [Y/n]"
    read -r USE_NAS_INPUT
    USE_NAS="${USE_NAS_INPUT:-y}"
    if [[ "${USE_NAS,,}" == "n" ]]; then
        LOCAL_DVR=true
    fi
fi

NAS_SERVER="" NAS_SHARE="" NAS_USER="" NAS_PASS="" MOUNT_POINT="/mnt/channels"

if [[ "$LOCAL_DVR" == false ]]; then
    echo ""
    info "NAS / network share configuration"
    ask "NAS server address (hostname or IP, e.g. 192.168.3.150):"
    read -r NAS_SERVER
    ask "Share name on that server (e.g. Channels):"
    read -r NAS_SHARE
    ask "Mount point inside WSL2 [${MOUNT_POINT}]:"
    read -r MOUNT_INPUT
    MOUNT_POINT="${MOUNT_INPUT:-$MOUNT_POINT}"
else
    MOUNT_POINT=""
    info "Skipping NAS setup (--local-dvr). Configure DVR_MEDIA_HOST_PATH manually in .env after deploy."
fi

echo ""
echo "────────────────────────────────────────────────────────────────────"
echo "  Deploy dir : $DEPLOY_DIR"
echo "  DVR URL    : $CHANNELS_DVR_URL"
if [[ "$LOCAL_DVR" == false ]]; then
    echo "  NAS        : //${NAS_SERVER}/${NAS_SHARE} → ${MOUNT_POINT}"
fi
echo "────────────────────────────────────────────────────────────────────"
ask "Continue? [Y/n]"
read -r CONFIRM
if [[ "${CONFIRM,,}" == "n" ]]; then echo "Aborted."; exit 0; fi
echo ""

# ══════════════════════════════════════════════════════════════════════════
# STEP 1 — Install Docker Engine
# ══════════════════════════════════════════════════════════════════════════
info "Step 1/6 — Docker Engine"

if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    success "Docker already installed and running ($(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'unknown'))"
else
    info "Installing Docker Engine..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq ca-certificates curl gnupg lsb-release

    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    sudo usermod -aG docker "$USER"
    success "Docker Engine installed"
fi

# Ensure daemon is running
if ! docker info &>/dev/null 2>&1; then
    sudo service docker start
    sleep 2
fi

# Fix compose plugin symlink (Docker Desktop leftovers or apt path mismatch)
if ! docker compose version &>/dev/null 2>&1; then
    APT_COMPOSE="$(find /usr/libexec/docker/cli-plugins /usr/lib/docker/cli-plugins \
        -name docker-compose 2>/dev/null | head -1 || true)"
    if [[ -n "$APT_COMPOSE" ]]; then
        sudo mkdir -p /usr/local/lib/docker/cli-plugins
        sudo ln -sf "$APT_COMPOSE" /usr/local/lib/docker/cli-plugins/docker-compose
        success "docker compose plugin symlinked from $APT_COMPOSE"
    else
        warn "docker compose not found — you may need to install docker-compose-plugin manually"
    fi
fi
docker compose version | grep -oP '\d+\.\d+\.\d+' | head -1 | xargs -I{} success "docker compose {}"

# ══════════════════════════════════════════════════════════════════════════
# STEP 2 — NVIDIA Container Toolkit
# ══════════════════════════════════════════════════════════════════════════
info "Step 2/6 — NVIDIA Container Toolkit"

if docker info 2>/dev/null | grep -q 'nvidia'; then
    success "nvidia runtime already registered"
else
    info "Installing nvidia-container-toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null

    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y -qq nvidia-container-toolkit

    sudo nvidia-ctk runtime configure --runtime=docker --set-as-default 2>/dev/null || \
        sudo nvidia-ctk runtime configure --runtime=docker
    sudo service docker restart
    sleep 2
    success "nvidia-container-toolkit installed and registered"
fi

# Quick GPU test
if docker run --rm --gpus all --runtime=nvidia nvidia/cuda:12.1.0-base-ubuntu22.04 \
        nvidia-smi -L &>/dev/null 2>&1; then
    GPU_NAME=$(docker run --rm --gpus all --runtime=nvidia \
        nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "GPU")
    success "GPU visible in container: $GPU_NAME"
else
    warn "GPU container test failed. Check that nvidia-smi works on Windows and CUDA >= 12.2."
    warn "Continuing — GPU may still work at runtime."
fi

# ══════════════════════════════════════════════════════════════════════════
# STEP 3 — NAS mount
# ══════════════════════════════════════════════════════════════════════════
info "Step 3/6 — NAS mount"

if [[ "$LOCAL_DVR" == false ]]; then
    sudo apt-get install -y -qq cifs-utils

    CRED_FILE="/etc/cifs-credentials-py-captions"

    sudo mkdir -p "$MOUNT_POINT"

    # Mount with credential retry loop
    if mountpoint -q "$MOUNT_POINT"; then
        success "${MOUNT_POINT} already mounted"
    else
        while true; do
            ask "NAS username (leave blank for guest/no auth):"
            read -r NAS_USER
            if [[ -n "$NAS_USER" ]]; then
                ask "NAS password:"
                read -rs NAS_PASS; echo ""
                printf "username=%s\npassword=%s\n" "$NAS_USER" "$NAS_PASS" \
                    | sudo tee "$CRED_FILE" > /dev/null
                sudo chmod 600 "$CRED_FILE"
                MOUNT_OPTS="credentials=${CRED_FILE},uid=$(id -u),gid=$(id -g),iocharset=utf8"
            else
                NAS_PASS=""
                printf "username=guest\npassword=\n" | sudo tee "$CRED_FILE" > /dev/null
                sudo chmod 600 "$CRED_FILE"
                MOUNT_OPTS="guest,uid=$(id -u),gid=$(id -g),iocharset=utf8"
            fi

            if sudo mount -t cifs "//${NAS_SERVER}/${NAS_SHARE}" "$MOUNT_POINT" \
                    -o "$MOUNT_OPTS" 2>/tmp/py_captions_mount_err; then
                success "Mounted //${NAS_SERVER}/${NAS_SHARE} at ${MOUNT_POINT}"
                break
            else
                MOUNT_ERR=$(cat /tmp/py_captions_mount_err 2>/dev/null)
                error "Mount failed: $MOUNT_ERR"
                if echo "$MOUNT_ERR" | grep -qiE "permission denied|NT_STATUS_LOGON_FAILURE|error.13.|invalid credentials"; then
                    warn "Authentication failed — wrong username or password."
                    ask "Retry with different credentials? [Y/n]"
                    read -r RETRY_AUTH
                    [[ "${RETRY_AUTH,,}" == "n" ]] && error "Cannot continue without NAS mount." && exit 1
                elif echo "$MOUNT_ERR" | grep -qiE "no such host|connection refused|error.113.|error.111."; then
                    warn "Cannot reach //${NAS_SERVER}/${NAS_SHARE} — check server address and share name."
                    ask "NAS server address [${NAS_SERVER}]:"
                    read -r _NEW; NAS_SERVER="${_NEW:-$NAS_SERVER}"
                    ask "Share name [${NAS_SHARE}]:"
                    read -r _NEW; NAS_SHARE="${_NEW:-$NAS_SHARE}"
                else
                    warn "Unexpected mount error. Check server, share name, and network."
                    ask "Retry? [Y/n]"
                    read -r RETRY_AUTH
                    [[ "${RETRY_AUTH,,}" == "n" ]] && exit 1
                fi
            fi
        done
    fi

    # Shared propagation for Docker bind mount
    sudo mount --make-shared "$MOUNT_POINT"
    success "Mount propagation set to shared"

    ENTRY_COUNT=$(ls "$MOUNT_POINT" 2>/dev/null | wc -l)
    info "Contents visible at ${MOUNT_POINT}: ${ENTRY_COUNT} entries"
else
    success "Skipped (local DVR mode)"
fi

# ══════════════════════════════════════════════════════════════════════════
# STEP 4 — Clone / update repo
# ══════════════════════════════════════════════════════════════════════════
info "Step 4/6 — Repository"

if [[ -d "$DEPLOY_DIR/.git" ]]; then
    info "Repo already exists at $DEPLOY_DIR — pulling latest..."
    git -C "$DEPLOY_DIR" pull --ff-only
    success "Repository up to date"
else
    git clone "$REPO_URL" "$DEPLOY_DIR"
    success "Cloned to $DEPLOY_DIR"
fi

# ══════════════════════════════════════════════════════════════════════════
# STEP 5 — Configure .env
# ══════════════════════════════════════════════════════════════════════════
info "Step 5/6 — .env configuration"

ENV_FILE="$DEPLOY_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$DEPLOY_DIR/.env.example.nvidia" "$ENV_FILE"
    success "Created .env from .env.example.nvidia"
else
    warn ".env already exists — preserving existing config"
    warn "Review $ENV_FILE and update manually if needed"
fi

# Helper: set or update a key in .env
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

set_env "CHANNELS_DVR_URL" "$CHANNELS_DVR_URL"
set_env "DOCKER_RUNTIME"   "nvidia"
set_env "NVIDIA_VISIBLE_DEVICES" "all"

if [[ "$LOCAL_DVR" == false ]]; then
    set_env "DVR_MEDIA_HOST_PATH" "$MOUNT_POINT"
    set_env "DVR_MEDIA_MOUNT"     "$MOUNT_POINT"
    set_env "LOCAL_PATH_PREFIX"   "$MOUNT_POINT"
fi

success ".env configured"

# ══════════════════════════════════════════════════════════════════════════
# STEP 6 — Auto-start block in ~/.bashrc
# ══════════════════════════════════════════════════════════════════════════
info "Step 6/6 — Auto-start (~/.bashrc)"

MARKER="# ── py-captions auto-start"
if grep -q "$MARKER" ~/.bashrc 2>/dev/null; then
    success "Auto-start block already in ~/.bashrc"
else
    cat >> ~/.bashrc << BASHRC

${MARKER} ──────────────────────────────────────────
AUTOSTART_DEPLOY_DIR="${DEPLOY_DIR}"

# Start Docker if not running
if ! pgrep -x dockerd > /dev/null; then
    sudo service docker start 2>/dev/null
fi
BASHRC

    if [[ "$LOCAL_DVR" == false ]]; then
        cat >> ~/.bashrc << BASHRC

# Mount NAS
if ! mountpoint -q ${MOUNT_POINT}; then
    sudo mount -t cifs //${NAS_SERVER}/${NAS_SHARE} ${MOUNT_POINT} \\
        -o credentials=${CRED_FILE},uid=\$(id -u),gid=\$(id -g),iocharset=utf8 2>/dev/null
fi
sudo mount --make-shared ${MOUNT_POINT} 2>/dev/null
BASHRC
    fi

    cat >> ~/.bashrc << 'BASHRC'

# Start container if not already running
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q py-captions-for-channels; then
    (cd "$AUTOSTART_DEPLOY_DIR" && docker compose up -d 2>/dev/null)
fi
# ───────────────────────────────────────────────────────────────────────────
BASHRC
    success "Auto-start block added to ~/.bashrc"
fi

# ── Sudoers entries for passwordless auto-start commands ──────────────────
SUDOERS_FILE="/etc/sudoers.d/py-captions"
if [[ ! -f "$SUDOERS_FILE" ]]; then
    cat << SUDOERS | sudo tee "$SUDOERS_FILE" > /dev/null
# py-captions auto-start — passwordless commands
%docker ALL=(ALL) NOPASSWD: /usr/sbin/service docker start
%docker ALL=(ALL) NOPASSWD: /bin/mount -t cifs *
%docker ALL=(ALL) NOPASSWD: /bin/mount --make-shared *
SUDOERS
    sudo chmod 440 "$SUDOERS_FILE"
    success "sudoers entries written to $SUDOERS_FILE"
else
    success "sudoers file already exists"
fi

# ══════════════════════════════════════════════════════════════════════════
# LAUNCH
# ══════════════════════════════════════════════════════════════════════════
echo ""
info "Pulling image and starting container..."
cd "$DEPLOY_DIR"
# newgrp docker changes GID — run docker commands via sg if group not yet active
DOCKER_CMD="docker"
if ! groups | grep -q docker; then
    DOCKER_CMD="sg docker -c docker"
fi

$DOCKER_CMD compose pull
$DOCKER_CMD compose up -d

echo ""
echo "════════════════════════════════════════════════════════════════════"
success "Setup complete!"
echo ""
echo "  Web dashboard : http://localhost:8000"
echo "  Logs          : cd $DEPLOY_DIR && docker compose logs -f"
echo "  Deploy dir    : $DEPLOY_DIR"
echo ""
echo "  Next steps:"
echo "  1. Open http://localhost:8000 and run the Setup Wizard"
echo "  2. Go to Recordings, whitelist shows you want captioned"
echo "  3. Edit .env and set DRY_RUN=false, then:"
echo "     cd $DEPLOY_DIR && docker compose down && docker compose up -d"
echo ""
if ! groups | grep -q docker; then
    warn "Log out and back in (or run 'newgrp docker') to use Docker without sudo."
fi
echo "════════════════════════════════════════════════════════════════════"
