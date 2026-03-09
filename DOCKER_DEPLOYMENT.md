# Docker Deployment Guide

## Quick Start

A prebuilt image is published automatically on every push to `main`:

```
ghcr.io/jay3702/py-captions-for-channels:latest
```

No local build is required. The `docker-compose.yml` in the repo pulls this image automatically.

```bash
# Clone the repository
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

# Create your .env from the example
cp .env.example .env
# Edit .env — minimum required: set CHANNELS_DVR_URL (see Configuration below)

# Pull the prebuilt image and start
docker compose pull
docker compose up -d

# View logs
docker compose logs -f

# Web dashboard: http://YOUR_HOST_IP:8000
```

### Building locally (optional)

If you need to build from source (e.g. to test local changes):

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
```

## Configuration

All configuration is done via the `.env` file — **do not edit `docker-compose.yml` directly.**
`docker-compose.yml` reads every setting from `.env` via `${VAR:-default}` substitution.

### Minimum settings — CPU-only host

```bash
CHANNELS_DVR_URL=http://YOUR_DVR_IP:8089
DRY_RUN=true   # set to false once verified
```

### Minimum settings — GPU host (NVIDIA)

Add to the CPU settings above:

```bash
DOCKER_RUNTIME=nvidia
NVIDIA_VISIBLE_DEVICES=all
```

> **Driver requirement:** the host NVIDIA driver must be **≥ 520** (supports CUDA 12.2).
> Check with `nvidia-smi` — "CUDA Version" must show 12.2 or higher.
> If it is lower, GPU acceleration silently falls back to CPU and a warning is logged at startup.

### Recordings path (DVR media mount)

Use the **Setup Wizard** in the web dashboard (⚙ gear icon → **Setup Wizard**) to configure
the Docker volume that exposes your DVR recordings inside the container. The wizard:
- Auto-detects the DVR media folder from the API
- Lets you choose same-host (bind mount) or remote (SMB/CIFS or NFS)
- Verifies the path is accessible from inside the container before writing settings

The relevant `.env` variables it sets:

| Variable | Description |
|----------|-------------|
| `DVR_MEDIA_TYPE` | Volume driver type: `none` (bind), `cifs`, or `nfs` |
| `DVR_MEDIA_DEVICE` | Host path or network share to mount |
| `DVR_MEDIA_OPTS` | Mount options passed to the Docker volume driver |
| `DVR_MEDIA_MOUNT` | Container path where recordings appear |
| `DVR_PATH_PREFIX` | DVR server's local path prefix (remote deployments only) |
| `LOCAL_PATH_PREFIX` | Equals `DVR_MEDIA_MOUNT`; managed automatically by the wizard |

See [.env.example](.env.example) for full documentation and examples for each deployment type.

### Key environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CHANNELS_DVR_URL` | *(required)* | Channels DVR server base URL |
| `DRY_RUN` | `true` | If true, log commands without executing them |
| `DOCKER_RUNTIME` | `runc` | Set to `nvidia` on GPU hosts |
| `NVIDIA_VISIBLE_DEVICES` | *(empty)* | Set to `all` on GPU hosts |
| `DISCOVERY_MODE` | `polling` | `polling` or `webhook` |
| `WEBHOOK_PORT` | `9000` | Webhook receiver port |
| `WEB_UI_PORT` | `8000` | Web dashboard port |
| `HOST_DATA_DIR` | `./data` | Host path for persistent data (state, logs) |
| `PIPELINE_TIMEOUT` | `7200` | Max seconds per caption job |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

For the full list see [.env.example](.env.example).

## ChannelWatch Configuration

Configure ChannelWatch to send webhooks to your container:

1. Open ChannelWatch web interface: `http://YOUR_DVR_IP:8501`
2. Go to **Settings ? Notification Providers**
3. Enable **Custom URL**
4. Set **Custom Apprise URL** to:
   ```
   json://YOUR_DOCKER_HOST_IP:9000
   ```
   - If running on the same machine as DVR: `http://<LOCAL_IP>:9000`
   - If running on a different machine: `json://YOUR_MACHINE_IP:9000`
5. Save settings
6. Enable notifications for "Recording Completed" events

## Deployment to Your Server

### Via SSH

```bash
ssh user@YOUR_SERVER

# Clone repository
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

# Create and edit .env
cp .env.example .env
nano .env   # set CHANNELS_DVR_URL at minimum

# Pull prebuilt image and start
docker compose pull
docker compose up -d

# Check logs
docker compose logs -f
```

Then open the web dashboard at `http://YOUR_SERVER_IP:8000` and use the **Setup Wizard** to
configure the recordings mount.

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
   docker exec -it py-captions curl http://<CHANNELS_DVR_SERVER>:8089/dvr/jobs
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
# Pull latest config/compose changes
git pull

# Pull the new prebuilt image and restart
docker compose pull
docker compose up -d
```

The container is replaced in-place; persistent data in `HOST_DATA_DIR` (default `./data`) is preserved.

## Uninstall

```bash
# Stop and remove container
docker compose down

# Remove data (optional)
rm -rf data/ logs/

# Remove image
docker rmi ghcr.io/jay3702/py-captions-for-channels:latest
```
