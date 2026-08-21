#!/usr/bin/env bash
# setup-portainer-env.sh — pre-flight config generator for Portainer deployments
#                           of py-captions-for-channels.
#
# Portainer's "Web editor"/"Upload" stack types run docker-compose.yml from
# Portainer's own internal working directory, not a path on your host — and
# the recordings volume (channels_media) is a named volume with driver_opts,
# which Docker will NOT auto-create if the target path doesn't exist yet
# (unlike a plain bind mount). Typing DVR_MEDIA_* into Portainer's
# environment-variables UI by hand, with no validation, is exactly how you
# end up with a cryptic "failed to mount local volume: ... no such file or
# directory" error at deploy time instead of a clear one beforehand.
#
# This script does everything setup-linux.sh does to gather and validate that
# same information — reachability-checked DVR URL, discovered/mounted
# recordings storage — but stops short of installing Docker or starting the
# container itself, since Portainer already owns that part. It writes one
# ready-to-use .env file that serves two purposes at once:
#   1. Mounted into the container at /app/.env (via HOST_ENV_FILE) as the
#      app's live-reloadable runtime config.
#   2. Uploaded as-is into Portainer's stack via "Load variables from .env
#      file" (Environment variables section, Portainer CE 2.x+) — which
#      covers the compose-level substitutions (DVR_MEDIA_*, HOST_DATA_DIR,
#      etc.) that Docker needs *before* the container exists and can never
#      get from the mounted /app/.env alone.
#
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main/scripts/setup-portainer-env.sh)
# or, from a repo checkout:
#   bash scripts/setup-portainer-env.sh
# ---------------------------------------------------------------------------

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main"
DEFAULT_DEPLOY_DIR="$HOME/py-captions-for-channels"
LOG=/tmp/py_captions_portainer_setup.log
: > "$LOG"

if [[ $EUID -eq 0 ]]; then
    echo "Do not run as root. Run as your normal sudo-capable user." >&2
    exit 1
fi

# ── load the shared discovery/validation/mount library ──────────────────────
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$_SCRIPT_DIR/lib/dvr-discovery.sh" ]]; then
    # shellcheck source=lib/dvr-discovery.sh
    source "$_SCRIPT_DIR/lib/dvr-discovery.sh"
else
    # Running via curl-pipe with no local checkout — fetch it.
    _LIB=$(mktemp)
    curl -fsSL "$REPO_RAW/scripts/lib/dvr-discovery.sh" -o "$_LIB"
    # shellcheck source=/dev/null
    source "$_LIB"
fi

echo "py-captions-for-channels — Portainer pre-flight config generator"
echo "=================================================================="
echo "This gathers and validates the info Docker needs before the container"
echo "exists (DVR URL, recordings path/share), then writes a ready .env file"
echo "for you to upload into Portainer. It does not touch Docker or Portainer"
echo "itself."
echo ""

_detect_pkg_mgr
echo "Package manager: $PKG_MGR"

# ── deploy directory ──────────────────────────────────────────────────────────
read -rp "Where should the config live? [$DEFAULT_DEPLOY_DIR]: " DEPLOY_DIR
DEPLOY_DIR="${DEPLOY_DIR:-$DEFAULT_DEPLOY_DIR}"
mkdir -p "$DEPLOY_DIR/data"
# Named without a leading dot on purpose: this file gets uploaded through a
# browser file picker (Portainer's "Load variables from .env file" button),
# and most OS file pickers hide dotfiles by default — a literal ".env" here
# is invisible in that dialog even when searched for by name. The container
# always sees it as /app/.env regardless of this host-side filename (see
# docker-compose.yml's HOST_ENV_FILE mount and config.py's fixed read path),
# so the rename is free.
ENV_FILE="$DEPLOY_DIR/py-captions-for-channels.env"

# ── LAN IP hint ───────────────────────────────────────────────────────────────
LAN_IP=$(_detect_lan_ip || true)
LAN_HINT="${LAN_IP:-192.168.1.5}"

