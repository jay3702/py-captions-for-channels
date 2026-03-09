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
- **NVIDIA driver ≥ 520** on the Docker host (supports CUDA 12.2, which the container requires). Check with `nvidia-smi` — the "CUDA Version" shown must be **12.2 or higher**. If it's lower, GPU acceleration will silently fall back to CPU; the container logs a warning at startup identifying the mismatch.
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

# Deploy (pulls pre-built image from GitHub Container Registry)
docker compose up -d

# Open the web dashboard
# http://your-server:8000
```

The pre-built image includes FFmpeg with NVENC/NVDEC support, Faster Whisper with CUDA, and starts the watcher + web UI automatically. No local compilation required.

> **Building locally:** If you prefer to build the image yourself (e.g., for development), use the build override:
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
> ```

### GPU Acceleration (Optional)

`docker compose up -d` works on any machine. To enable NVIDIA GPU acceleration,
add two lines to your `.env`:

```dotenv
DOCKER_RUNTIME=nvidia
NVIDIA_VISIBLE_DEVICES=all
```

Requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
Without it, everything works the same on CPU — just slower (~6-10 min per hour of recording vs 2-4 min with GPU).

### ChannelWatch Integration (Optional)

For instant detection instead of polling:

1. Open ChannelWatch: `http://YOUR_CHANNELWATCH_IP:8501`
2. Go to **Settings → Notification Providers**
3. Enable **Custom URL** and set: `json://YOUR_HOST_IP:9000`
4. Set `DISCOVERY_MODE=webhook` in your `.env`

## Configuration

All settings are in `.env` (see [.env.example](.env.example) for the full reference):

```bash
# Required — DVR server URL
CHANNELS_DVR_URL=http://your-channels-server:8089

# Recordings path — use the Setup Wizard (web dashboard → ⚙ gear icon)
# It auto-detects and configures the Docker volume for your setup.

# Recording detection
DISCOVERY_MODE=polling          # "polling" (default) or "webhook"

# Caption processing
WHISPER_MODE=automatic          # Optimizes per source type (OTA vs streaming)
TRANSCODE_FOR_FIRETV=false      # Set true for Fire TV / Android clients
KEEP_ORIGINAL=true              # Archive original .mpg after transcoding

# Whitelist (only process listed shows)
# Manage from the web UI: Settings → Whitelist, or Recordings (per-show toggle)

# Safety
DRY_RUN=true                    # Switch to false once setup is verified
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
| [SETUP_ADVANCED.md](SETUP_ADVANCED.md) | GPU, Fire TV transcoding, webhooks, whitelist regex |
| [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) | Full Docker deployment guide |
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

## Development Story

This project started as a Linux shell script built with ChatGPT. It worked, but had serious architectural, performance, and reliability limitations — mostly caused by parsing the Channels DVR log file as the recording discovery mechanism. To solve those problems, the project was rewritten in Python using VS Code with GitHub Copilot. That shift led to discovering that ChannelWatch could provide clean "recording complete" notifications (though only the title, not the full path), and that the Channels DVR API could supply both the file path and recording status. Polling the API directly turned out to be simpler and more reliable than either log parsing or webhooks.

From that rewrite forward, the entire project was built through AI-assisted pair programming — a continuous conversation between a developer and GitHub Copilot (powered by Claude). Every feature — GPU acceleration, the web dashboard, quarantine system, 344-test suite, Docker deployment — was designed, implemented, debugged, and documented within that workflow. The AI wrote the code; the developer provided domain knowledge, tested on real hardware (i7-7700K + RTX 2080), and steered decisions. Even this README was written that way.

Occasionally a particular problem would get bogged down, and a side conversation with ChatGPT would help break through it. If that yielded a useful solution, ChatGPT would prepare instructions for Copilot, which were then transferred back into the Copilot conversation. This worked well and helped reduce the "premium requests" generated by Copilot.

## Known Limitations

- **Playback interruption during transcoding** — When `TRANSCODE_FOR_FIRETV` is enabled, the processed `.mpg` file replaces the original while keeping a `.cc4chan.orig` backup. If a recording is actively being watched when the replacement happens, the Channels client may freeze. The workaround is to return to the recordings menu and resume playback — it will recover immediately. There is no way to avoid this; the file replacement is already atomic (`os.rename`), but the client detects the change underneath it.

## License

MIT — see [LICENSE](LICENSE).
