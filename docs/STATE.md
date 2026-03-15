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
- **`scripts/setup-linux.sh`** — Native Linux installer (apt/dnf/zypper, GPU, CIFS/NFS/local, systemd)

## In Progress

- **`setup-linux.sh` field testing** — iterating on koa dual-boot Ubuntu
  - Fixed: `wt_menu` height bug (passed width constant `$W` as height → froze terminal)
  - Fixed: `curl` missing on fresh Ubuntu Server minimal (false DVR connection failure)
  - Status: fixes pushed (`4568458`), awaiting next Linux boot to validate

## Known Issues / Pending

- **`env-settings` placeholder corruption** — the settings UI can write `.env.example` placeholder text (e.g. `←`) into the real `.env` if saved without filling all fields. Caused `DVR_MEDIA_HOST_PATH` corruption on niu. Not yet fixed.
- **`setup-linux.sh` untested end-to-end** — Docker install, CIFS mount, systemd service, `docker compose up` path not yet verified on real hardware

## Recent Decisions

- `.env` is always the source of truth — `config.py` unconditionally overwrites `os.environ` on import
- `DVR_PATH_PREFIX` auto-detection queries the DVR API using an embedded Python script (same logic in both `setup-wsl.sh` and `setup-linux.sh`)
- Setup wizard strips `DVR_MEDIA_HOST_PATH` from `.env.example` default; wizard manages path config
- `docs/copilot/` and `doc/copilot/` are gitignored (local session notes only); `docs/STATE.md`, `docs/TASK.md`, `docs/DECISIONS.md` are committed

## Deployment Inventory

| Host | OS | Role | py-captions status |
|------|----|------|--------------------|
| niu | Linux (native) | Channels DVR server + py-captions | Running (Docker, GPU) |
| borgpad | Windows (WSL2) | Secondary py-captions | Running |
| koa | Windows + Ubuntu dual-boot | Development machine | Testing setup-linux.sh |
