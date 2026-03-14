#!/usr/bin/env bash
# teardown-wsl.sh — removes all py-captions-for-channels artifacts from WSL2
#
# Reverses everything created by setup-wsl.sh plus any manual setup:
#   - Stops and removes the Docker container
#   - Removes the Docker image
#   - Unmounts the NAS share
#   - Removes CIFS credentials files
#   - Removes the sudoers entry
#   - Removes the ~/.bashrc auto-start block
#   - Optionally removes the deploy directory (including .env and data/)
#
# Does NOT uninstall Docker Engine or nvidia-container-toolkit
# (those are system-level; re-running setup-wsl.sh skips them if present).
#
# Usage:
#   bash teardown-wsl.sh
#   bash teardown-wsl.sh --all   # also removes deploy directory and persistent data
# ---------------------------------------------------------------------------

set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}▶ $*${NC}"; }
success() { echo -e "${GREEN}✔ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠ $*${NC}"; }
removed() { echo -e "${RED}✘ removed: $*${NC}"; }

if [[ $EUID -eq 0 ]]; then
    echo "Do not run as root. Run as your normal user." >&2; exit 1
fi
if ! grep -qi microsoft /proc/version 2>/dev/null; then
    echo "Run this inside WSL2 Ubuntu." >&2; exit 1
fi

REMOVE_DEPLOY=false
for arg in "$@"; do [[ "$arg" == "--all" ]] && REMOVE_DEPLOY=true; done

# ── Locate deploy directory ────────────────────────────────────────────────
# Check common locations: installer default, Windows Documents path
CANDIDATES=(
    "$HOME/py-captions-for-channels"
    "/mnt/c/Users/$USER/Documents/py-captions-for-channels"
    "/mnt/c/Users/$(whoami)/Documents/py-captions-for-channels"
)
DEPLOY_DIR=""
for c in "${CANDIDATES[@]}"; do
    if [[ -d "$c/.git" ]]; then
        DEPLOY_DIR="$c"
        break
    fi
done

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║     py-captions-for-channels — teardown (WSL2)                  ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

if [[ -n "$DEPLOY_DIR" ]]; then
    echo "  Deploy dir found : $DEPLOY_DIR"
else
    warn "Deploy directory not found in common locations."
    echo "  Checked: ${CANDIDATES[*]}"
    echo "  Enter path manually (or press Enter to skip deploy-dir steps):"
    read -r DEPLOY_DIR_INPUT
    DEPLOY_DIR="${DEPLOY_DIR_INPUT:-}"
fi

if [[ $REMOVE_DEPLOY == false && -n "$DEPLOY_DIR" ]]; then
    echo ""
    warn "The deploy directory ($DEPLOY_DIR) will be left in place."
    warn "Run with --all to also remove it and all persistent data (state, logs)."
fi

echo ""
echo "This will:"
echo "  • Stop and remove the py-captions-for-channels container"
echo "  • Remove the Docker image"
echo "  • Unmount /mnt/channels (and other /mnt/ NAS mounts used by this app)"
echo "  • Delete credentials files in /etc/cifs-credentials*"
echo "  • Delete /etc/sudoers.d/py-captions"
echo "  • Remove the auto-start block from ~/.bashrc"
[[ $REMOVE_DEPLOY == true ]] && echo "  • DELETE the deploy directory and all data (irreversible)"
echo ""
read -rp "Continue? [y/N] " CONFIRM
[[ "${CONFIRM,,}" != "y" ]] && echo "Aborted." && exit 0
echo ""

# ── 1. Stop and remove container ──────────────────────────────────────────
info "Stopping container..."
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q py-captions-for-channels; then
    docker stop py-captions-for-channels 2>/dev/null || true
    docker rm   py-captions-for-channels 2>/dev/null || true
    removed "container: py-captions-for-channels"
else
    success "No running container found"
fi

