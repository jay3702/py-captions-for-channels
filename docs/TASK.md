# AI Bootstrap

You are assisting development of **py-captions-for-channels** — a system that
automatically generates and embeds closed captions into Channels DVR recordings
using Whisper AI, deployed as a Docker container.

Read `.github/copilot-instructions.md` for architecture and conventions.
Read `docs/STATE.md` for current development status and known issues.
Then focus on the task described below.

---

# Current Task

Fix the **`env-settings` placeholder corruption** bug.

The settings UI (`web_app.py` + `webui/static/main.js`) can write `.env.example`
placeholder text (e.g. values containing `←` or the literal example strings) into
the real `.env` if the user saves without filling in a field.

This caused `DVR_MEDIA_HOST_PATH` corruption on niu in a previous session.

## Scope

1. Identify where `.env` values are written from the settings form (`/api/env` POST handler).
2. Add sanitization: skip or warn on any field whose value appears to be an unfilled placeholder.
3. Ensure the fix covers both the settings modal and the setup wizard.
4. Write a regression test if feasible.

## Definition of Done

- Saving settings with unfilled placeholder values does **not** overwrite `.env`.
- User sees a validation warning, or the placeholder field is skipped with an indicator.
- Existing filled fields continue to save correctly.

---

# Results  *(bare-metal clean install — 2026-03-17)*

Ran on koa after full Ubuntu reinstall + `git clone` + first `bash scripts/setup-linux.sh`.

**Three bugs found and fixed (pushed in this session):**

1. **Garbled dialog on NFS detection** — ANSI escape sequences from `wt_info` inside a `$()` subshell corrupted the NFS export input dialog on run #1. Fixed by hoisting `_ensure_probe_cmd` calls out of the subshells into the main flow.

2. **GPU test failed** — Expected on first run; NVIDIA toolkit freshly installed + Docker restart sleep too short. Resolved by re-running. No functional code change needed for this; covered by `--yes` fix below preventing a new prompt.

3. **Docker keyring overwrite prompt** — Two causes: (a) `docker info` without `sudo` returned false on a fresh session where group membership wasn't active yet, causing Docker to be re-installed; fixed with `sudo docker info`. (b) `gpg --dearmor` prompted interactively when keyring file already existed; fixed with `--yes` on both Docker and NVIDIA keyring writes.

**Next:** Re-run `setup-linux.sh` on koa (same install) to confirm all three fixes resolve cleanly with no prompts or corrupted dialogs.

# Results  *(2nd bare-metal + GPU validation — 2026-03-20)*

Confirmed by user on Windows after returning from Linux session.

- All three 2026-03-17 bug fixes (❌ garbled NFS dialog, ❌ GPU test on first run, ❌ keyring overwrite prompt) resolved cleanly.
- NVIDIA GPU installation flow working end-to-end including GPU pre-check dialogs.
- Bare-metal clean install validated.

---

# Session Log

2026-03-20 | lin→win | 2nd bare-metal + GPU install both confirmed working; pivoting to env-settings placeholder fix
2026-03-20 | lin | Found Secure Boot false-pass bug on koa reboot (container exit 128 after GPU install); fixed installer to warn when nvidia-smi passes but SB active; koa .env switched to CPU mode; container needs `docker compose up -d`
2026-03-18 | lin | GPU pre-check dialogs + startup upgrade hint added; OPTIMIZATION_MODE default → automatic; all pushed as 613e684; preparing 2nd bare-metal validation
2026-03-17 | lin | bare-metal clean install on koa; 3 installer bugs found + fixed; awaiting re-validation
2026-03-16 | lin→win | installer + runtime UX validated in-place; code pushed as 9245a66
2026-03-16 | lin | validated installer + runtime flow on koa; next is clean bare-metal rebuild validation
2026-03-15 | win→lin | push wt_menu freeze fix + curl prereq fix; validate on koa Ubuntu
