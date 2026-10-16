#!/usr/bin/env bash
# dvr-discovery.sh — shared DVR/recordings-mount logic for py-captions-for-channels
# installers. Sourced by both setup-linux.sh (interactive whiptail installer) and
# setup-portainer-env.sh (Portainer pre-flight config generator) so the two never
# drift apart on validation rules or mount behavior.
#
# Every function here is UI-framework-agnostic: no whiptail calls, no `read`
# prompts. Callers own the interaction; these functions just do the work and
# report a machine-readable outcome (an echoed status token, and a non-zero
# exit code on failure).
#
# Requires: PKG_MGR to be set (see _detect_pkg_mgr) before calling any
# _ensure_probe_cmd / _install_*_client function.

# ── package manager detection ────────────────────────────────────────────────
# Sets the global PKG_MGR (apt|dnf|zypper). Exits 1 on an unsupported distro.
_detect_pkg_mgr() {
    local distro_id="${1:-}"
    if [[ -z "$distro_id" && -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        source /etc/os-release
        distro_id="${ID:-unknown}"
    fi
    case "$distro_id" in
        ubuntu|debian|linuxmint|pop|elementary|neon) PKG_MGR=apt ;;
        fedora|rhel|almalinux|rocky|centos|ol)        PKG_MGR=dnf ;;
        opensuse*|sles)                                PKG_MGR=zypper ;;
        *)
            if   command -v apt-get &>/dev/null; then PKG_MGR=apt
            elif command -v dnf     &>/dev/null; then PKG_MGR=dnf
            elif command -v zypper  &>/dev/null; then PKG_MGR=zypper
            else
                echo "Unsupported distro — could not detect apt/dnf/zypper." >&2
                return 1
            fi ;;
    esac
}

# ── LAN IP detection (used to pre-fill DVR URL / NAS server prompts) ─────────
_detect_lan_ip() {
    hostname -I 2>/dev/null | tr ' ' '\n' \
        | grep -Ev '^(127\.|169\.|::1$)' \
        | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
        | head -1
}

# ── Channels DVR URL validation ──────────────────────────────────────────────
# _validate_dvr_url URL
# Checks format (scheme://host:port) and live reachability (curl .../dvr).
# Echoes exactly one of: ok | bad_format | bad_ipv4 | unreachable
# Returns 0 only for "ok".
_validate_dvr_url() {
    local url="$1"
    if ! echo "$url" | grep -qE '^https?://[^/:]+:[0-9]{2,5}(/.*)?$'; then
        echo "bad_format"
        return 1
    fi
    local host
    host=$(echo "$url" | grep -oE '//[^/:]+' | tr -d '/')
    if echo "$host" | grep -qE '^[0-9]+(\.[0-9]+)*$'; then
        local octets
        octets=$(echo "$host" | tr -cd '.' | wc -c)
        if [[ "$octets" -ne 3 ]]; then
            echo "bad_ipv4"
            return 1
        fi
    fi
    if curl -fsS --max-time 5 "${url%/}/dvr" >/dev/null 2>&1; then
        echo "ok"
        return 0
    fi
    echo "unreachable"
    return 1
}

# ── storage autodiscovery helpers (best-effort) ──────────────────────────────
# _ensure_probe_cmd CMD [NOTIFY_FN]
# Installs the package providing CMD (showmount|smbclient) if missing.
# NOTIFY_FN, if given, is called with a one-line status message before
# installing (e.g. a whiptail infobox in setup-linux.sh, or `echo` elsewhere).
_ensure_probe_cmd() {
    local cmd="$1" notify_fn="${2:-}"
    command -v "$cmd" &>/dev/null && return 0

    case "$cmd" in
        showmount)
            [[ -n "$notify_fn" ]] && "$notify_fn" "Installing NFS tools for export discovery..."
            case "$PKG_MGR" in
                apt)    sudo apt-get install -y -qq nfs-common >>"${LOG:-/dev/null}" 2>&1 || true ;;
                dnf)    sudo dnf install -y -q nfs-utils >>"${LOG:-/dev/null}" 2>&1 || true ;;
                zypper) sudo zypper install -y nfs-client >>"${LOG:-/dev/null}" 2>&1 || true ;;
            esac
            ;;
        smbclient)
            [[ -n "$notify_fn" ]] && "$notify_fn" "Installing smbclient for share discovery..."
            case "$PKG_MGR" in
                apt)    sudo apt-get install -y -qq smbclient >>"${LOG:-/dev/null}" 2>&1 || true ;;
                dnf)    sudo dnf install -y -q samba-client >>"${LOG:-/dev/null}" 2>&1 || true ;;
                zypper) sudo zypper install -y samba-client >>"${LOG:-/dev/null}" 2>&1 || true ;;
            esac
            ;;
    esac

    command -v "$cmd" &>/dev/null
}

