#!/usr/bin/env bash
# setup-linux.sh — first-run installer for py-captions-for-channels
#                  on a native Linux server (Ubuntu, Debian, Fedora, RHEL/Rocky/Alma, openSUSE)
#
# Run as your normal (non-root) user who has sudo access.
# Re-running is safe — all steps are idempotent.
# GPU support is detected and configured automatically; no GPU is fine too.
#
# Supported distros:
#   Ubuntu 20.04 / 22.04 / 24.04  (apt)
#   Debian 11 / 12                 (apt)
#   Fedora 37+                     (dnf)
#   RHEL / AlmaLinux / Rocky 8+    (dnf)
#   openSUSE Leap 15+              (zypper)
#
# For WSL2 on Windows, use setup-wsl.sh / setup-wsl.ps1 instead.
#
# Usage:
#   bash setup-linux.sh
# ---------------------------------------------------------------------------

set -euo pipefail

REPO_URL="https://github.com/jay3702/py-captions-for-channels.git"
DEFAULT_DEPLOY_DIR="$HOME/py-captions-for-channels"
LOG=/tmp/py_captions_install.log
BT="py-captions-for-channels — Linux installer"
W=72
ISSUES_URL="https://github.com/jay3702/py-captions-for-channels/issues/new"
CURRENT_STEP="Initializing"

# ── ensure TERM is set so whiptail can draw its TUI ──────────────────────────
export TERM="${TERM:-xterm-256color}"

# ── sanity: not root, not WSL ────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    echo "Do not run as root. Run as your normal sudo-capable user." >&2
    exit 1
fi
if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "This installer is for native Linux servers." >&2
    echo "For WSL2 on Windows, use setup-wsl.sh / setup-wsl.ps1 instead." >&2
    exit 1
fi

# ── detect Linux distro and package manager ──────────────────────────────────
PKG_MGR=""
DISTRO_ID=""
DISTRO_VER=""
DISTRO_CODENAME=""
if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    source /etc/os-release
    DISTRO_ID="${ID:-unknown}"
    DISTRO_VER="${VERSION_ID:-0}"
    DISTRO_CODENAME="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
fi

case "$DISTRO_ID" in
    ubuntu|debian|linuxmint|pop|elementary|neon) PKG_MGR=apt ;;
    fedora)                                      PKG_MGR=dnf; DOCKER_REPO=fedora ;;
    rhel|almalinux|rocky|centos|ol)              PKG_MGR=dnf; DOCKER_REPO=rhel ;;
    opensuse*|sles)                              PKG_MGR=zypper ;;
    *)
        if   command -v apt-get  &>/dev/null; then PKG_MGR=apt
        elif command -v dnf      &>/dev/null; then PKG_MGR=dnf; DOCKER_REPO=rhel
        elif command -v zypper   &>/dev/null; then PKG_MGR=zypper
        else
            echo "Unsupported distro — could not detect apt/dnf/zypper." >&2
            exit 1
        fi ;;
esac
DOCKER_REPO="${DOCKER_REPO:-$DISTRO_ID}"

# ── prime sudo early ─────────────────────────────────────────────────────────
echo ""
echo "This installer needs administrator (sudo) access for Docker, firewall, and mount config."
echo "Enter your sudo password when prompted."
sudo -v

# ── ensure whiptail and curl are available ───────────────────────────────────
# curl is used for reachability tests; not always installed on minimal images.
_prereq_missing=()
command -v whiptail &>/dev/null || _prereq_missing+=(whiptail)
command -v curl     &>/dev/null || _prereq_missing+=(curl)
if [[ ${#_prereq_missing[@]} -gt 0 ]]; then
    echo "Installing prerequisites: ${_prereq_missing[*]} ..."
    case "$PKG_MGR" in
        apt)    sudo apt-get install -y -qq whiptail curl 2>/dev/null ;;
        dnf)    sudo dnf install -y -q newt curl 2>/dev/null ;;
        zypper) sudo zypper install -y newt curl 2>/dev/null ;;
    esac
fi

# ── detect LAN IP defaults for prompts ───────────────────────────────────────
_detect_lan_ip() {
    hostname -I 2>/dev/null | tr ' ' '\n' \
        | grep -Ev '^(127\.|169\.|::1$)' \
        | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
        | head -1
}

LAN_IP=$(_detect_lan_ip || true)
if [[ -n "${LAN_IP:-}" ]]; then
    LAN_PREFIX="${LAN_IP%.*}."
else
    LAN_PREFIX="192.168.3."
fi
LAN_HINT="${LAN_PREFIX}xxx"

# ── storage autodiscovery helpers (best-effort) ──────────────────────────────
_ensure_probe_cmd() {
    local cmd="$1"
    if command -v "$cmd" &>/dev/null; then
        return 0
    fi

    case "$cmd" in
        showmount)
            wt_info "NFS Discovery" "Installing NFS tools for export discovery..."
            case "$PKG_MGR" in
                apt)    sudo apt-get install -y -qq nfs-common >> "$LOG" 2>&1 || true ;;
                dnf)    sudo dnf install -y -q nfs-utils >> "$LOG" 2>&1 || true ;;
                zypper) sudo zypper install -y nfs-client >> "$LOG" 2>&1 || true ;;
            esac
            ;;
        smbclient)
            wt_info "SMB Discovery" "Installing smbclient for share discovery..."
            case "$PKG_MGR" in
                apt)    sudo apt-get install -y -qq smbclient >> "$LOG" 2>&1 || true ;;
                dnf)    sudo dnf install -y -q samba-client >> "$LOG" 2>&1 || true ;;
                zypper) sudo zypper install -y samba-client >> "$LOG" 2>&1 || true ;;
            esac
            ;;
    esac

    command -v "$cmd" &>/dev/null
}

_discover_nfs_exports() {
    local server="$1"
    _ensure_probe_cmd showmount || return 1
    showmount -e "$server" 2>/dev/null \
        | awk 'NR>1 && $1 ~ /^\// { print $1 }' \
        | sort -u
}

