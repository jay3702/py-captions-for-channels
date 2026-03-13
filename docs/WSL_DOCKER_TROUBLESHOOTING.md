# WSL + Docker Troubleshooting: Field Guide

This document captures every real-world failure encountered during setup and operation of
py-captions-for-channels on a Windows 11 / WSL2 / NVIDIA GPU host. Each entry is structured
as **Symptom → Root Cause → Fix → Missteps to avoid**.

Murphy's Law applies liberally — many fixes trigger the next problem.
Read the full entry before acting, because the "obvious" fix often has hidden consequences.

---

## Table of Contents

1. [Volume mount fails — "no such file or directory"](#1-volume-mount-fails--no-such-file-or-directory)
2. [Running `docker compose` from the wrong directory creates a bogus `.env`](#2-running-docker-compose-from-the-wrong-directory-creates-a-bogus-env)
3. [Stale Docker named volume survives teardown/reinstall](#3-stale-docker-named-volume-survives-teardownreinstall)
4. [CIFS mount directory does not exist at boot time](#4-cifs-mount-directory-does-not-exist-at-boot-time)
5. [ffmpeg uses CPU despite GPU being available (NVENC)](#5-ffmpeg-uses-cpu-despite-gpu-being-available-nvenc)
6. [Whisper uses GPU but ffmpeg encode is CPU — after NVENC fix](#6-whisper-uses-gpu-but-ffmpeg-encode-is-cpu--after-nvenc-fix)
7. [Container starts but recording path is wrong inside container](#7-container-starts-but-recording-path-is-wrong-inside-container)
8. [Job shows as active in System Monitor after cancellation](#8-job-shows-as-active-in-system-monitor-after-cancellation)
9. [Container sees empty `/mnt/channels` — bind-mount race at autostart](#9-container-sees-empty-mntchannels--bind-mount-race-at-autostart)
10. [General WSL Docker diagnostics cheat sheet](#10-general-wsl-docker-diagnostics-cheat-sheet)

---

## 1. Volume mount fails — "no such file or directory"

### Symptom
Container fails to start. `docker compose logs` shows:

```
Error response from daemon: failed to mount local volume:
  mount /mnt/media: no such file or directory
```

Or the container starts but recordings are not visible at the expected path inside the container.

### Root Cause
**Two independent causes can produce this same error:**

**A) Stale named volume `opts.json`.** Docker named volumes store their driver options
(including the `device` path) in an internal `opts.json` file at volume creation time.
This file is NOT re-read from `.env` on subsequent `docker compose up` calls.
If the volume was created when `DVR_MEDIA_DEVICE` pointed to `/mnt/media` and you later
changed it to `/mnt/channels`, the volume still mounts `/mnt/media` — which doesn't exist.

**B) CIFS mount directory missing.** The `.bashrc`-injected CIFS mount command runs at WSL
shell startup. If the target directory (e.g. `/mnt/channels`) was never created, `mount.cifs`
fails silently and Docker sees an empty or missing path when it tries to bind into the container.

### Fix

**For cause A — delete and recreate the named volume:**
```bash
# In WSL or PowerShell
docker compose down
docker volume rm py-captions-for-channels_channels_media
docker compose up -d   # volume is recreated with current .env values
```

**For cause B — create the mount point:**
```bash
sudo mkdir -p /mnt/channels   # or whatever MOUNT_POINT is set to
```
Then manually trigger the CIFS mount (or restart WSL so `.bashrc` re-runs):
```bash
sudo mount -t cifs //NAS_IP/share /mnt/channels \
  -o credentials=/etc/smb-credentials,uid=$(id -u),gid=$(id -g),vers=3.0
```

### Missteps to Avoid
- **Don't just restart the container.** `docker compose restart` does not recreate volumes.
  The name `up -d` also does not recreate an existing volume — you must `rm` it first.
- **Don't assume the CIFS mount survived a WSL restart.** WSL does not run `systemd` by
  default; mounts from a previous session are gone. The `setup-gpu-wsl.sh` script injects
  the mount command into `.bashrc` so it re-runs on shell start, but only if you open a
  WSL shell. A bare `docker compose up` from PowerShell won't trigger `.bashrc`.
- **Don't edit `docker-compose.yml` to change the device path.** The volume driver options
  come from `.env` at compose invocation time, but Docker only applies them when the volume
  is first created. Editing compose does nothing until you delete the volume.

---

## 2. Running `docker compose` from the wrong directory creates a bogus `.env`

### Symptom
Container does not pick up any of your settings, or the stack starts with wrong values.
On inspection, there is a directory named `.env` in the repo folder instead of a file.

```bash
ls -la ~/py-captions-for-channels/.env
# drwxr-xr-x  .env/      ← directory, not a file
```

### Root Cause
If you run `docker compose up -d` from **a different directory** (e.g. `/mnt/c/Users/jay/...`
instead of `~/py-captions-for-channels`), Docker Compose looks for `.env` relative to the
working directory. When it doesn't find one, it creates **a directory named `.env`** as a
side effect of volume resolution on some Docker Compose versions.

This happened twice: once from `/mnt/c/Users/jay/py-captions-for-channels` and once from
a PowerShell session that had a different working directory.

### Fix
```bash
# Remove the bogus directory
rm -rf ~/py-captions-for-channels/.env

# Re-create from the example
cp ~/py-captions-for-channels/.env.example.nvidia ~/py-captions-for-channels/.env
# Edit with your actual values
nano ~/py-captions-for-channels/.env

# Always cd first, then compose
cd ~/py-captions-for-channels
docker compose down
docker compose up -d
```

### Missteps to Avoid
- **Never run `docker compose` from a Windows path** (`/mnt/c/...`) when your config lives
  in the WSL home directory. Always `cd` into the target directory first.
- **Check `ls -la .env` before troubleshooting anything else.** If `.env` is a directory,
  all your config is silently ignored and this is the root cause of seemingly unrelated failures.
- **git will not track the `.env` directory** (it's gitignored), so `git status` won't reveal it.
  Use `ls -la` directly.

---

## 3. Stale Docker named volume survives teardown/reinstall

### Symptom
After running the teardown script and reinstalling, the stack starts but immediately hits the
"no such file or directory" error even though `.env` has the correct `DVR_MEDIA_DEVICE` path.

### Root Cause
Docker named volumes are **not removed by `docker compose down`** unless you pass `-v`.
The `teardown-wsl.ps1` script (before the fix) only stopped containers and removed images;
it left `py-captions-for-channels_channels_media` intact with stale `opts.json`.

The stale `opts.json` contained `device=/mnt/media` from an older installation. The new
`.env` said `/mnt/channels`, but the volume was never recreated, so it ignored the new value.

### Fix
The teardown script was updated to explicitly remove the volume:

```powershell
# In teardown-wsl.ps1 — Step 1a
docker compose down
docker volume rm py-captions-for-channels_channels_media 2>/dev/null || true
docker rmi ghcr.io/jay3702/py-captions-for-channels:latest 2>/dev/null || true
```

To do this manually:
```bash
docker volume ls | grep py-captions   # verify the volume name
docker volume rm py-captions-for-channels_channels_media
```

### Missteps to Avoid
- **`docker compose down -v` is destructive** — it removes ALL named volumes for that project,
  including any data volumes you may want to keep. Prefer removing the specific media volume by name.
- **`docker volume inspect <name>`** shows you the current `opts.json` device path.
  Run this first to confirm the volume is stale before deleting it:
  ```bash
  docker volume inspect py-captions-for-channels_channels_media
  # Look for "device" under "Options"
  ```

---

## 4. CIFS mount directory does not exist at boot time

### Symptom
After a WSL restart, the NAS share is not mounted even though the `.bashrc` mount command
is present. `docker compose up -d` fails immediately with a mount error.

### Root Cause
The `.bashrc` snippet injected by `setup-gpu-wsl.sh` ran `mount.cifs` without first
ensuring the target directory existed. On a clean WSL install (or after `wsl --terminate`),
`/mnt/channels` does not exist, so `mount.cifs` fails immediately and logs nothing visible.

### Fix
`setup-gpu-wsl.sh` was updated to add a `mkdir -p` guard before the mount retry loop:

```bash
# In ~/.bashrc — injected by setup-gpu-wsl.sh
sudo mkdir -p /mnt/channels    # ← added guard
for attempt in 1 2 3; do
    sudo mount -t cifs //NAS_IP/share /mnt/channels \
      -o credentials=/etc/smb-credentials,... && break
    sleep 2
done
```

Manual fix for immediate recovery:
```bash
sudo mkdir -p /mnt/channels
sudo mount -t cifs //NAS_IP/share /mnt/channels \
  -o credentials=/etc/smb-credentials,uid=$(id -u),gid=$(id -g),vers=3.0
```

### Missteps to Avoid
- **Checking `dmesg` or `journalctl` for CIFS errors**: neither is useful here because the
  failure happens at the `bash` level, not the kernel level. Check `mount | grep cifs` to
  see if the share is actually mounted.
- **Assuming the mount persists across `wsl --terminate` / `wsl --shutdown`**: it does not.
  WSL2 is a lightweight VM that loses mounts on shutdown unless systemd mount units are configured.

---

## 5. ffmpeg uses CPU despite GPU being available (NVENC)

### Symptom
Job completes but the ffmpeg encode stage takes 20–30+ minutes instead of 5–8 minutes.
Logs show:

```
GPU Encode: NOT AVAILABLE (runtime check failed)
```

or ffmpeg selecting software encoder:
```
Stream #0: Video: h264 (libx264)
```

`nvidia-smi` on the WSL host shows the GPU, and Whisper runs on GPU.

### Root Cause
The NVIDIA Container Toolkit mounts **CUDA compute libraries** into the container at runtime,
but it does **not** mount **`libnvidia-encode.so.1`** — the library required for NVENC
hardware video encoding. That library lives at `/usr/lib/wsl/lib/libnvidia-encode.so.1`
on the WSL host but is invisible inside the container.

The internal `_test_nvenc_runtime()` function runs `ffmpeg -f lavfi -i color=c=black:s=16x16:r=1 -t 1 -c:v h264_nvenc -f null -` and checks the exit code. It returned non-zero because
`libnvidia-encode.so.1` was not found at runtime, so the capability was marked unavailable
and the pipeline fell back to CPU encoding.

This is a WSL-specific issue. On a bare Linux host, the nvidia container toolkit mounts
everything. On WSL2, the video encode library is a stub that only exists at `/usr/lib/wsl/lib`.

### Fix
Three changes were made together (commit `9f808d7`):

**1. `docker-compose.yml` — bind-mount the WSL lib path:**
```yaml
volumes:
  - ${WSL_LIB_PATH:-/tmp}:/usr/lib/wsl/lib:ro
```
The `:-/tmp` default means this is a no-op on non-WSL hosts (mounts an empty read-only /tmp).

**2. `Dockerfile` — add the path to `LD_LIBRARY_PATH`:**
```dockerfile
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib/wsl/lib:$LD_LIBRARY_PATH
```

**3. `.env` — set the host-side path (done by `setup-gpu-wsl.sh` automatically):**
```bash
WSL_LIB_PATH=/usr/lib/wsl/lib
```

### Verification
After the fix:
```bash
# Inside the container
docker exec -it py-captions ls /usr/lib/wsl/lib/libnvidia-encode.so.1
# Should show the file, not "no such file"

# Force a test job and watch the logs for:
# "GPU Encode: AVAILABLE" and "Stream #0: Video: h264_nvenc"
```

### Missteps to Avoid
- **Checking only `nvidia-smi` inside the container**: this succeeds because CUDA compute
  libraries ARE exposed. NVENC failing doesn't show up in `nvidia-smi`.
- **`ffmpeg -encoders | grep nvenc`**: this shows encoders compiled into ffmpeg, not whether
  the runtime library is available. NVENC can appear in `-encoders` and still fail at runtime.
  Always test with an actual encode: `ffmpeg -f lavfi -i color=c=black:s=16x16:r=1 -t 1 -c:v h264_nvenc -f null -`
- **Checking only `result.stdout` from `_query_ffmpeg_capabilities()`**: ffmpeg writes encoder
  availability info to stderr. The code was fixed (commit `7b1d04b`) to capture both
  `stdout + stderr`, but the real fix was the library mount.
- **Not pulling the new image after pushing the fix**: `docker compose up -d` reuses the
  old cached image. You must run `docker compose pull` first:
  ```bash
  docker compose pull
  docker compose down
  docker compose up -d
  ```
- **Not updating `.env` with `WSL_LIB_PATH`**: the compose mount uses `${WSL_LIB_PATH:-/tmp}`.
  If `WSL_LIB_PATH` is absent from `.env`, the compose file mounts `/tmp` which contains no
  NVIDIA libs. Add it manually if `setup-gpu-wsl.sh` wasn't re-run:
  ```bash
  echo 'WSL_LIB_PATH=/usr/lib/wsl/lib' >> ~/py-captions-for-channels/.env
  ```

---

## 6. Whisper uses GPU but ffmpeg encode is CPU — after NVENC fix

### Symptom
After deploying the NVENC fix (`WSL_LIB_PATH` set, new image pulled), a new job still shows
ffmpeg using CPU. Progress bar shows a very long ffmpeg stage, not the expected 5–8 minutes.

### Root Cause
One of two sub-causes (check in order):

**A) `.env` missing `WSL_LIB_PATH`.** The compose mount falls back to `/tmp`, which has no
NVIDIA libraries. The runtime test fails silently and the job uses CPU.

**B) Compose stack running from old image.** `docker compose up -d` was run before
`docker compose pull`. The old image is still in use.

Both produce the same symptom.

### Diagnosis & Fix
```bash
# 1. Check that WSL_LIB_PATH is in .env
grep WSL_LIB_PATH ~/py-captions-for-channels/.env

# 2. Check the library is visible inside the running container
docker exec -it py-captions ls /usr/lib/wsl/lib/ | grep nvenc

# 3. If the file is missing, check which image is running
docker inspect py-captions | grep Image

# 4. Pull latest and redeploy
cd ~/py-captions-for-channels
docker compose pull
docker compose down && docker compose up -d
```

### Missteps to Avoid
- **Running `docker compose up -d` without `docker compose pull` first** after pushing image fixes.
- **Running `docker compose` from the wrong directory** — see Issue #2.

---

## 7. Container starts but recording path is wrong inside container

### Symptom
Container is running, GPU works, but jobs fail with "file not found" when Whisper tries to
open the recording. Logs show paths like `/mnt/media/...` instead of `/mnt/channels/...`.

### Root Cause
The `.env` has the correct `DVR_MEDIA_DEVICE` but `DVR_PATH_PREFIX` / `LOCAL_PATH_PREFIX`
still reference the old path. The Channels DVR API returns recording paths with the old
prefix; the path-translation logic in `channels_api.py` fails to map them to the new mount.

### Fix
```bash
# Check current path settings
grep -E 'DVR_MEDIA_DEVICE|DVR_PATH_PREFIX|LOCAL_PATH_PREFIX' .env

# Fix with sed (example: /mnt/media → /mnt/channels)
sed -i 's|/mnt/media|/mnt/channels|g' ~/.env

# Restart container to pick up the change
cd ~/py-captions-for-channels
docker compose down && docker compose up -d
```

### Missteps to Avoid
- **Only fixing `DVR_MEDIA_DEVICE` and not `DVR_PATH_PREFIX`**: both must match.
- **Using the Setup Wizard on a re-install without first deleting the old volume**: the wizard
  may write the correct values but the stale volume still mounts the old path. Fix the volume first.

---

## 8. Job shows as active in System Monitor after cancellation

### Symptom
After clicking Cancel on a running job, the System Monitor tab continues to show the pipeline
progress bar frozen at the last stage (e.g., Whisper completed, ffmpeg shown as active).
The bar never clears on its own, or clears only after 30+ seconds.

### Root Cause
When a job is cancelled, the subprocess is killed (SIGTERM/SIGKILL). This kills the process
before it can call `stage_end()`, leaving `current_stage` populated in the `PipelineTimeline`
with no `ended_at`. The JS polling loop sees `active=True` forever because `active` is
derived from `current_stage is not None`.

The JS `updatePipelineStatus()` function had no cancellation detection path — it only cleared
when a terminal stage (`cleanup` or `replace_output`) was present, which cancelled jobs
never reach.

### Fix (commit `82b74d1`)

**`system_monitor.py`** — `job_cancel()` stamps the in-progress stage as ended and clears it:
```python
def job_cancel(self, job_id: str):
    with self.lock:
        self._load_state()
        if self.current_job_id == job_id:
            if self.current_stage and not self.current_stage.ended_at:
                self.current_stage.ended_at = time.time()
                self.completed_stages.append(self.current_stage)
            self.current_stage = None
            self._save_state()
```

**`web_app.py`** — `cancel_execution` endpoint calls `job_cancel()` immediately:
```python
ok = tracker.request_cancel(job_id)
get_pipeline_timeline().job_cancel(job_id)   # ← added
```

**`system_monitor.py`** — stale active stage auto-clear in `get_status()` (safety net for
timeouts and crashes that also kill the process without calling `stage_end`):
```python
if self.current_stage and not self.current_stage.ended_at:
    from .config import STALE_EXECUTION_SECONDS
    if time.time() - self.current_stage.started_at > STALE_EXECUTION_SECONDS:
        self.current_stage.ended_at = time.time()
        self.completed_stages.append(self.current_stage)
        self.current_stage = None
        self._save_state()
```

**`main.js`** — detect cancelled state and show a countdown message:
```javascript
const isCancelled = !pipeline.active && completedStages.length > 0 && !allCompleted;
if (isCancelled) {
    // show "✗ Cancelled" message, clear after COMPLETION_DISPLAY_DURATION seconds
}
```

---

## 9. Container sees empty `/mnt/channels` — bind-mount race at autostart

### Symptom
Container starts cleanly, GPU is up, logs report:
```
Recordings mount OK: /mnt/channels (0 entries visible)
```
Every job immediately fails with:
```
File not found or inaccessible: [Errno 2] No such file or directory: '/mnt/channels/TV/...
```
But `ls /mnt/channels` on the WSL host shows all folders (Database, TV, Movies, etc.).

### Root Cause
Docker bind mounts snapshot the host directory **at container start time**.
The `.bashrc` autostart sequence is:
1. Mount CIFS share at `/mnt/channels`
2. If container is not running → `docker compose up -d`

If step 2 races ahead of step 1 (e.g. Docker was already running from a previous session,
or a new WSL shell triggered the autostart block before the `mountpoint -q` check
returned), the container launches while `/mnt/channels` is still an empty directory.
Docker captures that empty state into the bind mount and the running container never
sees the files even after the CIFS share mounts successfully.

This is distinct from Issue #1 (volume driver errors) — here the container starts fine
and reports the mount path as OK, because the directory exists. It's just empty.

### Fix
Once you confirm the CIFS share is mounted on the host (`mount | grep cifs`), a
restart propagates the current state into the container's bind mount:
```bash
# Confirm share is up on the host
mount | grep cifs
ls /mnt/channels   # should show TV, Movies, etc.

# Restart (does NOT recreate the container — just remounts)
cd ~/py-captions-for-channels
docker compose restart

# Verify container now sees files
docker exec -it py-captions-for-channels ls /mnt/channels
```
No `down`/`up` cycle needed — `restart` is sufficient and preserves container state.

### Missteps to Avoid
- **`docker compose down && up`** instead of `restart` — works but is heavier than
  necessary and will re-run the startup NVML/GPU checks.
- **Checking container logs for a mount error** — there is none. The container
  reports the path as accessible (it is — it's just empty). The only clue is
  `(0 entries visible)` in the startup log and the repeated file-not-found warnings.
- **Re-running the setup script** — unnecessary for this specific problem. The CIFS
  credentials and `.bashrc` injection are fine. The only issue is timing.
- **Assuming the issue is path translation** (`DVR_PATH_PREFIX`/`LOCAL_PATH_PREFIX`) —
  those would cause wrong-path errors, not file-not-found on the correct path.
  If the path in the error matches what you expect, it's the empty-mount race.
- **"The setup script already handles this"** — The setup script's check-and-restart
  runs once, during initial setup. It does not protect against subsequent starts.
  The `.bashrc` autostart block originally used `if ! container running → up -d`,
  which skips a restart if the container is already up with a stale mount. This was
  fixed (see `scripts/setup-gpu-wsl.sh`): the autostart now also checks whether the
  mount is visible *inside* the running container, and does `docker compose restart`
  if the directory is empty.

---

## 10. General WSL Docker Diagnostics Cheat Sheet

### Is Docker running in WSL?
```bash
sudo service docker status
# If stopped: sudo service docker start
```

### Is the NAS share mounted?
```bash
mount | grep cifs
# If empty: sudo mkdir -p /mnt/channels && sudo mount -t cifs ...
```

### Is the volume stale?
```bash
docker volume inspect py-captions-for-channels_channels_media
# Check "Options" → "device" value matches current DVR_MEDIA_DEVICE
```

### Is the library visible inside the container?
```bash
docker exec -it py-captions-for-channels ls /usr/lib/wsl/lib/ | grep nvidia
# Should show: libcuda.so, libnvidia-encode.so.1, etc.
```

### Does NVENC actually work at runtime?
```bash
docker exec -it py-captions-for-channels ffmpeg \
  -f lavfi -i color=c=black:s=16x16:r=1 -t 1 \
  -c:v h264_nvenc -f null - 2>&1 | grep -E "nvenc|error|h264"
# Correct output includes: "Stream #0:0: Video: h264_nvenc"
# Failure output includes:  "Conversion failed!" or "No NVENC capable devices found"
```

### Is `.env` a file or a directory?
```bash
ls -la ~/py-captions-for-channels/.env
# Must be a file (-rw-r--r--), not a directory (drwx...)
```

### Which WSL_LIB_PATH is being used?
```bash
grep WSL_LIB_PATH ~/py-captions-for-channels/.env
docker exec -it py-captions-for-channels printenv LD_LIBRARY_PATH
```

### Full re-deploy from scratch (safe order of operations)
```bash
cd ~/py-captions-for-channels          # 1. cd first — always
docker compose down                     # 2. stop stack
docker volume rm py-captions-for-channels_channels_media 2>/dev/null || true
                                        # 3. remove stale volume
sudo mkdir -p /mnt/channels             # 4. ensure mount point exists
# (re-mount NAS share if needed)
docker compose pull                     # 5. pull latest image
docker compose up -d                    # 6. start with fresh volume
docker compose logs -f                  # 7. watch for errors
```

---

*Last updated: March 2026 — covers WSL2 Ubuntu 22.04, Docker Engine 24+, NVIDIA driver 550, Container Toolkit 1.17.*
