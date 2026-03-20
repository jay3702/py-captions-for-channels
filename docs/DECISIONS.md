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

### `modprobe` probe to distinguish reboot-needed vs MOK-not-enrolled (2026-03-20)
**Decision:** When NVIDIA packages are installed but the module is not loaded, the installer runs `sudo modprobe nvidia` and branches on the result: (1) module loads → reboot suggestion; (2) "Key was rejected by service" → specific MOK enrollment instructions (`mokutil --import MOK.der` + reboot + confirm at blue screen); (3) other failure + Secure Boot active → generic MOK/SB guidance; (4) other failure, no SB → generic reboot suggestion.
**Rationale:** The previous logic guessed based on `mokutil --sb-state`, but SB enabled is not the same as SB blocking. After a fresh Ubuntu reinstall, DKMS generates a new signing key for nvidia but the new key is never enrolled (the old key's fingerprint is still in MOK NVRAM from the previous install). `modprobe` returns the definitive error "Key was rejected by service" — this is the only reliable signal.
**Rejected:** Comparing `modinfo nvidia` sig_key fingerprint against `dmesg` "Loaded X.509 cert" entries — correct in theory but fragile (format normalization, sudo required for dmesg, doesn't cover all keyring sources).
**Rejected:** Branching on `mokutil --sb-state` alone — "SB enabled" ≠ "module blocked"; a properly enrolled MOK key works fine with SB on.

### Secure Boot warning when `nvidia-smi` passes but Secure Boot is active (2026-03-20)
**Decision:** Even when `nvidia-smi` works at install time, check `mokutil --sb-state`. If Secure Boot is enabled, show a three-choice menu: continue GPU mode (risky), switch to CPU mode (safe), or quit to fix first.
**Rationale:** The NVIDIA kernel module can be loaded from a prior session at install time, making `nvidia-smi` pass the pre-check, but it will be blocked after the next reboot — leaving the container unable to start (exit 128, "Driver Not Loaded"). This happened on koa: installer completed GPU mode successfully, then reboot caused the container to fail.
**Rejected:** Silent GPU mode despite Secure Boot active — produces a broken install that only manifests at reboot.
**Rejected:** Forcing CPU mode unconditionally when Secure Boot is active — users who have properly enrolled a MOK key should still be able to use GPU mode.

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
