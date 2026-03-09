#!/bin/bash
set -e

# Start Glances web server in background
echo "Starting Glances web server on port 61208..."
glances -w --disable-plugin quicklook,ports,irq,folders,raid &
GLANCES_PID=$!
echo "Glances started with PID $GLANCES_PID"

# Wait a moment for Glances to start
sleep 2

# Start the main application
echo "Starting py-captions-for-channels..."
exec python -u -m py_captions_for_channels
