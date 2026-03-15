# AI Bootstrap

You are assisting development of **py-captions-for-channels** — a system that
automatically generates and embeds closed captions into Channels DVR recordings
using Whisper AI, deployed as a Docker container.

Read `.github/copilot-instructions.md` for architecture and conventions.
Read `docs/STATE.md` for current development status and known issues.
Then focus on the task described below.

**Incoming environment:** koa — Ubuntu 24.04 native boot (dual-boot with Windows).
**No GPU** in this boot. niu (Channels DVR) is at `192.168.3.150:8089`.

---

# Current Task

End-to-end validation of `scripts/setup-linux.sh` — two bugs were fixed and
pushed from Windows. Need to confirm both fixes work and that the full install
completes successfully on a real Ubuntu machine.

## Commit to Test

`main @ 4568458` — "fix: setup-linux.sh — wt_menu freeze + curl prereq on fresh Ubuntu"

## Test Commands

```bash
# If this is a fresh clone:
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

# If already cloned:
git pull

# Run the installer
bash scripts/setup-linux.sh
```

## Wizard Inputs

When the TUI prompts you:

| Prompt | Value |
|--------|-------|
| Deploy directory | `~/py-captions-for-channels` (default) |
| DVR URL | `http://192.168.3.150:8089` |
| Storage type | CIFS |
| CIFS server | `192.168.3.150` |
| CIFS share | `Channels` |
| Mount point | `/mnt/channels` |
| CIFS username | *(use whatever credentials work for niu's share, or guest)* |
| Deploy dir confirm | accept |

## What to Watch For

- **Prerequisites block** — should silently install whiptail + curl before TUI starts (no "cannot connect" false negative from missing curl)
- **Storage menu** — should show a proper 4-item menu box without freezing (height bug was 72 rows)
- **Docker install** — if Docker already installed from previous attempt, should skip
- **DVR path prefix** — auto-detect step queries niu; should find or prompt for prefix
- **systemd service** — `py-captions-mount.service` created and enabled
- **Final screen** — should show `http://<koa-LAN-IP>:8000`; open in browser to verify

## If It Fails

1. Note the **exact step name** shown in the whiptail title bar
2. Copy the **exact error text** from the screen or from `/tmp/py_captions_install.log`
3. Fill in the Results section below, commit, push, reboot to Windows

---

# Results  *(fill in on Linux)*

<!-- What happened — step it failed at, verbatim error, or "completed successfully" -->



## Diagnosis

<!-- If you can identify the cause, note it here -->



## Suggested Fix

<!-- Pseudocode or description — Windows session implements it -->



---

# Session Log

<!-- Newest entry at top. Format: YYYY-MM-DD | direction | summary -->

2026-03-15 | win→lin | push wt_menu freeze fix + curl prereq fix; validate on koa Ubuntu
