# py-captions-for-channels

Automatic closed-caption generation for [Channels DVR](https://getchannels.com/) recordings using [OpenAI Whisper](https://github.com/openai/whisper).

Monitors your DVR for completed recordings, transcribes them with Whisper AI on your NVIDIA GPU, and writes SRT caption files that Channels clients pick up automatically — no manual steps required.

<!-- Screenshot placeholder: web UI dashboard -->

## Features

- **Fully Automatic** — Detects completed recordings via polling or ChannelWatch webhooks and queues them for captioning
- **GPU-Accelerated** — NVIDIA CUDA + NVENC/NVDEC for fast transcription and encoding (7x faster than CPU)
- **Web Dashboard** — Real-time status, execution history, settings, system/GPU monitoring, and manual reprocessing
- **Smart Optimization** — Automatically tunes Whisper and ffmpeg parameters based on source type (OTA vs streaming)
- **Show Whitelist** — Process only the shows you care about; interactive toggle from the web UI
- **Fire TV / Android Support** — Optional MP4 transcoding with burned-in captions for clients that don't support SRT
- **Idempotent** — Tracks processed recordings in a database to avoid duplicates
- **Quarantine System** — Isolates problem files instead of retrying endlessly
- **Dry-Run Mode** — Test the full pipeline without modifying any files
- **Docker Ready** — Single `docker-compose up` with NVIDIA GPU passthrough

## How It Works

```
Channels DVR ──recording complete──▶ py-captions-for-channels
                                        │
                                        ├─ Fetch recording metadata (DVR API)
                                        ├─ Whisper AI transcription (GPU)
                                        ├─ Write .srt caption file
                                        └─ (optional) Transcode to .mp4 with burned-in captions
```

Channels DVR clients (Apple TV, Roku, Fire TV, web) automatically detect `.srt` files placed alongside recordings.

## Requirements

- **Channels DVR** server (with recordings accessible via network/mount)
- **NVIDIA GPU** with 6GB+ VRAM (GTX 1660 Super / RTX 2060 or better)
- **Docker** with NVIDIA Container Toolkit (`nvidia-container-toolkit`)
- **ChannelWatch** (optional, for webhook-based detection instead of polling)

> **CPU-only operation** is possible but impractical for real-time use (~3-5x real-time vs 0.3-0.6x with GPU).

| Hardware | 30-min Recording | Daily Capacity |
|----------|-----------------|----------------|
| GTX 1660 Super (6GB) | ~15-18 min | 4-6 hours |
| RTX 2060/2080 (8GB+) | ~8-12 min | 12-16+ hours |
| RTX 3060/4060+ | ~6-9 min | 20+ hours |

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

The container builds FFmpeg with NVENC/NVDEC support, installs Whisper with CUDA, and starts the watcher + web UI automatically.

### ChannelWatch Integration (Optional)

For instant detection instead of polling:

1. Open ChannelWatch: `http://YOUR_DVR_IP:8501`
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

### Whisper Model Selection

| Model | VRAM Required | Quality | Speed |
|-------|-------------|---------|-------|
| `base` | 4GB | Good | Fastest |
| `medium` | 6GB | **Recommended** | Balanced |
| `large` | 8GB | Best | Slowest |

## Documentation

| Document | Description |
|----------|-------------|
| [SETUP.md](SETUP.md) | Quick setup walkthrough |
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


- Completions (inline): provides AI code suggestions directly in the editor as you type. Ensure `GitHub Copilot` (Completions) is installed and signed in; accept suggestions with `Tab` or the UI accept control.
- Chat (conversational): `GitHub Copilot Chat` is a separate pane for asking questions, requesting explanations, or referencing open files. Install the Chat extension if you want the chat UI.
- Setup steps:
  1. Extensions ? Manage Extensions ? confirm `GitHub Copilot` (Completions) is installed; install `GitHub Copilot Chat` if desired.
  2. Restart Visual Studio if prompted.
  3. Sign in: Extensions ? GitHub Copilot ? Sign in (use the GitHub account with Copilot access).
  4. Open a code file and type to see inline suggestions; open `View ? Other Windows ? GitHub Copilot Chat` for chat.
- Tips:
  - Pushing the repository to GitHub improves suggestion quality because Copilot can use repository context.
  - Both Completions and Chat can be active simultaneously; Chat can reference editor/workspace context when enabled.
