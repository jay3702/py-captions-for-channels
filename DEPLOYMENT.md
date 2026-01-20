# Deployment Requirements

## Prerequisites

### 1. Docker & Docker Compose
- **Docker Engine**: v20.10+ with Docker Compose v2.0+
- **Platform**: Linux (recommended), macOS, or Windows with Docker Desktop
  - Linux preferred for production (better performance, native GPU support)
- **GPU Support** (optional but recommended):
  - NVIDIA GPU with CUDA compute capability 3.0+
  - NVIDIA Container Toolkit installed (`nvidia-container-toolkit`)
  - NVIDIA driver 450+ on host

**Installation**:
```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install nvidia-container-toolkit (if using GPU)
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### 2. Channels DVR + ChannelWatch
- **Channels DVR**: v8.0+ (running on local network)
- **ChannelWatch**: Docker image (`gofmt/channelwatch:latest`) or native installation
  - Acts as the event source (webhook notifications)
  - Sends webhook POSTs when recordings complete
  - Configuration: Point ChannelWatch webhook URL to `http://py-captions-host:9000/`

**Example docker-compose for ChannelWatch**:
```yaml
services:
  channelwatch:
    image: gofmt/channelwatch:latest
    container_name: channelwatch
    network_mode: host
    environment:
      - CHANNELS_URL=http://channels-dvr-ip:8089
      - NOTIFY_URL=http://py-captions-host:9000/  # Points to py-captions webhook
      - NOTIFY_TITLE_FORMAT=Recording Event
```

### 3. Linux-Based Server
- **OS**: Ubuntu 18.04 LTS+, Debian 10+, CentOS 7+, or equivalent
- **Storage**: 
  - Sufficient space for recording directory (mounted via Docker volume)
  - ~100MB for application data and logs
- **Network**:
  - Access to Channels DVR (local network)
  - Outbound HTTPS for OpenAI API (Whisper model download on first run, ~1.4GB for medium model)
- **Resources**:
  - **Minimum**: 4 CPU cores, 8GB RAM, no GPU (CPU captions ~6–10x realtime)
  - **Recommended**: 8 CPU cores, 16GB+ RAM, NVIDIA GPU (GPU captions 5–25x realtime)

---

## Installation

### Step 1: Clone Repository
```bash
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels
```

### Step 2: Configure Environment
Create `.env` file:
```env
# Channels DVR API
CHANNELS_API_URL=http://channels-dvr-ip:8089

# Webhook
USE_WEBHOOK=true
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=9000

# Processing
TRANSCODE_FOR_FIRETV=true       # Transcode to MP4 for Fire TV
KEEP_ORIGINAL=true              # Archive original .mpg files
CAPTION_COMMAND=bash -c 'whisper --model medium --output_format srt --output_dir "$(dirname "{path}")" "{path}"'

# State & data
STATE_FILE=/app/data/state.json
DRY_RUN=false

# Logging
LOG_VERBOSITY=NORMAL             # MINIMAL, NORMAL, or VERBOSE
LOG_FILE=/app/logs/app.log

# GPU (optional)
NVIDIA_VISIBLE_DEVICES=all       # Set to device ID if multiple GPUs
```

### Step 3: Mount Recording Directory
Edit `docker-compose.yml` to mount your recording volume:
```yaml
volumes:
  - /path/to/recordings:/tank/AllMedia/Channels:rw
  - ./data:/app/data
  - ./logs:/app/logs
```

### Step 4: Deploy
```bash
docker compose build
docker compose up -d
```

### Step 5: Configure ChannelWatch Webhook
Point ChannelWatch to send webhooks to:
```
http://py-captions-host:9000/
```

### Step 6: Verify
```bash
# Check logs
docker compose logs -f py-captions

# Test health check (after processing some recordings)
docker compose exec py-captions python scripts/health_check.py \
  --log-file /app/logs/app.log \
  --lookback-days 1
```

---

## System Requirements Summary

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 4 cores | 8+ cores |
| **RAM** | 8 GB | 16+ GB |
| **GPU** | None (CPU captions) | NVIDIA (5–25x speedup) |
| **Storage** | 200 MB (app) | 100 GB+ (logs, temp transcodes) |
| **Network** | Local LAN | 1 Gbps+ |
| **OS** | Ubuntu 18.04 LTS | Ubuntu 20.04 LTS+ |
| **Docker** | v20.10+ | v20.10+ with docker-compose v2+ |

---

## Network Topology

