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

Some Channels DVR clients — such as Apple TV and the web player — automatically detect and display captions from `.srt` files placed alongside recordings. Others, such as Fire TV and Android clients, require captions to be muxed into the recording file itself (see `TRANSCODE_FOR_FIRETV` in the [Fire TV / Android section](SETUP_ADVANCED.md#fire-tv--android-transcoding)).

## Requirements

- **Channels DVR** server (with recordings accessible via network/mount)
- **NVIDIA GPU** with 6GB+ VRAM (GTX 1660 Super / RTX 2060 or better)
- **NVIDIA driver ≥ 520** on the Docker host (supports CUDA 12.2, which the container requires). Check with `nvidia-smi` — the "CUDA Version" shown must be **12.2 or higher**. If it's lower, GPU acceleration will silently fall back to CPU; the container logs a warning at startup identifying the mismatch.
- **Docker** with NVIDIA Container Toolkit (`nvidia-container-toolkit`)
- **ChannelWatch** (optional, for webhook-based detection instead of polling)

> **CPU-only operation** is possible but significantly slower (~10 min SRT-only, ~10–20 min with Fire TV transcoding, per 1-hour recording).

Timings below are for the default **SRT-only** mode. `TRANSCODE_FOR_FIRETV=true` adds encoding time (see [GPU Configuration](SETUP_ADVANCED.md#gpu-configuration)).

| Hardware | 1-hr OTA Recording | 1-hr TVE (Streaming) | Daily Capacity |
|----------|-------------------|---------------------|----------------|
| CPU only | ~10–15 min | ~10 min | Very limited |
| RTX 2080 (11GB) | ~3–5 min | ~1–2 min | 20+ hours |
| RTX 3060/4060+ | ~2–4 min | ~1–2 min | 24+ hours |

> **Note:** OTA (over-the-air) recordings require MPEG2→H.264 transcoding, which adds time even in SRT-only mode. TVE (streaming) recordings are already H.264 and only need Whisper transcription (~1–2 min with GPU, ~10 min with CPU).

See [docs/SYSTEM_REQUIREMENTS.md](docs/SYSTEM_REQUIREMENTS.md) for detailed benchmarks and hardware guidance.

## Installation

**Linux — one command** (run on the server; installs Docker, GPU toolkit, and the container):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main/scripts/setup-linux.sh)
```

**Windows — one command** (run in an Administrator PowerShell window; installs WSL2, Docker, GPU toolkit, and the container):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
irm https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main/setup-windows.ps1 | iex
```

Both scripts run a guided TUI wizard — they ask for your DVR URL, recordings location, and NAS details (if any), then complete the installation unattended.

For manual installation, troubleshooting, and developer setup: **[INSTALL.md](INSTALL.md)**

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
| [INSTALL.md](INSTALL.md) | Installation — quick one-command and manual tracks, troubleshooting, developer setup |
| [SETUP_ADVANCED.md](SETUP_ADVANCED.md) | GPU tuning, Fire TV transcoding, webhooks, whitelist regex |
| [.env.example](.env.example) | All configuration options with descriptions |
| [docs/SYSTEM_REQUIREMENTS.md](docs/SYSTEM_REQUIREMENTS.md) | Hardware benchmarks and sizing |
| [docs/AUTOMATIC_WHISPER_OPTIMIZATION.md](docs/AUTOMATIC_WHISPER_OPTIMIZATION.md) | Smart encoding optimization |
| [docs/LANGUAGE_SELECTION.md](docs/LANGUAGE_SELECTION.md) | Multi-language audio/subtitle processing |
| [docs/LOGGING.md](docs/LOGGING.md) | Log levels, job markers, verbosity |

## Development

See the [Developer Setup](INSTALL.md#developer-setup) section of INSTALL.md.

## Development Story

This project started as a Linux shell script built with ChatGPT. It worked, but had serious architectural, performance, and reliability limitations — mostly caused by parsing the Channels DVR log file as the recording discovery mechanism. To solve those problems, the project was rewritten in Python using VS Code with GitHub Copilot. That shift led to discovering that ChannelWatch could provide clean "recording complete" notifications (though only the title, not the full path), and that the Channels DVR API could supply both the file path and recording status. Polling the API directly turned out to be simpler and more reliable than either log parsing or webhooks.

From that rewrite forward, the entire project was built through AI-assisted pair programming — a continuous conversation between a developer and GitHub Copilot (powered by Claude). Every feature — GPU acceleration, the web dashboard, quarantine system, 344-test suite, Docker deployment — was designed, implemented, debugged, and documented within that workflow. The AI wrote the code; the developer provided domain knowledge, tested on real hardware (i7-7700K + RTX 2080), and steered decisions. Even this README was written that way.

Occasionally a particular problem would get bogged down, and a side conversation with ChatGPT would help break through it. If that yielded a useful solution, ChatGPT would prepare instructions for Copilot, which were then transferred back into the Copilot conversation. This worked well and helped reduce the "premium requests" generated by Copilot.

## Known Limitations

- **Playback interruption during transcoding** — When `TRANSCODE_FOR_FIRETV` is enabled, the processed `.mpg` file replaces the original while keeping a `.cc4chan.orig` backup. If a recording is actively being watched when the replacement happens, the Channels client may freeze. The workaround is to return to the recordings menu and resume playback — it will recover immediately. There is no way to avoid this; the file replacement is already atomic (`os.rename`), but the client detects the change underneath it.

## License

MIT — see [LICENSE](LICENSE).