_discover_nfs_exports() {
    local server="$1"
    command -v showmount &>/dev/null || return 1
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
    command -v smbclient &>/dev/null || return 1
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

# ── client package installs ──────────────────────────────────────────────────
_install_cifs_client() {
    if ! command -v mount.cifs &>/dev/null; then
        case "$PKG_MGR" in
            apt)    sudo apt-get install -y -qq cifs-utils >>"${LOG:-/dev/null}" 2>&1 ;;
            dnf)    sudo dnf install -y -q cifs-utils >>"${LOG:-/dev/null}" 2>&1 ;;
            zypper) sudo zypper install -y cifs-utils >>"${LOG:-/dev/null}" 2>&1 ;;
        esac
    fi
    if ! command -v smbclient &>/dev/null; then
        case "$PKG_MGR" in
            apt)    sudo apt-get install -y -qq smbclient >>"${LOG:-/dev/null}" 2>&1 ;;
            dnf)    sudo dnf install -y -q samba-client >>"${LOG:-/dev/null}" 2>&1 ;;
            zypper) sudo zypper install -y samba-client >>"${LOG:-/dev/null}" 2>&1 ;;
        esac
    fi
}

_install_nfs_client() {
    if ! command -v mount.nfs &>/dev/null && ! command -v mount.nfs4 &>/dev/null; then
        case "$PKG_MGR" in
            apt)    sudo apt-get install -y -qq nfs-common >>"${LOG:-/dev/null}" 2>&1 ;;
            dnf)    sudo dnf install -y -q nfs-utils >>"${LOG:-/dev/null}" 2>&1 ;;
            zypper) sudo zypper install -y nfs-client >>"${LOG:-/dev/null}" 2>&1 ;;
        esac
    fi
}

# ── mount execution ───────────────────────────────────────────────────────────
# _mount_cifs_share SERVER SHARE MOUNT_POINT CRED_FILE [USER] [PASS]
# Idempotent: no-ops if already mounted. Writes CRED_FILE (mode 600).
# Echoes exactly one of: already_mounted | ok | auth_failed | unreachable | error:<msg>
# Returns 0 for already_mounted/ok, 1 otherwise.
_mount_cifs_share() {
    local server="$1" share="$2" mount_point="$3" cred_file="$4" user="${5:-}" pass="${6:-}"
    _install_cifs_client
    sudo mkdir -p "$mount_point"

    if mountpoint -q "$mount_point"; then
        echo "already_mounted"
        return 0
    fi

    local mount_opts
    if [[ -n "$user" ]]; then
        printf "username=%s\npassword=%s\n" "$user" "$pass" | sudo tee "$cred_file" >/dev/null
        mount_opts="credentials=${cred_file},uid=$(id -u),gid=$(id -g),iocharset=utf8"
    else
        printf "username=guest\npassword=\n" | sudo tee "$cred_file" >/dev/null
        mount_opts="guest,uid=$(id -u),gid=$(id -g),iocharset=utf8"
    fi
    sudo chmod 600 "$cred_file"

    local err_file; err_file=$(mktemp)
    if sudo mount -t cifs "//${server}/${share}" "$mount_point" -o "$mount_opts" 2>"$err_file"; then
        sudo mount --make-shared "$mount_point"
        rm -f "$err_file"
        echo "ok"
        return 0
    fi

    local err; err=$(cat "$err_file" 2>/dev/null); rm -f "$err_file"
    if echo "$err" | grep -qiE "permission denied|NT_STATUS_LOGON_FAILURE|error.13.|invalid credentials"; then
        echo "auth_failed"
    elif echo "$err" | grep -qiE "no such host|connection refused|error.113.|error.111."; then
        echo "unreachable"
    else
        echo "error:${err}"
    fi
    return 1
}