_best_nfs_export_from_list() {
    awk '
    BEGIN { IGNORECASE=1 }
    {
        score=0
        if ($0 ~ /\/allmedia\/channels$/) score=130
        else if ($0 ~ /\/channels$/)      score=120
        else if ($0 ~ /channels/)          score=100
        else if ($0 ~ /recordings|media|dvr/) score=80
        printf "%04d|%s\n", score, $0
    }
    ' | sort -t'|' -k1,1nr -k2,2 | head -1 | cut -d'|' -f2-
}

_discover_smb_shares() {
    local server="$1"
    _ensure_probe_cmd smbclient || return 1
    smbclient -g -N -L "//${server}" 2>/dev/null \
        | awk -F'|' '$1 == "Disk" { print $2 }' \
        | grep -Ev '^(IPC\$|print\$)$' \
        | sort -u
}

_best_smb_share_from_list() {
    awk '
    BEGIN { IGNORECASE=1 }
    {
        score=0
        if ($0 ~ /^channels\$$/)       score=130
        else if ($0 ~ /^channels$/)     score=125
        else if ($0 ~ /channels/)       score=100
        else if ($0 ~ /recordings|media|dvr/) score=80
        printf "%04d|%s\n", score, $0
    }
    ' | sort -t'|' -k1,1nr -k2,2 | head -1 | cut -d'|' -f2-
}

# ── whiptail dialog helpers ───────────────────────────────────────────────────
_wt()      { whiptail --backtitle "$BT" "$@" 3>&1 1>&2 2>&3; }
wt_msg()   { whiptail --backtitle "$BT" --title "$1" --msgbox  "$2" "${3:-10}" "$W"; }
wt_yesno() { whiptail --backtitle "$BT" --title "$1" --yesno   "$2" "${3:-10}" "$W"; }
wt_input() { _wt --title "$1" --inputbox   "$2" "${4:-9}"  "$W" "$3"; }
wt_pass()  { _wt --title "$1" --passwordbox "$2" 9         "$W" ""; }
wt_info()  { whiptail --backtitle "$BT" --title "$1" --infobox "$2" 7 "$W" || true; }
# wt_menu "Title" "Text" [height] [list-height] tag item tag item ...
wt_menu()  { _wt --title "$1" --menu "$2" "${3:-16}" "$W" "${4:-4}" "${@:5}"; }

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
    local ai_prompt="I ran the py-captions-for-channels Linux installer and it failed. Step: '${step}'. Exit code: ${rc}. Last log: $(tail -3 \"$LOG\" 2>/dev/null | tr '\n' ' ' | cut -c1-200)"
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

