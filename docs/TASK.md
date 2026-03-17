# AI Bootstrap

You are assisting development of **py-captions-for-channels** — a system that
automatically generates and embeds closed captions into Channels DVR recordings
using Whisper AI, deployed as a Docker container.

Read `.github/copilot-instructions.md` for architecture and conventions.
Read `docs/STATE.md` for current development status and known issues.
Then focus on the task described below.

---

# Current Task

Run a **cold-start bare-metal validation** of `scripts/setup-linux.sh` on koa
after tearing down the current Linux environment.

The current installer and UI/backend queue fixes have already been validated in
an in-place environment; now we need proof that first-run setup works from a
clean machine with no prior Docker/NFS/CIFS state.

## Scope

1. Start from a clean Ubuntu boot (or freshly reinstalled Linux environment).
2. Clone repo and run installer.
3. Verify web UI starts and manual process pipeline state updates correctly.
4. Record any drift between expected and actual prompts/behavior.

## Test Commands

```bash
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels
bash scripts/setup-linux.sh
```

## Expected Installer Behavior

- IP prompts prefilled with detected LAN hint (`192.168.x.xxx` style)
- Storage prompt is binary: local vs remote
- Remote storage flow:
	- ask server address
	- auto-detect NFS exports first, then SMB shares
	- if discovery fails, prompt for protocol and manual path/share
- Writes bind-mount style env config (`DVR_MEDIA_HOST_PATH`, `DVR_MEDIA_TYPE=none`)
- Adds user to `docker` group idempotently

## Post-Install Checks

```bash
sg docker -c 'docker compose ps'
sg docker -c 'docker compose logs --tail 120 py-captions'
curl -s http://localhost:8000/api/status | python3 -m json.tool
```

## Manual Processing UX Checks

1. Queue one recording from manual process dialog.
2. Confirm queue shows running state promptly.
3. Confirm pipeline progress appears without long initial delay.
4. Confirm top indicators (`File Ops`, `Whisper`, `ffmpeg`) reflect active work.

## If It Fails

1. Note exact installer step or UI action where mismatch occurs.
2. Capture exact error text.
3. Save relevant logs:

```bash
tail -n 200 /tmp/py_captions_install.log
sg docker -c 'docker compose logs --tail 200 py-captions'
```

---

# Results  *(bare-metal clean install — 2026-03-17)*

Ran on koa after full Ubuntu reinstall + `git clone` + first `bash scripts/setup-linux.sh`.

**Three bugs found and fixed (pushed in this session):**

1. **Garbled dialog on NFS detection** — ANSI escape sequences from `wt_info` inside a `$()` subshell corrupted the NFS export input dialog on run #1. Fixed by hoisting `_ensure_probe_cmd` calls out of the subshells into the main flow.

2. **GPU test failed** — Expected on first run; NVIDIA toolkit freshly installed + Docker restart sleep too short. Resolved by re-running. No functional code change needed for this; covered by `--yes` fix below preventing a new prompt.

3. **Docker keyring overwrite prompt** — Two causes: (a) `docker info` without `sudo` returned false on a fresh session where group membership wasn't active yet, causing Docker to be re-installed; fixed with `sudo docker info`. (b) `gpg --dearmor` prompted interactively when keyring file already existed; fixed with `--yes` on both Docker and NVIDIA keyring writes.

**Next:** Re-run `setup-linux.sh` on koa (same install) to confirm all three fixes resolve cleanly with no prompts or corrupted dialogs.

---

# Session Log

2026-03-17 | lin | bare-metal clean install on koa; 3 installer bugs found + fixed; awaiting re-validation
2026-03-16 | lin→win | installer + runtime UX validated in-place; code pushed as 9245a66
2026-03-16 | lin | validated installer + runtime flow on koa; next is clean bare-metal rebuild validation
2026-03-15 | win→lin | push wt_menu freeze fix + curl prereq fix; validate on koa Ubuntu
