# py-captions-for-channels

Automatic closed-caption generation for [Channels DVR](https://getchannels.com/) recordings using [Faster Whisper](https://github.com/SYSTRAN/faster-whisper).

Monitors your DVR for completed recordings, transcribes them with Faster Whisper on your NVIDIA GPU, and writes SRT caption files that Channels clients pick up automatically — no manual steps required.

<!-- Screenshot placeholder: web UI dashboard -->

## Features

- **Fully Automatic** — Detects completed recordings via polling or ChannelWatch webhooks and queues them for captioning
- **GPU-Accelerated** — NVIDIA CUDA + NVENC/NVDEC for fast transcription and encoding (7x faster than CPU)
- **Web Dashboard** — Real-time status, execution history, settings, system/GPU monitoring, and manual reprocessing
- **Smart Optimization** — Automatically tunes Whisper and ffmpeg parameters based on source type (OTA vs streaming)
- **Show Whitelist** — Process only the shows you care about; interactive toggle from the web UI
- **Fire TV / Android Support** — Optional MP4 transcoding with an embedded captions track for clients that don't support sidecar SRT files
- **Idempotent** — Tracks processed recordings in a database to avoid duplicates
- **Quarantine System** — Cleans up orphaned `.srt` and `.orig` files after source media is deleted, conserving storage space
- **Dry-Run Mode** — Test the full pipeline without modifying any files
- **Docker Ready** — Single `docker-compose up` with NVIDIA GPU passthrough

## How It Works

```
Channels DVR ──recording complete──▶ py-captions-for-channels
                                        │
                                        ├─ Fetch recording metadata (DVR API)
                                        ├─ Whisper AI transcription (GPU)
                                        ├─ Write .srt caption file
                                        └─ (optional) Transcode to .mp4 with embedded captions track
```

Channels DVR clients (Apple TV, Roku, Fire TV, web) automatically detect `.srt` files placed alongside recordings.

## Requirements

- **Channels DVR** server (with recordings accessible via network/mount)
- **NVIDIA GPU** with 6GB+ VRAM (GTX 1660 Super / RTX 2060 or better)
- **Docker** with NVIDIA Container Toolkit (`nvidia-container-toolkit`)
- **ChannelWatch** (optional, for webhook-based detection instead of polling)

> **CPU-only operation** is possible but significantly slower (~25 min per 1-hour recording vs 3-6 min with GPU).

| Hardware | 1-hr OTA Recording | 1-hr TVE (Streaming) | Daily Capacity |
|----------|-------------------|---------------------|----------------|
| CPU only | ~25 min | ~20 min | Very limited |
| RTX 2080 (11GB) | ~5-6 min | ~3-4 min | 20+ hours |
| RTX 3060/4060+ | ~4-5 min | ~2-3 min | 24+ hours |

> **Note:** OTA (over-the-air) recordings require MPEG2→H.264 transcoding, which adds time. TVE (streaming) recordings are already H.264 and only need captioning.

See [docs/SYSTEM_REQUIREMENTS.md](docs/SYSTEM_REQUIREMENTS.md) for detailed benchmarks and hardware guidance.

## Quick Start

```bash
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

# Configure
cp .env.example .env
nano .env   # Set CHANNELS_DVR_URL, DVR_RECORDINGS_PATH, etc.

# Deploy
docker-compose up -d

# Open the web dashboard
# http://your-server:8000
```

The container builds FFmpeg with NVENC/NVDEC support, installs Faster Whisper with CUDA, and starts the watcher + web UI automatically.

### ChannelWatch Integration (Optional)

For instant detection instead of polling:

1. Open ChannelWatch: `http://YOUR_CHANNELWATCH_IP:8501`
2. Go to **Settings → Notification Providers**
3. Enable **Custom URL** and set: `json://YOUR_HOST_IP:9000`
4. Set `DISCOVERY_MODE=webhook` in your `.env`

## Configuration

All settings are in `.env` (see [.env.example](.env.example) for the full reference):

```bash
# Required
CHANNELS_DVR_URL=http://your-channels-server:8089
DVR_RECORDINGS_PATH=/path/to/Channels/recordings

# Recording detection
DISCOVERY_MODE=polling          # "polling" (default) or "webhook"

# Caption processing
WHISPER_MODE=automatic          # Optimizes per source type (OTA vs streaming)
TRANSCODE_FOR_FIRETV=false      # Set true for Fire TV / Android clients
KEEP_ORIGINAL=true              # Archive original .mpg after transcoding

# Whitelist (only process listed shows)
# Edit whitelist.txt or toggle shows in the web UI

# Safety
DRY_RUN=false                   # Set true to test without modifying files
```

### Faster Whisper Model Selection

| Model | VRAM Required | Quality | Speed | Notes |
|-------|-------------|---------|-------|-------|
| `tiny` / `tiny.en` | ~1 GB | Basic | Fastest | Testing only |
| `base` / `base.en` | ~1 GB | Good | Very fast | Light workloads |
| `small` / `small.en` | ~2 GB | **Recommended** | Fast | Best speed/quality balance |
| `medium` / `medium.en` | ~5 GB | Very good | Moderate | Higher accuracy |
| `large-v3` | ~10 GB | Best | Slowest | Multilingual, highest accuracy |

> `.en` models are English-only and faster/more accurate for English content. Use the non-`.en` variant for multilingual recordings.

## Documentation

| Document | Description |
|----------|-------------|
| [SETUP.md](SETUP.md) | Quick setup walkthrough |
| [SETUP_ADVANCED.md](SETUP_ADVANCED.md) | GPU, custom caption commands, whitelist regex |
| [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) | Full Docker deployment guide |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Prerequisites and requirements |
| [.env.example](.env.example) | All configuration options with descriptions |
| [docs/SYSTEM_REQUIREMENTS.md](docs/SYSTEM_REQUIREMENTS.md) | Hardware benchmarks and sizing |
| [docs/AUTOMATIC_WHISPER_OPTIMIZATION.md](docs/AUTOMATIC_WHISPER_OPTIMIZATION.md) | Smart encoding optimization |
| [docs/LANGUAGE_SELECTION.md](docs/LANGUAGE_SELECTION.md) | Multi-language audio/subtitle processing |
| [docs/LOGGING.md](docs/LOGGING.md) | Log levels, job markers, verbosity |

## Development

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env

pytest                     # Run tests
python -m py_captions_for_channels   # Run watcher locally
```

## License

MIT — see [LICENSE](LICENSE).