# ── Channels DVR URL — validated, not just collected ─────────────────────────
CHANNELS_DVR_URL=""
while [[ -z "$CHANNELS_DVR_URL" ]]; do
    read -rp "Channels DVR server URL (e.g. http://${LAN_HINT}:8089): " CHANNELS_DVR_URL
    if [[ -z "$CHANNELS_DVR_URL" ]]; then
        echo "  Required — cannot continue without a DVR URL."
        continue
    fi
    _dvr_check=$(_validate_dvr_url "$CHANNELS_DVR_URL") || true
    case "$_dvr_check" in
        bad_format)
            echo "  Invalid: must start with http:// (or https://) and include a port, e.g. http://${LAN_HINT}:8089"
            echo "    Got: $CHANNELS_DVR_URL"
            CHANNELS_DVR_URL=""
            ;;
        bad_ipv4)
            echo "  Invalid IP address in that URL — check for typos."
            CHANNELS_DVR_URL=""
            ;;
        unreachable)
            echo "  Could not reach $CHANNELS_DVR_URL — Channels DVR not running, wrong IP/port, or a firewall is blocking it."
            read -rp "  Continue with this URL anyway? [y/N]: " _cont
            [[ "$_cont" =~ ^[Yy]$ ]] || CHANNELS_DVR_URL=""
            ;;
        ok)
            echo "  ✔ Connected to Channels DVR at $CHANNELS_DVR_URL"
            ;;
    esac
done

# ── hardware profile ──────────────────────────────────────────────────────────
echo ""
echo "Hardware profile:"
echo "  1) NVIDIA GPU"
echo "  2) CPU only"
echo "  3) Intel GPU (VA-API hardware video encode/decode; not transcription — see docs/SYSTEM_REQUIREMENTS.md)"
# AMD (AMF/VAAPI) is not offered here — the codebase itself marks that path
# "stubbed / untested" (see embed_captions.py), so it isn't a real choice yet.
read -rp "Choose [1-3]: " _hw_choice
case "$_hw_choice" in
    1) HW_PROFILE="nvidia" ;;
    3) HW_PROFILE="intel" ;;
    *) HW_PROFILE="cpu" ;;
esac

# ── fetch the matching .env.example.* template as our starting point ────────
_TEMPLATE="$_SCRIPT_DIR/../.env.example.${HW_PROFILE}"
if [[ -f "$_TEMPLATE" ]]; then
    cp "$_TEMPLATE" "$ENV_FILE"
else
    curl -fsSL "$REPO_RAW/.env.example.${HW_PROFILE}" -o "$ENV_FILE"
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

set_env "CHANNELS_DVR_URL" "$CHANNELS_DVR_URL"

case "$HW_PROFILE" in
    nvidia)
        set_env "DOCKER_RUNTIME" "nvidia"
        set_env "NVIDIA_VISIBLE_DEVICES" "all"
        ;;
    *)
        set_env "DOCKER_RUNTIME" "runc"
        set_env "NVIDIA_VISIBLE_DEVICES" ""
        ;;
esac

# ── recordings storage — validated and mounted before Docker ever sees it ───
echo ""
echo "Where are the recordings files physically stored?"
echo "  1) On this machine (local disk or already-mounted path)"
echo "  2) On a NAS / remote machine"
read -rp "Choose [1-2]: " _storage_choice

NAS_SERVER="" NAS_SHARE="" NAS_EXPORT="" MOUNT_POINT="/mnt/channels"
CRED_FILE="/etc/cifs-credentials-py-captions"
STORAGE_TYPE="local"

