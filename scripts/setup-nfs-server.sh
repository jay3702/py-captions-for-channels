#!/bin/bash
#
# Setup NFS server on NIU (Debian) for Channels DVR recordings
#
# Run this ON THE NIU SERVER as root or with sudo
#

set -e

EXPORT_PATH="/tank/AllMedia/Channels"
ALLOWED_NETWORK="192.168.0.0/16"  # Allows all 192.168.x.x for VPN compatibility

echo "=========================================="
echo "NFS Server Setup for Channels DVR"
echo "=========================================="
echo ""
echo "This will set up NFS exports for: $EXPORT_PATH"
echo "Allowing access from: $ALLOWED_NETWORK"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

# Install NFS server
echo "Installing NFS server packages..."
apt-get update
apt-get install -y nfs-kernel-server

# Backup existing exports file
if [ -f /etc/exports ]; then
    cp /etc/exports /etc/exports.backup.$(date +%Y%m%d_%H%M%S)
    echo "✓ Backed up existing /etc/exports"
fi

# Check if export already exists
if grep -q "$EXPORT_PATH" /etc/exports 2>/dev/null; then
    echo ""
    echo "WARNING: Export for $EXPORT_PATH already exists in /etc/exports"
    echo "Current entry:"
    grep "$EXPORT_PATH" /etc/exports
    echo ""
    read -p "Do you want to replace it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Remove old entry
        sed -i "\|$EXPORT_PATH|d" /etc/exports
        echo "Old entry removed"
    else
        echo "Keeping existing entry"
        exit 0
    fi
fi

# Add NFS export
# Options explained:
#   rw: read-write access
#   sync: write changes to disk before responding (safer, slightly slower)
#   no_subtree_check: improves reliability
#   no_root_squash: allow root from client to be root (needed for Docker)
#   insecure: allow connections from ports >1024 (needed for WSL)
#   crossmnt: allow mounting of subdirectories
echo ""
echo "Adding NFS export to /etc/exports..."
cat >> /etc/exports << EOF

# Channels DVR recordings - NFS export
$EXPORT_PATH $ALLOWED_NETWORK(rw,sync,no_subtree_check,no_root_squash,insecure,crossmnt)
EOF

echo "✓ Export added to /etc/exports"

# Export the filesystem
echo ""
echo "Exporting filesystems..."
exportfs -ra

# Restart NFS server
echo "Restarting NFS server..."
systemctl restart nfs-kernel-server
systemctl enable nfs-kernel-server

# Show active exports
echo ""
echo "✓ NFS server configured!"
echo ""
echo "Active NFS exports:"
exportfs -v

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "You can now mount this from WSL with:"
echo "  sudo mount -t nfs 192.168.3.150:$EXPORT_PATH /mnt/niu-recordings"
echo ""
echo "To verify from another machine:"
echo "  showmount -e 192.168.3.150"
echo ""
