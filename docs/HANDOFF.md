# Copilot Handoff Document

This file is the shared context bridge between VS Code Copilot sessions running
on different OS instances (Windows ↔ Linux dual-boot on koa).

**Workflow:**
1. Outgoing session fills in the relevant section and commits + pushes
2. Incoming session does `git pull`, then tells Copilot:
   > "Read docs/copilot/HANDOFF.md and continue from there."
3. Incoming session fills in its section when done, commits + pushes
4. Repeat

---

## Current Task

End-to-end test of `scripts/setup-linux.sh` on koa native Ubuntu.
Previous run (first attempt) hit two bugs now fixed — need to confirm the fixes
work and that the full install completes successfully.

## Commit to Test

`main @ 4568458` — "fix: setup-linux.sh — wt_menu freeze + curl prereq on fresh Ubuntu"

## Test Instructions

```bash
# 1. Get the latest fixes
cd ~
git clone https://github.com/jay3702/py-captions-for-channels.git   # if not already cloned
# OR if already cloned:
cd py-captions-for-channels && git pull

# 2. Run the installer
bash scripts/setup-linux.sh

# 3. Walk through the wizard:
#    - DVR URL: http://192.168.3.150:8089  (niu)
#    - Storage: CIFS  →  server: 192.168.3.150  share: Channels  mount: /mnt/channels
#    - Credentials: whatever niu's SMB credentials are (or guest if no auth)
#
# 4. If it completes, open http://localhost:8000 in a browser to confirm the web UI loads
#
# 5. Record the exact step where it failed (if it does), and capture any error text
```

## What to Watch For

- **Prerequisites block**: should silently install whiptail + curl before TUI starts (no more "cannot connect" false negative)
- **Storage type menu**: should show a proper menu box, not freeze (wt_menu height was 72 rows before — now fixed)
- **CIFS mount**: credential prompt → retry loop if auth fails
- **DVR path prefix auto-detect**: wizard queries niu's API to detect the recordings base path
- **Docker install**: koa Linux may already have Docker from previous attempt — script should skip if already installed
- **systemd service**: `py-captions-mount.service` should be created and enabled
- **Final screen**: should show `http://<koa-LAN-IP>:8000`

## Environment Notes

- koa native Ubuntu (dual-boot — not WSL, not a VM)
- No NVIDIA GPU available in this boot path (script should auto-skip GPU steps)
- niu (Channels DVR server) is at `192.168.3.150:8089`
- Recordings are on a CIFS share: `//192.168.3.150/Channels`
- Previous run: wt_menu froze the terminal; curl was missing so DVR test falsely failed



---

## Results  *(filled in by incoming session)*

<!-- What happened — verbatim error messages if any, whiptail dialog that was shown, -->
<!-- step it failed at, or confirmation that it completed successfully -->



## Diagnosis  *(filled in by incoming session if identifiable)*

<!-- If the incoming session can determine the cause, note it here -->
<!-- so the outgoing session can go straight to fixing it -->



## Suggested Fix  *(filled in by incoming session if identifiable)*

<!-- Pseudocode or description of the fix — the outgoing session implements it -->



---

## Session Log

<!-- Append a one-line entry each time a handoff occurs, newest at top -->
<!-- Format: YYYY-MM-DD HH:MM | direction | one-line summary -->

2026-03-15 | win→lin | test wt_menu freeze fix + curl prereq fix on koa Ubuntu
