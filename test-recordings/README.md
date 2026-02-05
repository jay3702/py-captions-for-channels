# Test Recordings Directory

This directory is for local development and testing without requiring access to the network DVR repository.

## Setup

1. Copy sample recordings from the Channels DVR server to this directory:
   ```bash
   # Example: Copy a few CNN News Central recordings
   scp user@server:/tank/AllMedia/Channels/TV/CNN\ News\ Central/CNN\ News\ Central\ 2026-02-04-*.mpg \
       ./TV/CNN\ News\ Central/
   ```

2. Update `.env` to use local testing:
   ```dotenv
   LOCAL_TEST_DIR=./test-recordings
   USE_POLLING=true
   USE_WEBHOOK=false
   ```

3. Start dev environment:
   ```bash
   docker-compose -f docker-compose.dev.yml up -d
   ```

## Directory Structure

Maintain the same structure as the DVR server:
```
test-recordings/
├── TV/
│   ├── CNN News Central/
│   │   ├── CNN News Central 2026-02-04-1100.mpg
│   │   └── CNN News Central 2026-02-04-1200.mpg
│   ├── Amanpour/
│   └── ...
└── Movies/
    └── ...
```

## Workflow

1. **Copy samples**: Get a few representative recordings (1-2 hours each)
2. **Test changes**: Modify code and test with local files (no network latency)
3. **Move files**: Move recordings in/out of directory to simulate new completions
4. **Deploy**: Once tested locally, deploy to niu for network testing
