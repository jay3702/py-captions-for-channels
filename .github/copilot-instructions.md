# Copilot Instructions for AI Coding Agents

## Project Overview
- **Purpose:** Automate caption generation for Channels DVR recordings using Whisper AI.
- **Core Flow:**
  1. Listens for ChannelWatch webhooks (recording complete events)
  2. Fetches recording info from Channels DVR API
  3. Runs a configurable caption command (default: Whisper)
  4. Tracks processed recordings to avoid duplicates
  5. Exposes a web UI for monitoring and manual actions

## Key Components
- `py_captions_for_channels/` — Main Python package
  - `channels_api.py` — Interacts with Channels DVR API
  - `channelwatch_source.py`, `channelwatch_webhook_source.py` — Webhook/event sources
  - `pipeline.py` — Orchestrates end-to-end processing
  - `embed_captions.py` — Caption embedding logic
  - `web_app.py` — FastAPI web UI
  - `state.py` — Tracks processed recordings (idempotency)
  - `logging/structured_logger.py` — Structured logging
- `scripts/` — Utilities, test runners, and manual tools
- `docs/`, `doc/` — Design docs, session notes, deployment guides

## Developer Workflows
- **Run all tests:** `pytest`
- **Start watcher:** `python -m py_captions_for_channels`
- **Run web UI (dev):** `uvicorn py_captions_for_channels.web_app:app --reload --port 8000`
- **Docker deploy:** `docker-compose up -d`
- **Pre-commit hooks:** `./setup-hooks.sh` (Linux/Mac), `./setup-hooks.ps1` (Windows)

## Configuration
- All runtime config via `.env` file (see `.env.example`)
- Key env vars: `CHANNELS_API_URL`, `DVR_RECORDINGS_PATH`, `CAPTION_COMMAND`
- Dry-run mode: set `DRY_RUN=true` to test without modifying files

## Patterns & Conventions
- **Idempotency:** Always check state before processing a recording
- **Logging:** Use `structured_logger` for all logs; prefer structured over print
- **Extensibility:** New sources should subclass the polling/webhook base classes
- **Testing:** Place tests in `tests/`, use pytest fixtures for state setup
- **Shell scripts:** Use `.sh` for Linux/Mac, `.ps1` for Windows; keep logic in Python when possible

## Integration Points
- **Channels DVR API:** See `channels_api.py` for endpoints used
- **ChannelWatch:** Webhook integration (see `channelwatch_webhook_source.py`)
- **Whisper AI:** External captioning command (configurable)

## References
- See `README.md`, `SETUP.md`, and `DOCKER_DEPLOYMENT.md` for more details
- Design notes: `docs/copilot/`, `doc/copilot/`

---

**If unsure about a workflow or pattern, check the referenced files or ask for clarification.**