if [[ "$_storage_choice" == "2" ]]; then
    read -rp "NAS address [${LAN_HINT}]: " NAS_SERVER
    NAS_SERVER="${NAS_SERVER:-$LAN_HINT}"

    echo "Probing ${NAS_SERVER} for NFS exports and SMB shares..."
    _ensure_probe_cmd showmount || true
    _ensure_probe_cmd smbclient || true
    _AUTO_NFS=$(_discover_nfs_exports "$NAS_SERVER" || true)
    _AUTO_SMB=$(_discover_smb_shares "$NAS_SERVER" || true)

    if [[ -n "${_AUTO_NFS:-}" ]]; then
        STORAGE_TYPE="nfs"
        _best=$(printf '%s\n' "$_AUTO_NFS" | _best_nfs_export_from_list)
        echo "Found NFS exports:"; printf '%s\n' "$_AUTO_NFS"
        read -rp "Export path to use [${_best:-/tank/AllMedia/Channels}]: " NAS_EXPORT
        NAS_EXPORT="${NAS_EXPORT:-${_best:-/tank/AllMedia/Channels}}"
    elif [[ -n "${_AUTO_SMB:-}" ]]; then
        STORAGE_TYPE="cifs"
        _best=$(printf '%s\n' "$_AUTO_SMB" | _best_smb_share_from_list)
        echo "Found SMB shares:"; printf '%s\n' "$_AUTO_SMB"
        read -rp "Share name to use [${_best:-Channels}]: " NAS_SHARE
        NAS_SHARE="${NAS_SHARE:-${_best:-Channels}}"
    else
        echo "No shares auto-detected on ${NAS_SERVER}."
        read -rp "Protocol — nfs or cifs [cifs]: " STORAGE_TYPE
        STORAGE_TYPE="${STORAGE_TYPE:-cifs}"
        if [[ "$STORAGE_TYPE" == "nfs" ]]; then
            read -rp "NFS export path: " NAS_EXPORT
        else
            read -rp "SMB share name: " NAS_SHARE
        fi
    fi

    read -rp "Local mount point [$MOUNT_POINT]: " _mp
    MOUNT_POINT="${_mp:-$MOUNT_POINT}"

    if [[ "$STORAGE_TYPE" == "cifs" ]]; then
        read -rp "Username for //${NAS_SERVER}/${NAS_SHARE} (blank for guest): " NAS_USER
        NAS_PASS=""
        if [[ -n "$NAS_USER" ]]; then
            read -rsp "Password: " NAS_PASS; echo ""
        fi
        while true; do
            echo "Mounting //${NAS_SERVER}/${NAS_SHARE} ..."
            _result=$(_mount_cifs_share "$NAS_SERVER" "$NAS_SHARE" "$MOUNT_POINT" "$CRED_FILE" "$NAS_USER" "$NAS_PASS") || true
            case "$_result" in
                already_mounted) echo "  Already mounted at $MOUNT_POINT."; break ;;
                ok) echo "  ✔ Mounted ($(ls "$MOUNT_POINT" 2>/dev/null | wc -l) entries visible)."; break ;;
                auth_failed)
                    echo "  Wrong username or password. Try again."
                    read -rp "Username (blank for guest): " NAS_USER
                    NAS_PASS=""
                    [[ -n "$NAS_USER" ]] && { read -rsp "Password: " NAS_PASS; echo ""; }
                    ;;
                unreachable)
                    echo "  Cannot reach ${NAS_SERVER}."
                    read -rp "Server address [$NAS_SERVER]: " _s; NAS_SERVER="${_s:-$NAS_SERVER}"
                    read -rp "Share name [$NAS_SHARE]: " _s; NAS_SHARE="${_s:-$NAS_SHARE}"
                    ;;
                *)
                    echo "  Mount failed: ${_result#error:}"
                    read -rp "  Retry? [Y/n]: " _r
                    [[ "$_r" =~ ^[Nn]$ ]] && { echo "Aborting — fix the share and re-run this script."; exit 1; }
                    ;;
            esac
        done
        _install_media_mount_service "cifs" "$MOUNT_POINT" "$NAS_SERVER" "$NAS_SHARE" "$CRED_FILE"
    else
        echo "Mounting ${NAS_SERVER}:${NAS_EXPORT} ..."
        _result=$(_mount_nfs_export "$NAS_SERVER" "$NAS_EXPORT" "$MOUNT_POINT") || true
        case "$_result" in
            already_mounted) echo "  Already mounted at $MOUNT_POINT." ;;
            ok) echo "  ✔ Mounted ($(ls "$MOUNT_POINT" 2>/dev/null | wc -l) entries visible)." ;;
            *)
                echo "  Mount failed: ${_result#error:}"
                echo "  Aborting — fix the export and re-run this script."
                exit 1
                ;;
        esac
        _install_media_mount_service "nfs" "$MOUNT_POINT" "$NAS_SERVER" "$NAS_EXPORT"
    fi