_STATUS=$(mktemp)
gauge() {
    local title="$1" msg="$2" fn="$3"
    CURRENT_STEP="$title"
    echo 1 > "$_STATUS"
    {
        set +e
        $fn
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
# PRE-FLIGHT CHECKS
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Pre-flight checks"
_PREFLIGHT_WARN=()

# ── Snap Docker conflict ─────────────────────────────────────────────────────
if command -v snap &>/dev/null && snap list docker &>/dev/null 2>&1; then
    wt_msg "Pre-flight: Snap Docker Detected" \
"A snap-packaged version of Docker is installed.

It conflicts with Docker Engine (apt/dnf) which this installer needs
for GPU passthrough and reliable operation.

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
[[ ${#_busy_ports[@]} -gt 0 ]] && _PREFLIGHT_WARN+=("Port(s) ${_busy_ports[*]} are already in use.")

# ── Firewall — ufw (Ubuntu/Debian) or firewalld (RHEL/Fedora) ────────────────
if command -v ufw &>/dev/null && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
    _ufw_missing=()
    for _p in 8000 9000; do
        sudo ufw status 2>/dev/null | grep -qE "^${_p}[/ ]" || _ufw_missing+=("$_p")
    done
    if [[ ${#_ufw_missing[@]} -gt 0 ]]; then
        _PREFLIGHT_WARN+=("ufw active — ports ${_ufw_missing[*]} not open.")
        if wt_yesno "Pre-flight: ufw Ports" \
"ufw (firewall) is active and port(s) ${_ufw_missing[*]} are not open.

This will block the web UI and webhooks.

Allow these ports now?" 12; then
            for _p in "${_ufw_missing[@]}"; do
                sudo ufw allow "$_p/tcp" >> "$LOG" 2>&1 || true
            done
            _PREFLIGHT_WARN=( "${_PREFLIGHT_WARN[@]/ufw active*/}" )
        fi
    fi
elif command -v firewall-cmd &>/dev/null && sudo firewall-cmd --state 2>/dev/null | grep -q "running"; then
    _fwd_missing=()
    for _p in 8000 9000; do
        sudo firewall-cmd --query-port="${_p}/tcp" 2>/dev/null | grep -q "yes" || _fwd_missing+=("$_p")
    done
    if [[ ${#_fwd_missing[@]} -gt 0 ]]; then
        _PREFLIGHT_WARN+=("firewalld active — ports ${_fwd_missing[*]} not open.")
        if wt_yesno "Pre-flight: firewalld Ports" \
"firewalld is active and port(s) ${_fwd_missing[*]} are not open.

This will block the web UI and webhooks.

Allow these ports now?" 12; then
            for _p in "${_fwd_missing[@]}"; do
                sudo firewall-cmd --add-port="${_p}/tcp" --permanent >> "$LOG" 2>&1 || true
            done
            sudo firewall-cmd --reload >> "$LOG" 2>&1 || true
            _PREFLIGHT_WARN=( "${_PREFLIGHT_WARN[@]/firewalld active*/}" )
        fi
    fi
fi

# ── Stale container ──────────────────────────────────────────────────────────
if command -v docker &>/dev/null && \
   docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qE '^py-captions'; then
    if wt_yesno "Pre-flight: Existing Container" \
"A Docker container named 'py-captions' already exists.

This may be a leftover from a previous install.  Remove it now so
docker compose can start a fresh container?" 12; then
        docker rm -f py-captions py-captions-for-channels >> "$LOG" 2>&1 || true
    else
        _PREFLIGHT_WARN+=("Existing container kept — docker compose may fail.")
    fi
fi

# ── Disk space (~5 GB for Docker images + Whisper model cache) ────────────────
_free_kb=$(df --output=avail "$HOME" 2>/dev/null | tail -1)
if [[ -n "$_free_kb" && "$_free_kb" -lt $((5 * 1024 * 1024)) ]]; then
    _free_gb=$(awk "BEGIN { printf \"%.1f\", $_free_kb / 1048576 }" 2>/dev/null || echo "?")
    _PREFLIGHT_WARN+=("Only ${_free_gb} GB free — Docker images + models need ~5 GB.")
fi

# ── Show accumulated pre-flight warnings ─────────────────────────────────────
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
Fix them first, or press OK to continue anyway." 18 || true
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
# WELCOME
# ════════════════════════════════════════════════════════════════════════════
wt_msg "Welcome" \
"This installer sets up py-captions-for-channels on this Linux server:

  • Docker Engine
    (+ NVIDIA Container Toolkit if a GPU is detected)
  • CIFS / NFS share mount if recordings are on a NAS
  • Repository clone and .env configuration
  • systemd auto-start (survives reboots, no terminal needed)

You will be asked a few questions, then the install runs
unattended.  Re-running is safe — completed steps are skipped.

Distro: ${DISTRO_ID} ${DISTRO_VER}  (${PKG_MGR})" 18

# ════════════════════════════════════════════════════════════════════════════
# GATHER CONFIGURATION  (all questions up front)
# ════════════════════════════════════════════════════════════════════════════

# ── Deploy directory ──────────────────────────────────────────────────────────
DEPLOY_DIR=$(wt_input "Deploy Location" \
    "Where should the repository be stored?\n(Press Enter for the default)" \
    "$DEFAULT_DEPLOY_DIR") || cancelled

# ── Channels DVR URL ──────────────────────────────────────────────────────────
CHANNELS_DVR_URL=""
while [[ -z "$CHANNELS_DVR_URL" ]]; do
    CHANNELS_DVR_URL=$(wt_input "Channels DVR Server" \
"Enter your Channels DVR server URL (port required):

Example:  http://192.168.1.5:8089
Detected LAN hint: http://${LAN_HINT}:8089

Tip: open http://localhost:57000 on the DVR machine to find its address." \
        "http://${LAN_HINT}:8089") || cancelled

    if [[ -z "$CHANNELS_DVR_URL" ]]; then
        wt_msg "Required" "Channels DVR URL is required." 8
        continue
    fi

    # Format check — must include port
    if ! echo "$CHANNELS_DVR_URL" | grep -qE '^https?://[^/:]+:[0-9]{2,5}(/.*)?$'; then
        wt_msg "Invalid URL" \
            "URL must include a port number.\n\nGood:  http://192.168.1.5:8089\nBad:   http://192.168.1.5\n\nPlease re-enter." 12
        CHANNELS_DVR_URL=""
        continue
    fi

    # IPv4 sanity check
    _host=$(echo "$CHANNELS_DVR_URL" | grep -oE '//[^/:]+' | tr -d '/')
    if echo "$_host" | grep -qE '^[0-9]+(\.[0-9]+)*$'; then
        _octets=$(echo "$_host" | tr -cd '.' | wc -c)
        if [[ "$_octets" -ne 3 ]]; then
            wt_msg "Invalid IP" \
                "That IP address doesn't look right:\n  $_host\n\nA valid IPv4 address has four parts separated by dots.\n\nExample:  192.168.1.5" 14
            CHANNELS_DVR_URL=""
            continue
        fi
    fi

    # Reachability test
    if curl -fsS --max-time 5 "${CHANNELS_DVR_URL%/}/dvr" >/dev/null 2>&1; then
        wt_info "Channels DVR" "✔ Connected to Channels DVR at\n  $CHANNELS_DVR_URL"
        sleep 1
    else
        if ! wt_yesno "Cannot Reach Server" \
"Could not connect to:
  $CHANNELS_DVR_URL

Common causes:
  • Wrong IP address or port
  • Channels DVR not running
  • Firewall blocking the connection

Continue with this URL anyway?" 16; then
            CHANNELS_DVR_URL=""
        fi
    fi
done

# ── Recordings storage location ─────────────────────────────────────────────
STORAGE_LOC=$(wt_menu "Recordings Storage" \
"Where are the recordings files physically stored?" 12 2 \
    "local"  "On this machine  (recordings are on a local disk or mount)" \
    "remote" "On a remote machine  (NAS or network share)") || cancelled

NAS_SERVER="" NAS_SHARE="" NAS_EXPORT="" MOUNT_POINT="/mnt/channels"
CRED_FILE="/etc/cifs-credentials-py-captions"
USE_CIFS=false; USE_NFS=false; USE_LOCAL=false
STORAGE_TYPE="other"

case "$STORAGE_LOC" in
    local)
        USE_LOCAL=true
        STORAGE_TYPE="local"
        MOUNT_POINT=$(wt_input "Local Recordings Path" \
"Full path to the recordings folder on this machine.

(Find it in Channels DVR → Settings → General → Storage Location)

Example:  /tank/AllMedia/Channels
          /opt/channels/recordings" \
            "/mnt/channels") || cancelled
        ;;
    remote)
        NAS_SERVER=$(wt_input "Remote Storage Server" \
"Address of the machine where the recordings are stored.

Detected LAN hint: ${LAN_HINT}" \
            "${LAN_HINT}") || cancelled

        # ── Try NFS first, then SMB, then fall back to manual ────────────────
        wt_info "Auto-detecting" "Probing ${NAS_SERVER} for NFS exports and SMB shares..."
        _AUTO_NFS=$(_discover_nfs_exports "$NAS_SERVER" || true)
        _AUTO_SMB=$(_discover_smb_shares  "$NAS_SERVER" || true)

        if [[ -n "${_AUTO_NFS:-}" ]]; then
            USE_NFS=true
            STORAGE_TYPE="nfs"
            _AUTO_NFS_BEST=$(printf '%s\n' "$_AUTO_NFS" | _best_nfs_export_from_list)
            NAS_EXPORT=$(wt_input "NFS — Export Path" \
"Auto-detected NFS exports on ${NAS_SERVER}:

${_AUTO_NFS}

Confirm or edit the path to mount:" \
                "${_AUTO_NFS_BEST:-/tank/AllMedia/Channels}" 16) || cancelled

        elif [[ -n "${_AUTO_SMB:-}" ]]; then
            USE_CIFS=true
            STORAGE_TYPE="cifs"
            _AUTO_SMB_BEST=$(printf '%s\n' "$_AUTO_SMB" | _best_smb_share_from_list)
            NAS_SHARE=$(wt_input "SMB — Share Name" \
"Auto-detected SMB shares on ${NAS_SERVER}:

${_AUTO_SMB}

Confirm or edit the share name:" \
                "${_AUTO_SMB_BEST:-Channels}" 16) || cancelled

        else
            # ── Neither NFS nor SMB discovered — ask manually ────────────────
            wt_msg "Discovery Failed" \
"Could not auto-detect shares on ${NAS_SERVER}.

No NFS exports or SMB shares were found at that address.
You can enter the connection details manually.
(Hidden SMB shares may require authentication — see advanced docs.)" 16 || true

            STORAGE_TYPE=$(wt_menu "Protocol" \
"What protocol does ${NAS_SERVER} use?" 12 2 \
    "nfs"  "NFS  (Linux / TrueNAS / Synology)" \
    "cifs" "SMB / CIFS  (Windows / Samba)") || cancelled

            case "$STORAGE_TYPE" in
                nfs)
                    USE_NFS=true
                    NAS_EXPORT=$(wt_input "NFS — Export Path" \
"Enter the NFS export path on ${NAS_SERVER}:

Example:  /tank/AllMedia/Channels" \
                        "/tank/AllMedia/Channels" 14) || cancelled
                    ;;
                cifs)
                    USE_CIFS=true
                    NAS_SHARE=$(wt_input "SMB — Share Name" \
"Enter the share name on ${NAS_SERVER}:

Tip: hidden shares end with \$ and won't appear in anonymous scans." \
                        "Channels" 12) || cancelled
                    ;;
            esac
        fi

        MOUNT_POINT=$(wt_input "Mount Point" \
            "Local directory to mount the remote share at:" \
            "/mnt/channels") || cancelled
        ;;
esac

# ── Confirm settings summary ──────────────────────────────────────────────────
case "$STORAGE_TYPE" in
    cifs)  _STORAGE_SUMMARY="SMB   //${NAS_SERVER}/${NAS_SHARE} → ${MOUNT_POINT}" ;;
    nfs)   _STORAGE_SUMMARY="NFS   ${NAS_SERVER}:${NAS_EXPORT} → ${MOUNT_POINT}" ;;
    local) _STORAGE_SUMMARY="Local ${MOUNT_POINT}" ;;
    *)     _STORAGE_SUMMARY="Manual (configure after install)" ;;
esac

wt_yesno "Confirm Settings" \
"Ready to install with these settings:

  Deploy dir  : $DEPLOY_DIR
  DVR URL     : $CHANNELS_DVR_URL
  Storage     : ${_STORAGE_SUMMARY}
  Distro      : ${DISTRO_ID} ${DISTRO_VER}

Proceed with installation?" 16 || cancelled

# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — Docker Engine
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Docker Engine"

if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    wt_info "Docker Engine" "Docker already installed — skipping."
    sleep 1
else
    _docker_install_apt() {
        echo 5
        sudo apt-get update -qq                                          >> "$LOG" 2>&1
        echo 10
        sudo apt-get install -y -qq \
            ca-certificates curl gnupg lsb-release                      >> "$LOG" 2>&1
        echo 18
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        echo 28
        # Use the OS codename; for distros derived from Ubuntu fall back to ubuntu
        _codename="${DISTRO_CODENAME:-$(lsb_release -cs 2>/dev/null || echo focal)}"
        # Derive download URL segment — Docker only publishes ubuntu and debian
        _docker_distro="ubuntu"
        [[ "$DISTRO_ID" == "debian" ]] && _docker_distro="debian"
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/${_docker_distro} ${_codename} stable" \
            | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        echo 35
        sudo apt-get update -qq                                          >> "$LOG" 2>&1
        echo 50
        sudo apt-get install -y -qq \
            docker-ce docker-ce-cli containerd.io \
            docker-buildx-plugin docker-compose-plugin                   >> "$LOG" 2>&1
        echo 85
        sudo usermod -aG docker "$USER"                                  >> "$LOG" 2>&1
        sudo systemctl enable --now docker                               >> "$LOG" 2>&1
        echo 100
    }

    _docker_install_dnf() {
        echo 5
        sudo dnf install -y -q dnf-plugins-core                         >> "$LOG" 2>&1
        echo 12
        # Docker publishes repos for fedora and rhel/centos; use the right one
        local _dr="${DOCKER_REPO:-rhel}"
        sudo dnf config-manager \
            --add-repo "https://download.docker.com/linux/${_dr}/docker-ce.repo" >> "$LOG" 2>&1
        echo 25
        sudo dnf install -y \
            docker-ce docker-ce-cli containerd.io \
            docker-buildx-plugin docker-compose-plugin                   >> "$LOG" 2>&1
        echo 85
        sudo usermod -aG docker "$USER"                                  >> "$LOG" 2>&1
        sudo systemctl enable --now docker                               >> "$LOG" 2>&1
        echo 100
    }

    _docker_install_zypper() {
        echo 10
        sudo zypper install -y docker docker-compose                     >> "$LOG" 2>&1
        echo 80
        sudo usermod -aG docker "$USER"                                  >> "$LOG" 2>&1
        sudo systemctl enable --now docker                               >> "$LOG" 2>&1
        echo 100
    }

    case "$PKG_MGR" in
        apt)    gauge "Docker Engine" "Installing Docker Engine — please wait..." _docker_install_apt ;;
        dnf)    gauge "Docker Engine" "Installing Docker Engine — please wait..." _docker_install_dnf ;;
        zypper) gauge "Docker Engine" "Installing Docker Engine — please wait..." _docker_install_zypper ;;
    esac
fi

# Ensure daemon is running
if ! docker info &>/dev/null 2>&1; then
    wt_info "Docker Engine" "Starting Docker daemon..."
    sudo systemctl start docker && sleep 3
fi

# Ensure the invoking user can run Docker without sudo (idempotent).
# This must run even when Docker was already present before this installer.
DOCKER_GROUP_ADDED=false
_ensure_docker_group_membership() {
    sudo groupadd -f docker >> "$LOG" 2>&1 || true

    if id -nG "$USER" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
        return 0
    fi

    sudo usermod -aG docker "$USER" >> "$LOG" 2>&1
    DOCKER_GROUP_ADDED=true
}
_ensure_docker_group_membership

# Fix missing compose plugin symlink (can happen on some apt setups)
if ! docker compose version &>/dev/null 2>&1; then
    _APT_COMPOSE=$(find /usr/libexec/docker/cli-plugins /usr/lib/docker/cli-plugins \
        -name docker-compose 2>/dev/null | head -1 || true)
    if [[ -n "$_APT_COMPOSE" ]]; then
        sudo mkdir -p /usr/local/lib/docker/cli-plugins
        sudo ln -sf "$_APT_COMPOSE" /usr/local/lib/docker/cli-plugins/docker-compose
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — NVIDIA Container Toolkit  (auto-detect; skip if no GPU)
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="GPU Detection"
GPU_OK=false
SKIP_NVIDIA=false

if ! command -v nvidia-smi &>/dev/null || ! nvidia-smi &>/dev/null 2>&1; then
    SKIP_NVIDIA=true
    wt_info "GPU Detection" "No NVIDIA GPU detected — Whisper will run in CPU mode.\n(Slower, but fully functional.)"
    sleep 2
fi

if [[ "$SKIP_NVIDIA" == false ]]; then
    CURRENT_STEP="NVIDIA Container Toolkit"
    if docker info 2>/dev/null | grep -q 'nvidia'; then
        wt_info "NVIDIA Toolkit" "nvidia runtime already registered — skipping."
        sleep 1
    else
        _nvidia_install_apt() {
            echo 10
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
                | sudo gpg --dearmor \
                    -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
            echo 25
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
                | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
                | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
            echo 35
            sudo apt-get update -qq                                          >> "$LOG" 2>&1
            echo 55
            sudo apt-get install -y -qq nvidia-container-toolkit             >> "$LOG" 2>&1
            echo 80
            (sudo nvidia-ctk runtime configure --runtime=docker --set-as-default \
                || sudo nvidia-ctk runtime configure --runtime=docker)       >> "$LOG" 2>&1
            echo 92
            sudo systemctl restart docker                                     >> "$LOG" 2>&1
            sleep 2
            echo 100
        }
        _nvidia_install_dnf() {
            echo 10
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
                | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo > /dev/null
            echo 30
            sudo dnf install -y nvidia-container-toolkit                     >> "$LOG" 2>&1
            echo 75
            sudo nvidia-ctk runtime configure --runtime=docker               >> "$LOG" 2>&1
            echo 90
            sudo systemctl restart docker                                     >> "$LOG" 2>&1
            sleep 2
            echo 100
        }

        case "$PKG_MGR" in
            apt)    gauge "NVIDIA Toolkit" "Installing nvidia-container-toolkit — please wait..." _nvidia_install_apt ;;
            dnf)    gauge "NVIDIA Toolkit" "Installing nvidia-container-toolkit — please wait..." _nvidia_install_dnf ;;
            zypper)
                # NVIDIA does not publish zypper packages; use the dnf approach via rpm
                wt_msg "NVIDIA Toolkit" \
"Automatic NVIDIA Container Toolkit installation is not supported on openSUSE.

Please install it manually:
  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

Continuing without GPU acceleration." 14 || true
                SKIP_NVIDIA=true ;;
        esac
    fi

    if [[ "$SKIP_NVIDIA" == false ]]; then
        # GPU sanity test inside a container
        CURRENT_STEP="GPU Test"
        wt_info "GPU Test" "Testing GPU passthrough inside Docker..."
        if docker run --rm --gpus all --runtime=nvidia nvidia/cuda:12.1.0-base-ubuntu22.04 \
                nvidia-smi -L >> "$LOG" 2>&1; then
            GPU_OK=true
            GPU_NAME=$(docker run --rm --gpus all --runtime=nvidia \
                nvidia/cuda:12.1.0-base-ubuntu22.04 \
                nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "GPU detected")
            wt_msg "GPU Test" "✔ GPU visible in container:\n  $GPU_NAME\n\nGPU acceleration will be enabled." 12
        else
            wt_msg "GPU Test" \
"GPU test failed — the container will use CPU mode.

To fix later:
  1. Ensure 'nvidia-smi' works as your user
  2. Ensure the NVIDIA Container Toolkit is installed
  3. Re-run this installer — it is safe to run again.

Full log: ${LOG}" 16 || true
        fi
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — Mount (CIFS / NFS / local bind)
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Mount Setup"

if [[ "$USE_CIFS" == true ]]; then
    # ── Install cifs-utils ────────────────────────────────────────────────────
    if ! command -v mount.cifs &>/dev/null; then
        wt_info "CIFS" "Installing cifs-utils..."
        case "$PKG_MGR" in
            apt)    sudo apt-get install -y -qq cifs-utils >> "$LOG" 2>&1 ;;
            dnf)    sudo dnf install -y -q cifs-utils >> "$LOG" 2>&1 ;;
            zypper) sudo zypper install -y cifs-utils >> "$LOG" 2>&1 ;;
        esac
    fi
    if ! command -v smbclient &>/dev/null; then
        wt_info "CIFS" "Installing smbclient..."
        case "$PKG_MGR" in
            apt)    sudo apt-get install -y -qq smbclient >> "$LOG" 2>&1 ;;
            dnf)    sudo dnf install -y -q samba-client >> "$LOG" 2>&1 ;;
            zypper) sudo zypper install -y samba-client >> "$LOG" 2>&1 ;;
        esac
    fi
    sudo mkdir -p "$MOUNT_POINT"

    if mountpoint -q "$MOUNT_POINT"; then
        wt_info "CIFS Mount" "${MOUNT_POINT} is already mounted — skipping."
        sleep 1
    else
        while true; do
            NAS_USER=$(wt_input "CIFS Credentials" \
"Username for //${NAS_SERVER}/${NAS_SHARE}

(Leave blank for guest / anonymous access)" \
                "") || cancelled

            if [[ -n "$NAS_USER" ]]; then
                NAS_PASS=$(wt_pass "CIFS Credentials" \
                    "Password for ${NAS_USER}@${NAS_SERVER}:") || cancelled
                printf "username=%s\npassword=%s\n" "$NAS_USER" "$NAS_PASS" \
                    | sudo tee "$CRED_FILE" > /dev/null
                MOUNT_OPTS="credentials=${CRED_FILE},uid=$(id -u),gid=$(id -g),iocharset=utf8"
            else
                printf "username=guest\npassword=\n" | sudo tee "$CRED_FILE" > /dev/null
                MOUNT_OPTS="guest,uid=$(id -u),gid=$(id -g),iocharset=utf8"
            fi
            sudo chmod 600 "$CRED_FILE"

            wt_info "CIFS Mount" "Mounting //${NAS_SERVER}/${NAS_SHARE} ..."
            if sudo mount -t cifs "//${NAS_SERVER}/${NAS_SHARE}" "$MOUNT_POINT" \
                    -o "$MOUNT_OPTS" 2>/tmp/py_captions_mount_err; then
                break
            fi
            MOUNT_ERR=$(cat /tmp/py_captions_mount_err 2>/dev/null)
            if echo "$MOUNT_ERR" | grep -qiE "permission denied|NT_STATUS_LOGON_FAILURE|error.13.|invalid credentials"; then
                wt_msg "Authentication Failed" \
                    "Wrong username or password for //${NAS_SERVER}/${NAS_SHARE}.\n\nPlease try again." 10
            elif echo "$MOUNT_ERR" | grep -qiE "no such host|connection refused|error.113.|error.111."; then
                NAS_SERVER=$(wt_input "CIFS Unreachable" \
                    "Cannot reach ${NAS_SERVER}. Check the address.\n\nServer address:" \
                    "$NAS_SERVER") || cancelled
                NAS_SHARE=$(wt_input "CIFS Share" \
                    "Share name on ${NAS_SERVER}:" "$NAS_SHARE") || cancelled
            else
                wt_yesno "Mount Error" \
                    "Mount failed:\n\n${MOUNT_ERR}\n\nRetry?" 14 || cancelled
            fi
        done

        sudo mount --make-shared "$MOUNT_POINT"
        ENTRY_COUNT=$(ls "$MOUNT_POINT" 2>/dev/null | wc -l)
        wt_msg "CIFS Mount" \
            "Mounted //${NAS_SERVER}/${NAS_SHARE}\n  at ${MOUNT_POINT}\n  ${ENTRY_COUNT} entries visible." 11
    fi

elif [[ "$USE_NFS" == true ]]; then
    # ── Install nfs client ────────────────────────────────────────────────────
    if ! command -v mount.nfs &>/dev/null && ! command -v mount.nfs4 &>/dev/null; then
        wt_info "NFS" "Installing NFS client utilities..."
        case "$PKG_MGR" in
            apt)    sudo apt-get install -y -qq nfs-common >> "$LOG" 2>&1 ;;
            dnf)    sudo dnf install -y -q nfs-utils >> "$LOG" 2>&1 ;;
            zypper) sudo zypper install -y nfs-client >> "$LOG" 2>&1 ;;
        esac
    fi
    sudo mkdir -p "$MOUNT_POINT"

    if mountpoint -q "$MOUNT_POINT"; then
        wt_info "NFS Mount" "${MOUNT_POINT} is already mounted — skipping."
        sleep 1
    else
        wt_info "NFS Mount" "Mounting ${NAS_SERVER}:${NAS_EXPORT} ..."
        if ! sudo mount -t nfs4 "${NAS_SERVER}:${NAS_EXPORT}" "$MOUNT_POINT" \
                -o "rw,nfsvers=4.1,soft,timeo=60,retrans=3" 2>/tmp/py_captions_mount_err; then
            MOUNT_ERR=$(cat /tmp/py_captions_mount_err 2>/dev/null)
            if ! wt_yesno "NFS Mount Error" \