```
┌─────────────────────────────────────────────────────┐
│                    Linux Server                      │
│  ┌──────────────────────────────────────────────┐  │
│  │ Docker Compose                               │  │
│  │ ┌──────────────────┐  ┌──────────────────┐  │  │
│  │ │ ChannelWatch     │  │ py-captions      │  │  │
│  │ │ (Event Source)   │→→│ (Processing)     │  │  │
│  │ └──────────────────┘  └──────────────────┘  │  │
│  └──────────────────────────────────────────────┘  │
│           ↓              ↓           ↓             │
│    Channels DVR    Recordings    OpenAI API       │
│    (8089)          (NAS/Local)    (Whisper)       │
└─────────────────────────────────────────────────────┘
```

**Data Flow**:
1. Channels DVR records a show → Recording saved to mounted directory
2. ChannelWatch detects recording complete → POSTs webhook to `http://localhost:9000/`
3. py-captions receives webhook → Downloads Whisper model (first run) → Generates captions
4. Optional: Transcode to MP4 with GPU (if `TRANSCODE_FOR_FIRETV=true`)
5. Save `.srt` file alongside recording → Log completion to `/app/logs/app.log`

---

## Optional: GPU Setup (NVIDIA)

### Check GPU Support
```bash
# On host
nvidia-smi

# In container
docker compose exec py-captions nvidia-smi
```

### Enable GPU in docker-compose.yml
The image already includes GPU support. Just ensure:
```yaml
runtime: nvidia
environment:
  - NVIDIA_VISIBLE_DEVICES=all
```

### Performance Expectations
- **CPU (4 cores)**: ~6–10x realtime (1 hour video takes 6–10 minutes)
- **GPU (NVIDIA RTX 2080 Ti)**: ~15–25x realtime (1 hour video takes 2–4 minutes)

---

## Troubleshooting

### Docker Build Fails
```bash
# Check Docker daemon
docker ps

# Rebuild with no cache
docker compose build --no-cache

# Check logs
docker compose logs py-captions
```

### Webhook Not Triggering
```bash
# Verify ChannelWatch is sending POSTs
docker compose logs py-captions | grep "webhook"

# Test manually
curl -X POST http://localhost:9000/ \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","message":"Program: Test Show\nStatus: Completed"}'
```

### GPU Not Detected
```bash
# Verify nvidia-container-toolkit
docker run --rm --runtime=nvidia nvidia/cuda:11.8.0-base nvidia-smi

# Check docker-compose.yml has runtime: nvidia
```

### Logs Not Writing
```bash
# Check volume mount permissions
docker compose exec py-captions ls -la /app/logs/

# Ensure ./logs directory exists on host
mkdir -p ./logs
chmod 755 ./logs
```

---

## First-Run Checklist

- [ ] Docker + nvidia-container-toolkit installed
- [ ] Channels DVR running and accessible
- [ ] ChannelWatch Docker container or native installation running
- [ ] Recording directory mounted in docker-compose.yml
- [ ] `.env` file configured with correct IP addresses
- [ ] ChannelWatch webhook URL points to py-captions host:9000
- [ ] `docker compose up -d` completes successfully
- [ ] First recording processed (check `/app/logs/app.log` for `Caption pipeline completed`)
- [ ] `.srt` file present alongside recording (e.g., `show.mpg` + `show.srt`)

---

## Supported Platforms

| Platform | Docker | ChannelWatch | Status |
|----------|--------|--------------|--------|
| **Ubuntu 20.04 LTS** | ✅ | ✅ Docker | ✅ Tested & recommended |
| **Ubuntu 18.04 LTS** | ✅ | ✅ Docker | ✅ Supported |
| **Debian 10+** | ✅ | ✅ Docker | ✅ Supported |
| **QNAP NAS (Docker)** | ✅ | Via Docker | ✅ Production (RTX 2080 Ti) |
| **Synology NAS** | ✅ | ✅ Docker | ⚠️ Untested |
| **Docker Desktop (Mac)** | ✅ | ✅ Docker | ⚠️ GPU not available |
| **Docker Desktop (Windows)** | ✅ | ✅ Docker | ⚠️ GPU requires WSL2 + NVIDIA driver |

---

## Support & Issues

- **GitHub Issues**: [jay3702/py-captions-for-channels/issues](https://github.com/jay3702/py-captions-for-channels/issues)
- **Logs**: Check `/app/logs/app.log` or `docker compose logs py-captions`
- **Health Check**: Run `docker compose exec py-captions python scripts/health_check.py --lookback-days 1`

---

**Last Updated**: January 20, 2026  
**Version**: 0.7+