# _mount_nfs_export SERVER EXPORT MOUNT_POINT
# Idempotent: no-ops if already mounted.
# Echoes exactly one of: already_mounted | ok | error:<msg>
# Returns 0 for already_mounted/ok, 1 otherwise.
_mount_nfs_export() {
    local server="$1" export_path="$2" mount_point="$3"
    _install_nfs_client
    sudo mkdir -p "$mount_point"

    if mountpoint -q "$mount_point"; then
        echo "already_mounted"
        return 0
    fi

    local err_file; err_file=$(mktemp)
    if sudo mount -t nfs4 "${server}:${export_path}" "$mount_point" \
            -o "rw,nfsvers=4.1,soft,timeo=60,retrans=3" 2>"$err_file"; then
        sudo mount --make-shared "$mount_point"
        rm -f "$err_file"
        echo "ok"
        return 0
    fi

    local err; err=$(cat "$err_file" 2>/dev/null); rm -f "$err_file"
    echo "error:${err}"
    return 1
}

# ── systemd persistence for CIFS/NFS mounts ──────────────────────────────────
# _install_media_mount_service PROTOCOL MOUNT_POINT SERVER SHARE_OR_EXPORT [CRED_FILE]
# PROTOCOL is "cifs" or "nfs". Installs a oneshot mount unit that runs before
# docker.service, with a soft (Wants=) dependency so it never blocks Docker if
# the share is temporarily unreachable at boot.
_install_media_mount_service() {
    local protocol="$1" mount_point="$2" server="$3" share_or_export="$4" cred_file="${5:-}"
    # Additional instances (see _pcc_* below) get their own unit and script so
    # installing one never replaces another instance's mount.
    local sfx="${PCC_INSTANCE_SUFFIX:-}"
    local unit="py-captions-mount${sfx}.service"
    local mount_script="/usr/local/bin/py-captions-mount${sfx}.sh"

    if [[ "$protocol" == "cifs" ]]; then
        sudo tee "$mount_script" >/dev/null <<SVC_SCRIPT
#!/bin/bash
# Auto-generated by py-captions-for-channels — do not edit manually.
# Mounts Channels DVR CIFS share and enables bind-mount propagation.
for _try in 1 2 3; do
    mountpoint -q "${mount_point}" && break
    /bin/mount -t cifs "//${server}/${share_or_export}" "${mount_point}" \\
        -o "credentials=${cred_file},uid=$(id -u),gid=$(id -g),iocharset=utf8" 2>&1 && break
    [ "\$_try" -lt 3 ] && sleep \$(( _try * 3 ))
done
/bin/mount --make-shared "${mount_point}" 2>/dev/null || true
SVC_SCRIPT
    else
        sudo tee "$mount_script" >/dev/null <<SVC_SCRIPT
#!/bin/bash
# Auto-generated by py-captions-for-channels — do not edit manually.
# Mounts Channels DVR NFS export and enables bind-mount propagation.
for _try in 1 2 3; do
    mountpoint -q "${mount_point}" && break
    /bin/mount -t nfs4 "${server}:${share_or_export}" "${mount_point}" \\
        -o "rw,nfsvers=4.1,soft,timeo=60,retrans=3" 2>&1 && break
    [ "\$_try" -lt 3 ] && sleep \$(( _try * 3 ))
done
/bin/mount --make-shared "${mount_point}" 2>/dev/null || true
SVC_SCRIPT
    fi
    sudo chmod +x "$mount_script"

    sudo tee "/etc/systemd/system/${unit}" >/dev/null <<SVC_UNIT
[Unit]
Description=Mount recordings share for py-captions-for-channels
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
TimeoutStartSec=60
ExecStart=${mount_script}

[Install]
WantedBy=multi-user.target
SVC_UNIT

    sudo mkdir -p /etc/systemd/system/docker.service.d
    sudo tee "/etc/systemd/system/docker.service.d/py-captions-mount${sfx}.conf" >/dev/null <<SVC_OVERRIDE
[Unit]
After=${unit}
Wants=${unit}
SVC_OVERRIDE

    sudo systemctl daemon-reload >>"${LOG:-/dev/null}" 2>&1 || true
    sudo systemctl enable "${unit}" >>"${LOG:-/dev/null}" 2>&1 || true
}

