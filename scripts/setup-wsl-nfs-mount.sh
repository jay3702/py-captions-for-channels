#!/bin/bash
#
# Setup persistent NFS mount in WSL for Channels DVR recordings
#
# This replaces the CIFS/Samba mount with NFS for better Docker compatibility
#

set -e

MOUNT_POINT="/mnt/niu-recordings"
NFS_SERVER="192.168.3.150"
NFS_PATH="/tank/AllMedia/Channels"

echo "=========================================="
echo "WSL NFS Mount Setup"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

# Install NFS client if not present
if ! dpkg -l | grep -q nfs-common; then
    echo "Installing NFS client..."
    apt-get update
    apt-get install -y nfs-common
else
    echo "✓ NFS client already installed"
fi

# Create mount point if it doesn't exist
if [ ! -d "$MOUNT_POINT" ]; then
    echo "Creating mount point: $MOUNT_POINT"
    mkdir -p "$MOUNT_POINT"
else
    echo "✓ Mount point exists: $MOUNT_POINT"
fi

# Unmount if currently mounted
if mountpoint -q "$MOUNT_POINT"; then
    echo "Unmounting existing mount..."
    umount "$MOUNT_POINT" || umount -l "$MOUNT_POINT" || true
fi

# Remove old CIFS/Samba entries from fstab
if grep -q "//.*channels" /etc/fstab 2>/dev/null; then
    echo "Removing old CIFS mount entries from fstab..."
    cp /etc/fstab /etc/fstab.backup.$(date +%Y%m%d_%H%M%S)
    sed -i '/\/\/.*channels/d' /etc/fstab
    echo "✓ Old CIFS entries removed"
fi

# Check if NFS mount is already in fstab
if grep -q "$NFS_SERVER:$NFS_PATH" /etc/fstab 2>/dev/null; then
    echo "WARNING: NFS mount entry already exists in /etc/fstab"
    echo "Current entry:"
    grep "$NFS_SERVER:$NFS_PATH" /etc/fstab
    echo ""
    read -p "Do you want to replace it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sed -i "\|$NFS_SERVER:$NFS_PATH|d" /etc/fstab
        echo "Old entry removed"
    else
        echo "Skipping fstab update"
        exit 0
    fi
fi

# Add NFS mount to fstab
# Options explained:
#   rw: read-write
#   hard: keep trying if server goes down
#   intr: allow interrupting hung operations
#   timeo=600: timeout in deciseconds (60 seconds)
#   retrans=2: number of retransmissions
#   _netdev: wait for network before mounting
#   x-systemd.automount: auto-mount on access
echo ""
echo "Adding NFS mount to /etc/fstab..."
cat >> /etc/fstab << EOF

# Channels DVR recordings NFS mount
$NFS_SERVER:$NFS_PATH $MOUNT_POINT nfs rw,hard,intr,timeo=600,retrans=2,_netdev,x-systemd.automount 0 0
EOF

echo "✓ fstab entry added"

# Test the mount
echo ""
echo "Testing NFS mount..."
if mount "$MOUNT_POINT"; then
    echo "✓ Mount successful!"
    
    # Verify we can see files
    echo ""
    echo "Verifying access..."
    if [ -d "$MOUNT_POINT/TV" ]; then
        DIR_COUNT=$(ls -1 "$MOUNT_POINT/TV" 2>/dev/null | wc -l)
        echo "✓ Found $DIR_COUNT directories in TV/"
        
        # Show sample
        echo ""
        echo "Sample directories:"
        ls -la "$MOUNT_POINT/TV" | head -10
        
        # Test write
        TEST_FILE="$MOUNT_POINT/TV/nfs-test-$(date +%s).txt"
        if touch "$TEST_FILE" 2>/dev/null; then
            echo ""
            echo "✓ Write access confirmed"
            rm "$TEST_FILE"
        else
            echo ""
            echo "⚠ WARNING: Cannot write to mount"
        fi
    else
        echo "⚠ WARNING: TV directory not found"
    fi
else
    echo "✗ Mount failed!"
    echo ""
    echo "Troubleshooting:"
    echo "1. Verify NFS server is running on $NFS_SERVER:"
    echo "   showmount -e $NFS_SERVER"
    echo ""
    echo "2. Check firewall allows NFS (port 2049)"
    echo ""
    echo "3. Verify export path on server:"
    echo "   exportfs -v"
    exit 1
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "NFS mount is now persistent and will auto-mount on WSL startup."
echo "Docker containers will have reliable access to recordings."
echo ""
echo "To verify from another machine:"
echo "  showmount -e $NFS_SERVER"
echo ""
