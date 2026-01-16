# py-captions-for-channels

A modular Python tool that listens for Channels DVR recording events and triggers a captioning pipeline.

Docs and Copilot materials: see `docs/copilot/` for Copilot prompts, session summaries, and design artifacts. 

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

## Using GitHub Copilot in Visual Studio

This project supports both inline completions and the Copilot Chat pane in Visual Studio. Add these notes for contributors:

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