"Could not mount:\n  ${NAS_SERVER}:${NAS_EXPORT}\n\n${MOUNT_ERR}\n\nContinue anyway? (configure manually later)" 14; then
                cancelled
            fi
        else
            sudo mount --make-shared "$MOUNT_POINT"
            ENTRY_COUNT=$(ls "$MOUNT_POINT" 2>/dev/null | wc -l)
            wt_msg "NFS Mount" \
                "Mounted ${NAS_SERVER}:${NAS_EXPORT}\n  at ${MOUNT_POINT}\n  ${ENTRY_COUNT} entries visible." 11
        fi
    fi

elif [[ "$USE_LOCAL" == true ]]; then
    if [[ -n "$MOUNT_POINT" ]]; then
        if [[ ! -d "$MOUNT_POINT" ]]; then
            wt_msg "Path Not Found" \
"Directory '${MOUNT_POINT}' does not exist.

This is usually because the Channels DVR hasn't been configured yet,
or the path is on a drive that's not yet mounted.

The path will be written to .env — open the web UI after install
to verify the Setup Wizard detects recordings correctly." 14 || true
        fi
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — Clone / update repository
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Repository Clone"
if ! command -v git &>/dev/null; then
    case "$PKG_MGR" in
        apt)    sudo apt-get install -y -qq git >> "$LOG" 2>&1 ;;
        dnf)    sudo dnf install -y -q git >> "$LOG" 2>&1 ;;
        zypper) sudo zypper install -y git >> "$LOG" 2>&1 ;;
    esac
