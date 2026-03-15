# Architectural Decisions & Rejected Approaches

> Log decisions here to prevent re-proposing rejected solutions across sessions.
> Format: date, decision, rationale, what was rejected and why.

---

## Config / Environment

### `.env` always overwrites `os.environ` (2026-01)
**Decision:** `config.py` `_load_dotenv_file()` uses `os.environ[key] = value` for all keys unconditionally.
**Rationale:** Docker Compose injects env vars before Python starts; without overwriting, values in `.env` (e.g. `TRANSCODE_FOR_FIRETV=false`) were silently ignored by subprocesses that re-import config.
**Rejected:** `os.environ.setdefault()` — only sets if key absent; breaks when docker-compose injects the wrong value.
**Rejected:** A `_WIZARD_MANAGED_KEYS` allowlist of keys to override — added complexity for no benefit; all keys should respect `.env`.

---

## Installer / Setup

### Native Linux installer separate from WSL installer (2026-03)
**Decision:** `setup-linux.sh` is a distinct script from `setup-wsl.sh`, not a combined script with flags.
**Rationale:** WSL2 requires Windows-side steps (portproxy, Task Scheduler, `.wslconfig` networking), NVIDIA toolkit setup differs, and the guard clauses would make a combined script hard to follow.
**Rejected:** Single script with `--wsl` / `--native` flag — too much conditional branching; better to keep concerns separate.

### ffmpeg `-map 0:{absolute_index}` for WAV extraction (2026-01)
**Decision:** Use the absolute stream index from ffprobe output, not the audio-relative index.
**Rationale:** On MPEG2 files the global stream index differs from the audio-relative index. `-map 0:a:{N}` selected the wrong stream or failed.
**Rejected:** `-map 0:a:{N}` (audio-relative) — breaks on containers where audio streams are not contiguous from index 0.

---

## Web UI

### Inline restart banner in settings modal fixed panel (2026-01)
**Decision:** After saving settings, show an inline "Restart now / Close" banner inside the fixed top panel of the settings modal rather than a separate toast or alert.
**Rationale:** Keeps the user in context; makes the restart action immediately visible without navigating away.
**Rejected:** Browser `alert()` — blocks the UI thread and looks unprofessional.
**Rejected:** Auto-restart on save — too aggressive; user may be mid-edit.

### 6-step setup wizard in-browser (2026-01)
**Decision:** The setup wizard is a browser-based multi-step modal, not a shell script or separate page.
**Rationale:** Works on all platforms (Windows Docker Desktop, WSL2, native Linux); no extra tooling; accessible from any machine that can reach the web UI.
**Rejected:** Wizard-only shell script — doesn't work on Windows Docker Desktop where there's no terminal access to the container.

---

## Deployment

### `restart: unless-stopped` in docker-compose.yml
**Decision:** Container always restarts unless explicitly stopped.
**Rationale:** Survives Docker daemon restarts, host reboots, and container crashes without manual intervention.
**Rejected:** `restart: on-failure` — doesn't restart after host reboot if Docker daemon itself restarts cleanly.

### CIFS credentials in `/etc/cifs-credentials-py-captions` (chmod 600) (2026-03)
**Decision:** Store NAS credentials in a root-owned credentials file, not in `/etc/fstab` inline or in `.env`.
**Rationale:** Keeps password out of world-readable files and out of git history.
**Rejected:** Inline credentials in `/etc/fstab` — world-readable by default.
**Rejected:** Storing SMB password in `.env` — `.env` may be committed accidentally or read by container processes.
