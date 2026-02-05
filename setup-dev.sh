#!/bin/bash
# Quick setup for local testing environment

echo "Setting up local development environment..."

# Create .env.dev if it doesn't exist
if [ ! -f .env.dev ]; then
    cat > .env.dev << 'EOF'
# Local Development Configuration
CHANNELS_API_URL=http://192.168.3.150:8089
USE_POLLING=true
USE_WEBHOOK=false
DRY_RUN=false
LOCAL_TEST_DIR=/recordings
POLL_INTERVAL_SECONDS=120
POLL_MAX_AGE_HOURS=2
LOG_VERBOSITY=VERBOSE
EOF
    echo "Created .env.dev file"
else
    echo ".env.dev already exists"
fi

# Create test directory structure
mkdir -p test-recordings/TV/{CNN\ News\ Central,Amanpour}
mkdir -p test-recordings/Movies

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Copy sample recordings:"
echo "   scp user@server:/path/to/recording.mpg test-recordings/TV/CNN\\ News\\ Central/"
echo ""
echo "2. Start dev environment:"
echo "   docker-compose -f docker-compose.dev.yml up -d"
echo ""
echo "3. View logs:"
echo "   docker logs -f py-captions-dev"
