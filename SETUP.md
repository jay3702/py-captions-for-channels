# Quick Setup Guide

## Initial Configuration

### 1. Copy and customize the environment file

```bash
# Copy the example file
cp .env.example .env

# Edit with your settings
nano .env  # or vi, vim, etc.
```

### 2. Update these key settings in .env:

```bash
# Your Channels DVR IP address
CHANNELS_API_URL=http://YOUR_DVR_IP:8089

# Path to your DVR recordings on the HOST machine
DVR_RECORDINGS_PATH=/path/to/your/recordings

# Your caption command (examples below)
CAPTION_COMMAND=/usr/local/bin/whisper --model medium {path}

# Set to false when ready for production
DRY_RUN=true
```

### 3. Deploy

```bash
# Create data directories
mkdir -p data logs

# Start the container
docker-compose up -d

# Watch logs
docker-compose logs -f
```

---

## Example Configurations

### For niu deployment (same machine as DVR):

```bash
# .env file
CHANNELS_API_URL=http://localhost:8089
DVR_RECORDINGS_PATH=/tank/AllMedia/Channels
CAPTION_COMMAND=/usr/local/bin/whisper --model medium {path}
DRY_RUN=false
```

### For remote deployment (different machine):

```bash
# .env file
CHANNELS_API_URL=http://192.168.1.100:8089  # DVR IP
DVR_RECORDINGS_PATH=/mnt/dvr-recordings     # Mounted network share
CAPTION_COMMAND=whisper --model base {path}
DRY_RUN=false
```

### For testing (no actual processing):

```bash
# .env file
CHANNELS_API_URL=http://localhost:8089
USE_MOCK=true          # Generate fake events
DRY_RUN=true           # Don't execute commands
CAPTION_COMMAND=echo "Would process: {path}"
```

---

## ChannelWatch Configuration

After starting the container, configure ChannelWatch:

1. Open ChannelWatch: `http://YOUR_DVR_IP:8501`
2. Go to **Settings ? Notification Providers**
3. Enable **Custom URL**
4. Set **Custom Apprise URL**:
   - Same machine: `json://localhost:9000`
   - Remote machine: `json://YOUR_DOCKER_HOST_IP:9000`
5. Save settings

---

## Verify Setup

```bash
# Check if container is running
docker-compose ps

# View logs
docker-compose logs -f

# Test webhook manually
curl -X POST http://localhost:9000 \
  -H "Content-Type: application/json" \
  -d '{
    "version": "1.0",
    "title": "Channels DVR - Recording Event",
    "message": "Test Event\nStatus: ?? Stopped\nProgram: Test Show"
  }'
```

---

## Troubleshooting

### Configuration not taking effect?

```bash
# Restart container to pick up .env changes
docker-compose down
docker-compose up -d
```

### Can't find recordings?

Check volume mount path:
```bash
# In .env, make sure DVR_RECORDINGS_PATH matches your system
# Example: DVR_RECORDINGS_PATH=/tank/AllMedia/Channels

# Verify inside container
docker exec -it py-captions-for-channels ls -la /recordings
```

### Not receiving webhooks?

```bash
# Check logs for connection attempts
docker-compose logs -f | grep webhook

# Verify port is accessible
netstat -tuln | grep 9000

# Test from DVR machine
curl http://YOUR_DOCKER_HOST:9000
```

---

## Next Steps

1. ? Configure environment variables in `.env`
2. ? Start container with `docker-compose up -d`
3. ? Configure ChannelWatch webhook URL
4. ? Test with a short recording
5. ? Check logs for successful processing
6. ? Set `DRY_RUN=false` when ready
7. ? Monitor and adjust as needed

See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for complete documentation.
