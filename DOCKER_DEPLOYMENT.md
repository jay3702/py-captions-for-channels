# Docker Deployment Guide

## Quick Start

### 1. Build and Run with Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

# Create data directory
mkdir -p data logs

# Start the container
docker-compose up -d

# View logs
docker-compose logs -f
```

### 2. Build and Run with Docker

```bash
# Build the image
docker build -t py-captions-for-channels .

# Run the container
docker run -d \
  --name py-captions \
  --network host \
  -v $(pwd)/data:/app/data \
  -v /tank/AllMedia/Channels:/recordings:ro \
  -e USE_WEBHOOK=true \
  -e DRY_RUN=false \
  py-captions-for-channels
```

## Configuration

### Environment Variables

All configuration can be set via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_MOCK` | `false` | Use mock event source for testing |
| `USE_WEBHOOK` | `true` | Use webhook receiver (production) |
| `WEBHOOK_HOST` | `0.0.0.0` | Webhook server bind address |
| `WEBHOOK_PORT` | `9000` | Webhook server port |
| `CHANNELS_API_URL` | `http://192.168.3.150:8089` | Channels DVR API endpoint |
| `CAPTION_COMMAND` | `/usr/local/bin/whisper --model medium {path}` | Command to execute for captioning |
| `STATE_FILE` | `/app/data/state.json` | Path to state file |
| `DRY_RUN` | `true` | If true, only print commands without executing |

### Customize docker-compose.yml

Edit `docker-compose.yml` to match your setup:

```yaml
environment:
  # Set to false to actually run caption commands
  - DRY_RUN=false
  
  # Update DVR API URL if different
  - CHANNELS_API_URL=http://YOUR_DVR_IP:8089
  
  # Customize caption command
  - CAPTION_COMMAND=whisper --model base --language en {path}

volumes:
  # Update recording path to match your DVR storage
  - /your/dvr/recordings:/recordings:ro
```

## ChannelWatch Configuration

Configure ChannelWatch to send webhooks to your container:

1. Open ChannelWatch web interface: `http://YOUR_DVR_IP:8501`
2. Go to **Settings ? Notification Providers**
3. Enable **Custom URL**
4. Set **Custom Apprise URL** to:
   ```
   json://YOUR_DOCKER_HOST_IP:9000
   ```
   - If running on the same machine as DVR: `json://192.168.3.150:9000`
   - If running on a different machine: `json://YOUR_MACHINE_IP:9000`
5. Save settings
6. Enable notifications for "Recording Completed" events

## Deployment to niu

### Via SSH

```bash
# SSH to niu
ssh admin@192.168.3.150

# Install Docker if not already installed
# (Follow QNAP Container Station setup)

# Clone repository
cd /share/Container
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

# Edit docker-compose.yml to match your setup
vi docker-compose.yml

# Start container
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Configure ChannelWatch on niu

Update Custom Apprise URL to: `json://127.0.0.1:9000` (since running on same machine)

## Monitoring

### View Logs

```bash
# With docker-compose
docker-compose logs -f

# With docker
docker logs -f py-captions

# View last 100 lines
docker-compose logs --tail=100
```

### Check Container Status

```bash
# With docker-compose
docker-compose ps

# With docker
docker ps | grep py-captions
```

### Restart Container

```bash
# With docker-compose
docker-compose restart

# With docker
docker restart py-captions
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs for errors
docker-compose logs

# Verify configuration
docker-compose config
```

### Webhook Not Receiving Events

1. Check ChannelWatch configuration
2. Verify port 9000 is accessible:
   ```bash
   curl -X POST http://YOUR_HOST:9000 -H "Content-Type: application/json" -d '{"test":"data"}'
   ```
3. Check firewall rules
4. Verify `network_mode: host` in docker-compose.yml

### Cannot Access DVR API

1. Verify `CHANNELS_API_URL` is correct
2. Test from container:
   ```bash
   docker exec -it py-captions curl http://192.168.3.150:8089/dvr/jobs
   ```

### Recording Files Not Found

1. Verify volume mount paths in docker-compose.yml
2. Check file permissions
3. Ensure container has read access to recordings

## Advanced Configuration

### Custom Whisper Model

```yaml
environment:
  - CAPTION_COMMAND=whisper --model large-v2 --language en --output_dir /app/captions {path}
```

### Multiple Caption Formats

```yaml
environment:
  - CAPTION_COMMAND=whisper {path} --output_format srt,vtt --output_dir /recordings/captions
```

### Production Best Practices

1. **Disable Dry-Run**: Set `DRY_RUN=false`
2. **Use Persistent Volumes**: Ensure `./data` is backed up
3. **Monitor Logs**: Set up log rotation or monitoring
4. **Resource Limits**: Add to docker-compose.yml:
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '2'
         memory: 4G
   ```

## Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## Uninstall

```bash
# Stop and remove container
docker-compose down

# Remove data (optional)
rm -rf data/ logs/

# Remove image
docker rmi py-captions-for-channels
```
