# py-captions-for-channels

A modular Python tool that listens for Channels DVR recording events and triggers a captioning pipeline.

Docs and Copilot materials: see `docs/copilot/` for Copilot prompts, session summaries, and design artifacts. Redact secrets before sharing.

License: MIT (see `LICENSE`)

## Quick start

1. Install dependencies (use virtualenv):

    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    ```

2. Run the watcher (development):

    ```powershell
    python scripts\py-captions-watcher.py
    ```
