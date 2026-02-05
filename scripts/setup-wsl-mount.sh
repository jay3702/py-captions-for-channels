#!/bin/bash
#
# Setup persistent CIFS mount in WSL for Channels DVR recordings
#
# This script configures /etc/fstab to automatically mount the CIFS share
# on WSL startup, ensuring Docker containers always have access to recordings.
#

set -e

MOUNT_POINT="/mnt/niu-recordings"
SHARE_PATH="//192.168.3.150/channels"
CREDENTIALS_FILE="/home/jay/.smbcredentials"

echo "=========================================="
echo "WSL CIFS Mount Setup"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

# Create mount point if it doesn't exist
if [ ! -d "$MOUNT_POINT" ]; then
    echo "Creating mount point: $MOUNT_POINT"
    mkdir -p "$MOUNT_POINT"
else
    echo "Mount point already exists: $MOUNT_POINT"
fi

# Verify credentials file exists
if [ ! -f "$CREDENTIALS_FILE" ]; then
    echo "ERROR: Credentials file not found: $CREDENTIALS_FILE"
    echo ""
    echo "Please create it with:"
    echo "  cat > $CREDENTIALS_FILE << 'EOF'"
    echo "  username=jay"
    echo "  password=Applep1e!"
    echo "  EOF"
    echo "  chmod 600 $CREDENTIALS_FILE"
    exit 1
fi

# Secure credentials file
echo "Securing credentials file..."
chmod 600 "$CREDENTIALS_FILE"
chown root:root "$CREDENTIALS_FILE"

# Check if mount is already in fstab
if grep -q "$SHARE_PATH" /etc/fstab; then
    echo "WARNING: Mount entry already exists in /etc/fstab"
    echo "Current entry:"
    grep "$SHARE_PATH" /etc/fstab
    echo ""
    read -p "Do you want to replace it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Backup fstab
        cp /etc/fstab /etc/fstab.backup.$(date +%Y%m%d_%H%M%S)
        # Remove old entry
        sed -i "\|$SHARE_PATH|d" /etc/fstab
        echo "Old entry removed"
    else
        echo "Skipping fstab update"
        exit 0
    fi
fi

# Add to fstab
echo "Adding mount to /etc/fstab..."
cat >> /etc/fstab << EOF

# Channels DVR recordings CIFS mount
$SHARE_PATH $MOUNT_POINT cifs credentials=$CREDENTIALS_FILE,uid=0,gid=0,file_mode=0777,dir_mode=0777,vers=3.0,noperm,_netdev,x-systemd.automount,x-systemd.requires=network-online.target 0 0
EOF

echo "✓ fstab entry added"

# Unmount if already mounted
if mountpoint -q "$MOUNT_POINT"; then
    echo "Unmounting existing mount..."
    umount "$MOUNT_POINT" || true
fi

# Mount using fstab entry
echo "Mounting share..."
mount "$MOUNT_POINT"

# Verify mount
if mountpoint -q "$MOUNT_POINT"; then
    echo "✓ Mount successful!"
    echo ""
    echo "Testing access..."
    ls -la "$MOUNT_POINT/TV" | head -5
    echo ""
    echo "=========================================="
    echo "Setup complete!"
    echo "=========================================="
    echo ""
    echo "The CIFS share will now automatically mount when WSL starts."
    echo "Docker containers can now reliably access: /mnt/niu-recordings"
    echo ""
else
    echo "ERROR: Mount failed!"
    echo "Check the mount manually with: mount $MOUNT_POINT"
    exit 1
fi