else
    read -rp "Full path to the recordings folder on this machine: " MOUNT_POINT
    if [[ ! -d "$MOUNT_POINT" ]]; then
        read -rp "'$MOUNT_POINT' doesn't exist — create it? [Y/n]: " _mk
        if [[ ! "$_mk" =~ ^[Nn]$ ]]; then
            mkdir -p "$MOUNT_POINT"
            echo "  Created $MOUNT_POINT"
        else
            echo "Aborting — the recordings path must exist before Docker can mount it."
            exit 1
        fi
    fi
fi

# Same convention as setup-linux.sh: DVR_MEDIA_TYPE is always "none" (plain
# bind of an already-real, already-mounted local path) — the actual CIFS/NFS
# mount happens above, at the OS level, not through Docker's driver_opts. This
# is the one thing Docker's volume driver can't auto-create, so by the time
# we write it to .env it is guaranteed to already exist.
set_env "DVR_MEDIA_TYPE"      "none"
set_env "DVR_MEDIA_OPTS"      "bind"
set_env "DVR_MEDIA_DEVICE"    "$MOUNT_POINT"
set_env "DVR_MEDIA_MOUNT"     "$MOUNT_POINT"
set_env "DVR_MEDIA_HOST_PATH" "$MOUNT_POINT"
set_env "DVR_RECORDINGS_PATH" "$MOUNT_POINT"
set_env "LOCAL_PATH_PREFIX"   "$MOUNT_POINT"

# ── port collision check (Portainer's own UI commonly sits on 9000) ─────────
WEBHOOK_PORT=9000
if ss -tlnH "sport = :9000" 2>/dev/null | grep -q ":9000"; then
    WEBHOOK_PORT=9001
    while ss -tlnH "sport = :${WEBHOOK_PORT}" 2>/dev/null | grep -q ":${WEBHOOK_PORT}"; do
        WEBHOOK_PORT=$((WEBHOOK_PORT + 1))
    done
    echo ""
    echo "Port 9000 is already in use on this host (likely Portainer itself)."
    echo "Using WEBHOOK_PORT=${WEBHOOK_PORT} instead."
fi
set_env "WEBHOOK_PORT" "$WEBHOOK_PORT"

# ── compose-level bind-mount targets, self-contained in this same file ──────
set_env "HOST_DATA_DIR" "$DEPLOY_DIR/data"
set_env "HOST_ENV_FILE" "$ENV_FILE"

# ── stale-volume warning ─────────────────────────────────────────────────────
# Docker named volumes are created once and then immutable: if a prior deploy
# attempt already created a *_channels_media volume (e.g. before .env had a
# real DVR_MEDIA_DEVICE), Compose silently reuses it as-is on every redeploy —
# ignoring the values in this fresh .env — and the container fails to start
# with a mount error pointing at the *old* device. Flag any candidates now,
# before that surprises anyone.
if command -v docker &>/dev/null; then
    _stale_vols=$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep -E '_channels_media$' || true)
    if [[ -n "$_stale_vols" ]]; then
        echo ""
        echo "NOTE: found existing recordings volume(s) from a previous deploy attempt:"
        echo "$_stale_vols" | sed 's/^/  - /'
        echo "If that deploy predates this .env, redeploying now will silently reuse"
        echo "the OLD volume (and its old path) instead of picking up these settings."
        echo "Remove it first if so: docker volume rm <name>  (or via Portainer -> Volumes)"
    fi
fi

echo ""
echo "=================================================================="
echo "Done. Wrote: $ENV_FILE"
echo ""
echo "  DVR URL     : $CHANNELS_DVR_URL"
echo "  Recordings  : $MOUNT_POINT"
echo "  Hardware    : $HW_PROFILE"
echo "  Webhook port: $WEBHOOK_PORT"
echo ""
echo "Next steps in Portainer:"
echo "  1. Stacks -> Add stack -> name it -> build method: Web editor"
echo "  2. Paste the contents of docker-compose.yml unmodified"
echo "     (https://github.com/jay3702/py-captions-for-channels/blob/main/docker-compose.yml)"
echo "  3. Under Environment variables, click 'Load variables from .env file'"
echo "     and upload: $ENV_FILE"
echo "  4. Deploy the stack."
echo ""
echo "That one file covers everything Docker needs before the container"
echo "starts (this host's paths) *and* everything the app needs at runtime"
echo "(DVR URL, whisper/caption settings, etc.) — no other values to type in."
