# py-captions-for-channels

Automatic caption generation for Channels DVR recordings using Whisper AI.

## Features

? **Automatic Processing** - Monitors ChannelWatch for completed recordings  
? **Flexible Configuration** - Environment variables or .env file  
? **Docker Ready** - Easy deployment with docker-compose  
? **Idempotent** - Tracks processed recordings to avoid duplicates  
? **Robust** - Webhook receiver with automatic reconnection  
? **Dry-Run Mode** - Test before executing actual commands  

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
DRY_RUN=true        # Test mode
WEBHOOK_PORT=9000
```

## ChannelWatch Setup

1. Open ChannelWatch: `http://YOUR_DVR_IP:8501`
2. Go to Settings ? Notification Providers
3. Enable "Custom URL"
4. Set URL: `json://YOUR_HOST_IP:9000`

## Documentation

- **[SETUP.md](SETUP.md)** - Quick setup guide with examples
- **[DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)** - Complete deployment documentation  
- **[.env.example](.env.example)** - All configuration options
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
