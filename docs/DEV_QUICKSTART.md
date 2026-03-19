# Developer Quick Start

This guide covers getting your local development environment set up, including VS Code and GitHub Copilot sign-in.

---

## 1. Clone and Install

```bash
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels
pip install -r requirements.txt -r requirements-dev.txt
```

Set up pre-commit hooks:

```bash
./setup-hooks.sh   # Linux/macOS
# or
./setup-hooks.ps1  # Windows
```

---

## 2. Configure

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Key variables to set: `CHANNELS_API_URL`, `DVR_RECORDINGS_PATH`. See `.env.example` for all options.

---

## 3. Run Tests

```bash
pytest
```

---

## 4. Start the App (without Docker)

```bash
python -m py_captions_for_channels
```

Or run just the web UI in dev mode:

```bash
uvicorn py_captions_for_channels.web_app:app --reload --port 8000
```

---

## 5. GitHub Copilot Sign-In (VS Code)

GitHub Copilot is available for AI-assisted development. To sign in:

1. **Locate the GitHub icon** in VS Code's **lower-right status bar** (not the command palette and not the profile icon in the lower-left).
2. Click it — it may show `Signed out`.
3. Click **"Enable more AI Features"** (this is the sign-in button; it is labeled this way rather than "Sign In").
4. A browser window will open. Complete the GitHub authentication and authorization flow.
5. Return to VS Code. If the status bar doesn't update, reload the window:
   - Command Palette → `Developer: Reload Window`

**If it still shows Signed out after authorizing:**

- Open the Command Palette and run `GitHub: Sign in`, or sign out and back in again.
- Make sure the **GitHub Copilot** extension is enabled and up to date (Extensions sidebar → search `GitHub Copilot`).
- Restart VS Code or disable/re-enable the extension.

---

## 6. Useful Dev Commands

| Task | Command |
|------|---------|
| Run all tests | `pytest` |
| Start watcher | `python -m py_captions_for_channels` |
| Web UI (dev) | `uvicorn py_captions_for_channels.web_app:app --reload --port 8000` |
| Docker deploy | `docker-compose up -d` |
| Dry run (no file writes) | Set `DRY_RUN=true` in `.env` |

---

## References

- [SETUP.md](../SETUP.md) — full deployment setup
- [SETUP_ADVANCED.md](../SETUP_ADVANCED.md) — advanced configuration
- [DOCKER_DEPLOYMENT.md](../DOCKER_DEPLOYMENT.md) — Docker-specific guide
- [docs/DECISIONS.md](DECISIONS.md) — architecture decisions