# ── Multiple instances on one Docker host ────────────────────────────────────
# Several instances (one per Channels DVR) can share one GPU machine; they
# take turns on the GPU through the shared py-captions-gpu-slots volume (see
# docker-compose.yml). These helpers let an installer notice an existing
# instance and give the new one names and ports that don't collide with it.

_PCC_SERVICE_LABEL="com.docker.compose.service=py-captions"

_pcc_docker() {
    command -v docker &>/dev/null || return 1
    docker "$@" 2>/dev/null || sudo -n docker "$@" 2>/dev/null
}

# One line per existing instance (running or stopped): "<container>|<compose dir>"
_pcc_existing_instances() {
    _pcc_docker ps -a --filter "label=${_PCC_SERVICE_LABEL}" \
        --format '{{.Names}}|{{.Label "com.docker.compose.project.working_dir"}}' || true
}

# Host ports reserved by any container, running or stopped — a stopped
# instance isn't listening, but would fail to start if its port were reused.
_pcc_container_ports() {
    local ids
    ids=$(_pcc_docker ps -aq) || return 0
    [[ -n "$ids" ]] || return 0
    # shellcheck disable=SC2086
    _pcc_docker inspect --format \
        '{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}{{.HostPort}} {{end}}{{end}}' \
        $ids | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u || true
}

_pcc_port_in_use() {
    local p="$1"
    ss -tlnH "sport = :${p}" 2>/dev/null | grep -q ":${p}" && return 0
    grep -qx "$p" <<<"${_PCC_USED_PORTS:-}"
}

# First port >= $1 that is neither listening nor reserved by a container.
# Call _pcc_scan_ports first to load container reservations.
_pcc_free_port() {
    local p="$1"
    while _pcc_port_in_use "$p"; do p=$((p + 1)); done
    echo "$p"
}

_pcc_scan_ports() {
    _PCC_USED_PORTS=$(_pcc_container_ports)
}

# "Bedroom DVR" -> "bedroom-dvr" (for container, folder and mount names)
_pcc_slug() {
    local s
    s=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-24)
    echo "${s:-dvr2}"
}

# True if the container already mounts a GPU slot directory, i.e. it runs a
# docker-compose.yml new enough to share the GPU with other instances.
_pcc_shares_gpu() {
    _pcc_docker inspect "$1" \
        --format '{{range .Mounts}}{{if eq .Destination "/gpu-slots"}}yes{{end}}{{end}}' \
        | grep -q yes
}

# Bring an existing instance up to date (git checkout + compose installs only)
# so it shares the GPU. Returns 1 if it isn't a checkout we can update.
_pcc_update_instance() {
    local dir="$1"
    [[ -d "$dir/.git" && -f "$dir/docker-compose.yml" ]] || return 1
    git -C "$dir" pull --ff-only >>"${LOG:-/dev/null}" 2>&1 || return 1
    (cd "$dir" && _pcc_docker compose pull >>"${LOG:-/dev/null}" 2>&1 \
        && _pcc_docker compose up -d >>"${LOG:-/dev/null}" 2>&1)
}
