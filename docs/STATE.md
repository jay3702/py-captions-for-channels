# Current Development State

> Update this file when the project state meaningfully changes.
> Read by incoming AI sessions alongside TASK.md for situational awareness.
> For project architecture and conventions, see `.github/copilot-instructions.md`.

---

## Completed

- **Core pipeline** — webhook → DVR API → Whisper → caption embed → state tracking
- **Web UI** (`web_app.py`, `webui/`) — FastAPI, recordings list, settings modal, queue display
- **Settings modal** — fixed top panel (status/buttons/restart banner), scrollable form body
- **Config source-of-truth fix** — `config.py` always overwrites env vars from `.env`; subprocesses see correct values
- **WAV extraction fix** — ffmpeg `-map 0:{absolute_index}` (was `-map 0:a:{N}` which broke on MPEG2)
- **Recordings whitelist fix** — `/api/recordings` passes `channel` arg to `whitelist.is_allowed()`
- **Setup wizard** — 6-step in-browser wizard (DVR URL, deployment type, mount, event source, caption engine, review/apply)
- **`scripts/setup-wsl.ps1` + `setup-wsl.sh`** — Windows WSL2 full installer with GPU, CIFS, systemd
- **`scripts/setup-dockerdesktop.ps1`** — Windows Docker Desktop installer
- **`scripts/setup-linux.sh`** — Native Linux installer; validated end-to-end on koa Ubuntu
  - Storage flow simplified to local/remote binary with auto-discovery (NFS exports → SMB shares → manual fallback)
  - Host bind-mount strategy for Docker volumes (avoids `nfsvers` Docker named-volume bugs)
  - NFS/SMB autodiscovery helpers (`showmount`, `smbclient`), scored best-match selection
  - LAN IP detection improved (`_detect_lan_ip` → `LAN_HINT` for prompt defaults)
  - **Bare-metal clean-install validated on koa (2026-03-17)** — three installer bugs found and fixed (see below)

## In Progress

- **Re-validation after installer bug fixes** — re-run `setup-linux.sh` on koa clean install to confirm all three fixes resolve the observed issues

## Known Issues / Pending

- **`env-settings` placeholder corruption** — the settings UI can write `.env.example` placeholder text (e.g. `←`) into the real `.env` if saved without filling all fields. Caused `DVR_MEDIA_HOST_PATH` corruption on niu. Not yet fixed.

## Recent Decisions

- `.env` is always the source of truth — `config.py` unconditionally overwrites `os.environ` on import
- `DVR_PATH_PREFIX` auto-detection queries the DVR API using an embedded Python script (same logic in both `setup-wsl.sh` and `setup-linux.sh`)
- Setup wizard strips `DVR_MEDIA_HOST_PATH` from `.env.example` default; wizard manages path config
- `docs/copilot/` and `doc/copilot/` are gitignored (local session notes only); `docs/STATE.md`, `docs/TASK.md`, `docs/DECISIONS.md` are committed
- Linux installer now defaults storage setup to host bind-mount behavior for reliability (`DVR_MEDIA_HOST_PATH` + `DVR_MEDIA_TYPE=none`) even when source storage is NFS/CIFS
- Linux installer storage selection is simplified to binary local/remote, with remote auto-discovery first (NFS exports, then SMB shares) and manual protocol/path fallback
- Linux installer now ensures invoking user is in `docker` group even when Docker is preinstalled

## Latest Validation Results (koa Ubuntu)

- `scripts/setup-linux.sh` validated end-to-end on koa with real DVR/NAS paths
- NFS Docker named-volume mount failure (`invalid argument` with `nfsvers=4.1,soft`) mitigated by host mount + bind mount strategy
- Manual processing UX improved:
  - manual queue loop checks immediately (no first-interval delay)
  - early "Preparing manual job" progress emitted
  - top process indicators use recent progress first and fallback state second
  - frontend now does a short burst refresh after adding manual jobs
- Performance observed on koa:
  - OTA ~60 min recording processed in under 9 min
  - TVE recording processed in ~4:10
  - roughly ~50% faster TVE processing vs same laptop on Windows

### Bare-metal clean install (2026-03-17) — bugs found & fixed

Three bugs surfaced on a full Ubuntu reinstall + fresh `git clone` + first run of `setup-linux.sh`:

1. **Garbled NFS dialog (run #1)** — `_ensure_probe_cmd` called `wt_info` inside a `$()` subshell (via `_discover_nfs_exports`/`_discover_smb_shares`), capturing whiptail ANSI escape sequences into `_AUTO_NFS` which were then rendered verbatim in the next dialog.
   - **Fix:** moved `_ensure_probe_cmd showmount/smbclient` calls to the main flow (before the subshells); discovery functions now use a simple `command -v` guard.

2. **GPU test failed (run #2)** — expected; NVIDIA Container Toolkit was freshly installed but Docker daemon restart sleep was insufficient for full runtime registration on first run. Re-running resolves it. No code change needed for the failure itself, but the `--yes` flag fix (below) prevents a separate prompt on re-run.

3. **Docker keyring overwrite prompt (run #3)** — two sub-issues:
   - Docker-already-installed skip check used `docker info` without `sudo`; fails when user's session predates `docker` group membership, causing installer to attempt Docker reinstall.
     - **Fix:** changed to `sudo docker info`.
   - `gpg --dearmor` prompts interactively when output file already exists.
     - **Fix:** added `--yes` to both `gpg --dearmor` calls (Docker keyring + NVIDIA toolkit keyring).

## Deployment Inventory

| Host | OS | Role | py-captions status |
|------|----|------|--------------------|
| niu | Linux (native) | Channels DVR server + py-captions | Running (Docker, GPU) |
| borgpad | Windows (WSL2) | Secondary py-captions | Running |
| koa | Windows + Ubuntu dual-boot | Development machine | Testing setup-linux.sh |