fi

_repo_step() {
    echo 10
    if [[ -d "$DEPLOY_DIR/.git" ]]; then
        git -C "$DEPLOY_DIR" pull --ff-only >> "$LOG" 2>&1
    else
        if [[ -d "$DEPLOY_DIR" ]]; then
            sudo rm -rf "$DEPLOY_DIR"  >> "$LOG" 2>&1
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

# Choose starter template based on GPU state
if [[ "$GPU_OK" == true ]]; then
    [[ ! -f "$ENV_FILE" ]] && cp "$DEPLOY_DIR/.env.example.nvidia" "$ENV_FILE"
else
    [[ ! -f "$ENV_FILE" ]] && cp "$DEPLOY_DIR/.env.example.cpu" "$ENV_FILE"
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

if [[ "$GPU_OK" == true ]]; then
    set_env "DOCKER_RUNTIME"         "nvidia"
    set_env "NVIDIA_VISIBLE_DEVICES" "all"
    set_env "WHISPER_DEVICE"         "auto"
    set_env "HWACCEL_DECODE"         "auto"
    set_env "GPU_ENCODER"            "auto"
else
    set_env "DOCKER_RUNTIME"         "runc"
    set_env "NVIDIA_VISIBLE_DEVICES" ""
    set_env "WHISPER_DEVICE"         "cpu"
    set_env "HWACCEL_DECODE"         "off"
    set_env "GPU_ENCODER"            "cpu"
fi

# Native Linux never needs the WSL lib path
set_env "WSL_LIB_PATH" ""

# Recordings path / mount config
if [[ -n "$MOUNT_POINT" ]]; then
    case "$STORAGE_TYPE" in
        cifs|nfs|local)
            # All storage types use a host bind-mount into the container.
            set_env "DVR_MEDIA_TYPE"      "none"
            set_env "DVR_MEDIA_DEVICE"    "$MOUNT_POINT"
            set_env "DVR_MEDIA_OPTS"      "bind"
            set_env "DVR_MEDIA_HOST_PATH" "$MOUNT_POINT"
            set_env "DVR_MEDIA_MOUNT"     "$MOUNT_POINT"
            set_env "DVR_RECORDINGS_PATH" "$MOUNT_POINT"
            set_env "LOCAL_PATH_PREFIX"   "$MOUNT_POINT"
            ;;
    esac

    # ── Auto-detect DVR_PATH_PREFIX (strip server's base path) ───────────────
    _DVR_PREFIX_PY=$(mktemp --suffix=.py)
    cat > "$_DVR_PREFIX_PY" << 'PYEOF'