# Also run compose down from deploy dir to catch any compose-managed containers
if [[ -n "$DEPLOY_DIR" && -f "$DEPLOY_DIR/docker-compose.yml" ]]; then
    (cd "$DEPLOY_DIR" && docker compose down --remove-orphans 2>/dev/null) || true
fi

# ── 2. Remove image ────────────────────────────────────────────────────────
info "Removing Docker image..."
IMAGE="ghcr.io/jay3702/py-captions-for-channels:latest"
if docker image inspect "$IMAGE" &>/dev/null 2>&1; then
    docker rmi "$IMAGE"
    removed "image: $IMAGE"
else
    success "Image not present"
fi

# ── 3. Unmount NAS ────────────────────────────────────────────────────────
info "Unmounting NAS shares..."
# Find all CIFS mounts that look like they were set up for this app
CIFS_MOUNTS=$(grep -E '\scifs\s' /proc/mounts | awk '{print $2}' || true)
if [[ -n "$CIFS_MOUNTS" ]]; then
    while IFS= read -r mp; do
        sudo umount "$mp" 2>/dev/null && removed "unmounted: $mp" || warn "Could not unmount $mp (may already be unmounted)"
    done <<< "$CIFS_MOUNTS"
else
    success "No CIFS mounts found"
fi

# ── 4. Remove credentials files ───────────────────────────────────────────
info "Removing credentials files..."
for f in /etc/cifs-credentials /etc/cifs-credentials-py-captions; do
    if [[ -f "$f" ]]; then
        sudo rm -f "$f"
        removed "$f"
    fi
done
success "Credentials files removed (or were not present)"

# ── 5. Remove sudoers entry ───────────────────────────────────────────────
info "Removing sudoers entry..."
SUDOERS_FILE="/etc/sudoers.d/py-captions"
if [[ -f "$SUDOERS_FILE" ]]; then
    sudo rm -f "$SUDOERS_FILE"
    removed "$SUDOERS_FILE"
else
    success "Sudoers file not present"
fi

# ── 6. Remove ~/.bashrc auto-start block ──────────────────────────────────
info "Removing auto-start block from ~/.bashrc..."
MARKER="# ── py-captions auto-start"
END_MARKER="# ──────────────────────────────────────────────────────────────────────────"

if grep -q "$MARKER" ~/.bashrc 2>/dev/null; then
    # Remove from the marker line through the closing dashes line
    # Use Python for reliable multi-line deletion (avoids sed portability issues)
    python3 - <<'PYEOF'
import re, pathlib
bashrc = pathlib.Path.home() / '.bashrc'
text = bashrc.read_text()
# Remove the block from the marker to the closing dash line (inclusive)
cleaned = re.sub(
    r'\n# ── py-captions auto-start.*?# ───+\n',
    '\n',
    text,
    flags=re.DOTALL
)
bashrc.write_text(cleaned)
PYEOF
    removed "auto-start block from ~/.bashrc"
else
    success "No auto-start block found in ~/.bashrc"
fi

# ── 7. Remove deploy directory (only with --all) ──────────────────────────
if [[ $REMOVE_DEPLOY == true ]]; then
    if [[ -n "$DEPLOY_DIR" && -d "$DEPLOY_DIR" ]]; then
        info "Removing deploy directory..."
        rm -rf "$DEPLOY_DIR"
        removed "$DEPLOY_DIR"
    else
        success "Deploy directory not found (nothing to remove)"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════"
success "Teardown complete."
echo ""
echo "  Docker Engine and nvidia-container-toolkit are still installed."
echo "  Run setup-wsl.sh to reinstall from scratch."
if [[ $REMOVE_DEPLOY == false && -n "$DEPLOY_DIR" ]]; then
    echo ""
    echo "  Deploy directory preserved: $DEPLOY_DIR"
    echo "  To also remove it: bash teardown-wsl.sh --all"
fi
echo "════════════════════════════════════════════════════════════════════"
