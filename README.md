# py-captions-for-channels

Automatic caption generation for Channels DVR recordings using Whisper AI.

## Features

? **Automatic Processing** - Monitors ChannelWatch for completed recordings  
? **Flexible Configuration** - Environment variables or .env file  
? **Docker Ready** - Easy deployment with docker-compose  
? **Idempotent** - Tracks processed recordings to avoid duplicates  
? **Robust** - Webhook receiver with automatic reconnection  
? **Dry-Run Mode** - Test before executing actual commands  

## System Requirements

**GPU-accelerated processing is strongly recommended** for practical real-time caption generation. CPU-only operation is significantly slower (3-5x real-time) and not suitable for typical DVR usage.

### Minimum Viable Configuration
- **GPU**: NVIDIA GTX 1660 Super or RTX 2060 (6GB+ VRAM)
- **CPU**: 4+ cores (Intel i5-8400, AMD Ryzen 5 2600, or equivalent)
- **RAM**: 8GB minimum, 16GB recommended
- **Storage**: 10GB free space for temp files
- **Performance**: Processes 30-min recording in ~15-18 minutes (0.5-0.6x real-time)
- **Capacity**: Can handle 4-6 hours of recordings per day

### Recommended Configuration
- **GPU**: NVIDIA RTX 2060 or better (8GB+ VRAM)
- **CPU**: 6+ cores
- **RAM**: 16GB
- **Performance**: Processes 30-min recording in ~8-12 minutes (0.3-0.4x real-time)
- **Capacity**: Can handle 12-16+ hours of recordings per day

### Modern Hardware (2023+)
Systems with RTX 3060/4060 or newer will see 25-35% faster transcription times due to improved Tensor cores. CPU upgrades provide minimal benefit as Whisper transcription is GPU-bound.

### Model Selection vs. Hardware
- **base** model: Works on 4GB GPUs, lower quality, faster
- **medium** model (default): Requires 6GB+ VRAM, good quality/speed balance
- **large** model: Requires 8GB+ VRAM, best quality, slower

**See [SYSTEM_REQUIREMENTS.md](docs/SYSTEM_REQUIREMENTS.md) for detailed performance benchmarks and hardware selection guidance.**

## Quick Start

### Docker Deployment (Recommended)

```bash
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

# Copy and customize configuration
cp .env.example .env
nano .env  # Update CHANNELS_API_URL, DVR_RECORDINGS_PATH, etc.

# Deploy
docker-compose up -d
docker-compose logs -f

# Web GUI
# (after containers start)
# Visit: http://localhost:8000
```

### Local Development

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

# Copy and edit configuration
cp .env.example .env

# Setup pre-commit hooks (optional but recommended)
./setup-hooks.sh  # Linux/Mac
.\setup-hooks.ps1  # Windows

# Run tests
pytest

# Run watcher
python -m py_captions_for_channels

# Run web GUI (auto-reload for development)
uvicorn py_captions_for_channels.web_app:app --reload --port 8000
```

## Configuration

Configure via `.env` file (see `.env.example` for all options):

```bash
# Required settings
CHANNELS_API_URL=http://localhost:8089
DVR_RECORDINGS_PATH=/path/to/recordings
CAPTION_COMMAND=/usr/local/bin/whisper --model medium {path}

# Optional
DRY_RUN=true         # Test mode
WEBHOOK_PORT=9000
WHISPER_MODE=automatic  # "standard" (default) or "automatic" (optimized per source)
```

**New**: `WHISPER_MODE=automatic` enables intelligent optimization of both Whisper transcription and ffmpeg encoding based on source characteristics (OTA vs TV Everywhere). Can reduce encoding time by 30-50% for OTA content. See [AUTOMATIC_WHISPER_OPTIMIZATION.md](docs/AUTOMATIC_WHISPER_OPTIMIZATION.md) for details.

## ChannelWatch Setup

1. Open ChannelWatch: `http://YOUR_DVR_IP:8501`
2. Go to Settings ? Notification Providers
3. Enable "Custom URL"
4. Set URL: `json://YOUR_HOST_IP:9000`

## Tools

### FFmpeg Test Suite

Benchmark harness for testing different ffmpeg encoding strategies:

```bash
python -m tools.ffmpeg_test_suite \
    --input-video /path/to/test.mpg \
    --input-srt /path/to/test.srt \
    --out-dir ./test-results \
    --report-json report.json \
    --report-csv report.csv
```

Tests multiple variants (NVENC, CUVID, container formats) and generates performance/compatibility reports. Use this to optimize encoding for problematic recordings.

**See [docs/ffmpeg_test_suite.md](docs/ffmpeg_test_suite.md) for full documentation.**

## Documentation

- **[SETUP.md](SETUP.md)** - Quick setup guide with examples
- **[DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)** - Complete deployment documentation  
- **[.env.example](.env.example)** - All configuration options
- **[docs/ffmpeg_test_suite.md](docs/ffmpeg_test_suite.md)** - FFmpeg test suite for encoding optimization
- `docs/copilot/` - Design artifacts and session notes

## Architecture

```
ChannelWatch ? Webhook (this app) ? DVR API ? Caption Command
```

## License

MIT (see LICENSE)


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