import json, re, sys, os.path, urllib.request

dvr_url = sys.argv[1].rstrip('/')
prefix = ''

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

    wt_info "Path Detection" "Querying Channels DVR to auto-detect media folder prefix..."
    _DETECTED_PREFIX=$(python3 "$_DVR_PREFIX_PY" "$CHANNELS_DVR_URL" 2>/dev/null || true)
    rm -f "$_DVR_PREFIX_PY"

    if [[ -n "$_DETECTED_PREFIX" ]]; then
        _DVR_PREFIX=$(wt_input "DVR Media Folder Path" \
"Auto-detected DVR media folder prefix — confirm or edit:

  $_DETECTED_PREFIX

This is stripped from DVR-reported file paths so they map correctly
to the local mount at ${MOUNT_POINT}.
(Leave as-is unless your DVR uses a different base path.)" \
            "$_DETECTED_PREFIX") || _DVR_PREFIX="$_DETECTED_PREFIX"
    else
        _DVR_PREFIX=$(wt_input "DVR Media Folder Path" \
"Could not auto-detect the DVR media folder prefix.

Enter the base path that Channels DVR reports for its recordings
(found in Channels DVR → Settings → General → Storage Location):

Example:  /tank/AllMedia/Channels

Leave blank to configure later in the web UI Setup Wizard." \
            "") || true
    fi
    [[ -n "${_DVR_PREFIX:-}" ]] && set_env "DVR_PATH_PREFIX" "$_DVR_PREFIX"
else
    # Avoid stale host-path bind mounts from previous installs.
    set_env "DVR_MEDIA_HOST_PATH" ""
fi

# Safety: start in dry-run until user validates
# (Only set if not already explicitly false in the template)
if ! grep -q "^DRY_RUN=false" "$ENV_FILE" 2>/dev/null; then
    set_env "DRY_RUN" "true"
fi

# ════════════════════════════════════════════════════════════════════════════
# STEP 6 — systemd auto-start
# Goal: keep py-captions running 24/7 without any terminal open.
#
# Approach:
#   a) docker.service is already enabled (done during Docker install).
#   b) For CIFS/NFS: create a one-shot systemd service that mounts the share,
#      then add an ordering dependency so docker.service waits for the mount.
#   c) If docker.service is not yet running (fresh install), start it.
# The restart: unless-stopped policy in docker-compose.yml handles container
# restart automatically after docker daemon restarts.
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Auto-start (systemd)"

# Ensure docker.service is enabled (idempotent)
sudo systemctl enable docker >> "$LOG" 2>&1 || true

if [[ "$USE_CIFS" == true || "$USE_NFS" == true ]]; then
    MOUNT_SCRIPT=/usr/local/bin/py-captions-mount.sh
    if [[ "$USE_CIFS" == true ]]; then
        sudo tee "$MOUNT_SCRIPT" > /dev/null << SVC_SCRIPT
#!/bin/bash
# Auto-generated by py-captions setup-linux.sh — do not edit manually.
# Mounts Channels DVR CIFS share and enables bind-mount propagation.
for _try in 1 2 3; do
    mountpoint -q "${MOUNT_POINT}" && break
    /bin/mount -t cifs "//${NAS_SERVER}/${NAS_SHARE}" "${MOUNT_POINT}" \\
        -o "credentials=${CRED_FILE},uid=$(id -u),gid=$(id -g),iocharset=utf8" 2>&1 && break
    [ "\$_try" -lt 3 ] && sleep \$(( _try * 3 ))
done
/bin/mount --make-shared "${MOUNT_POINT}" 2>/dev/null || true
SVC_SCRIPT
    else
        sudo tee "$MOUNT_SCRIPT" > /dev/null << SVC_SCRIPT
#!/bin/bash
# Auto-generated by py-captions setup-linux.sh — do not edit manually.
# Mounts Channels DVR NFS export and enables bind-mount propagation.
for _try in 1 2 3; do
    mountpoint -q "${MOUNT_POINT}" && break
    /bin/mount -t nfs4 "${NAS_SERVER}:${NAS_EXPORT}" "${MOUNT_POINT}" \\
        -o "rw,nfsvers=4.1,soft,timeo=60,retrans=3" 2>&1 && break
    [ "\$_try" -lt 3 ] && sleep \$(( _try * 3 ))
done
/bin/mount --make-shared "${MOUNT_POINT}" 2>/dev/null || true
SVC_SCRIPT
    fi
    sudo chmod +x "$MOUNT_SCRIPT"

    sudo tee /etc/systemd/system/py-captions-mount.service > /dev/null << SVC_UNIT
[Unit]
Description=Mount recordings share for py-captions-for-channels
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
TimeoutStartSec=60
ExecStart=${MOUNT_SCRIPT}

[Install]
WantedBy=multi-user.target
SVC_UNIT

    # Make docker depend on the mount (Wants = soft dependency; won't block docker if mount fails)
    sudo mkdir -p /etc/systemd/system/docker.service.d
    sudo tee /etc/systemd/system/docker.service.d/py-captions-mount.conf > /dev/null << SVC_OVERRIDE
[Unit]
After=py-captions-mount.service
Wants=py-captions-mount.service
SVC_OVERRIDE

    sudo systemctl daemon-reload >> "$LOG" 2>&1 || true
    sudo systemctl enable py-captions-mount.service >> "$LOG" 2>&1 || true
fi

# ── sudoers for passwordless mount commands ───────────────────────────────────
SUDOERS_FILE="/etc/sudoers.d/py-captions"
cat << SUDOERS | sudo tee "$SUDOERS_FILE" > /dev/null
# py-captions auto-start — passwordless commands
%docker ALL=(ALL) NOPASSWD: /bin/systemctl start docker
%docker ALL=(ALL) NOPASSWD: /bin/systemctl enable docker
%docker ALL=(ALL) NOPASSWD: /bin/mount -t cifs *
%docker ALL=(ALL) NOPASSWD: /bin/mount -t nfs4 *
%docker ALL=(ALL) NOPASSWD: /bin/mount --make-shared *
SUDOERS
sudo chmod 440 "$SUDOERS_FILE"

# ════════════════════════════════════════════════════════════════════════════
# STEP 7 — Pull image and start container
# ════════════════════════════════════════════════════════════════════════════
CURRENT_STEP="Docker Launch"
_launch_step() {
    echo 5
    cd "$DEPLOY_DIR"
    if groups | grep -q docker; then
        docker compose pull  >> "$LOG" 2>&1
        echo 85
        docker compose up -d >> "$LOG" 2>&1
    else
        sg docker -c "docker compose pull"  >> "$LOG" 2>&1
        echo 85
        sg docker -c "docker compose up -d" >> "$LOG" 2>&1
    fi
    echo 100
}
gauge "Starting" "Pulling image and starting container (~5 GB first run)..." _launch_step

# ════════════════════════════════════════════════════════════════════════════
# WAIT FOR HEALTHY STARTUP
# ════════════════════════════════════════════════════════════════════════════
WEB_UI_PORT=$(grep -m1 '^WEB_UI_PORT' "$ENV_FILE" 2>/dev/null \
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
    STARTUP_LOGS=$(docker logs --tail 20 py-captions-for-channels 2>&1 | tail -20 || true)
    wt_msg "Startup Warning" \
"The web UI did not respond within 90 seconds.

Last container log lines:

${STARTUP_LOGS}

Setup is otherwise complete.  Try opening
${WEB_UI_URL} in a moment, or run:
  docker logs py-captions-for-channels

Full log: ${LOG}" 24 || true
    STARTUP_STATUS="\n\nNOTE: Web UI did not respond during setup — check logs."
fi
rm -f "$_STARTUP_RESULT"

NEWGRP_NOTE=""
if [[ "$DOCKER_GROUP_ADDED" == true ]] || ! groups | grep -q docker; then
    NEWGRP_NOTE="\n\nLog out and back in (or run 'newgrp docker')\n  to use Docker without sudo."
fi

# ── Get the machine's LAN IP for the dashboard link ──────────────────────────
_LAN_IP=$(hostname -I 2>/dev/null | tr ' ' '\n' \
    | grep -Ev '^(127\.|169\.|::1$)' \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
    | head -1 || echo "$(hostname)")

wt_msg "Setup Complete" \
"py-captions-for-channels is running!${STARTUP_STATUS}

  Web dashboard   : http://${_LAN_IP}:${WEB_UI_PORT}
  Deploy dir      : $DEPLOY_DIR
  Install log     : $LOG

Next steps:
  1. Open http://${_LAN_IP}:${WEB_UI_PORT} in your browser
  2. Click ⚙ Setup Wizard to verify the recordings path
  3. Go to Recordings and whitelist shows to caption
  4. Set DRY_RUN=false in Settings when you are ready to process${NEWGRP_NOTE}" 26

rm -f "$_STATUS"
