#!/bin/bash
#
# Verify WSL CIFS mount is working correctly
#

MOUNT_POINT="/mnt/niu-recordings"

echo "=========================================="
echo "WSL Mount Verification"
echo "=========================================="
echo ""

# Check if mount point exists
if [ ! -d "$MOUNT_POINT" ]; then
    echo "✗ Mount point does not exist: $MOUNT_POINT"
    exit 1
fi
echo "✓ Mount point exists: $MOUNT_POINT"

# Check if mounted
if ! mountpoint -q "$MOUNT_POINT"; then
    echo "✗ Not mounted: $MOUNT_POINT"
    echo ""
    echo "Try mounting with: sudo mount $MOUNT_POINT"
    exit 1
fi
echo "✓ Mounted: $MOUNT_POINT"

# Check mount details
echo ""
echo "Mount details:"
mount | grep "$MOUNT_POINT"

# Check if accessible
if [ ! -d "$MOUNT_POINT/TV" ]; then
    echo ""
    echo "✗ Cannot access TV directory"
    exit 1
fi
echo ""
echo "✓ TV directory accessible"

# Test read access
echo ""
echo "Sample recordings:"
ls -la "$MOUNT_POINT/TV" | head -10

# Test write access
TEST_FILE="$MOUNT_POINT/TV/test-write-$(date +%s).txt"
if touch "$TEST_FILE" 2>/dev/null; then
    echo ""
    echo "✓ Write access confirmed"
    rm "$TEST_FILE"
else
    echo ""
    echo "✗ Write access failed"
    exit 1
fi

# Check from Docker perspective
echo ""
echo "Docker container verification:"
if docker ps --filter "name=py-captions-local" --format "{{.Names}}" | grep -q "py-captions-local"; then
    echo "✓ Container is running"
    
    # Test container can see the mount
    if docker exec py-captions-local test -d /tank/AllMedia/Channels/TV; then
        echo "✓ Container can access mount"
        
        # Count files
        FILE_COUNT=$(docker exec py-captions-local ls -1 /tank/AllMedia/Channels/TV | wc -l)
        echo "✓ Container sees $FILE_COUNT directories"
    else
        echo "✗ Container cannot access mount"
        exit 1
    fi
else
    echo "⚠ Container not running (start with: docker compose up -d)"
fi

echo ""
echo "=========================================="
echo "All checks passed!"
echo "=========================================="
