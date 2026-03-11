# Windows Setup Guide

This guide uses **WSL2 + Docker Engine** — the only Windows Docker configuration that supports full NVIDIA GPU acceleration (Whisper CUDA + ffmpeg NVENC). Docker Desktop is not supported for this project.

> **Why not Docker Desktop?** Docker Desktop cannot expose the NVIDIA encoding runtime (`libnvidia-encode`) to containers, so ffmpeg NVENC never works. It also requires a paid commercial license for organisations ≥ 250 employees. Docker Engine inside WSL2 has none of these limitations and works identically for CPU-only setups too.

> **No GPU?** The same script works for CPU-only captioning. Just skip the NVIDIA driver check — the `setup-gpu-wsl.ps1` handles it gracefully.

> **All commands in this guide are for [PowerShell](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-windows).** PowerShell 7+ is recommended.
>
> **Install PowerShell 7:**
>
> | Option | Command / Link |
> |--------|---------------|
> | winget (Windows 11 / Win 10 21H2+) | `winget install Microsoft.PowerShell` |
> | Microsoft Store | Search **"PowerShell"** |
> | Direct download | [github.com/PowerShell/PowerShell/releases](https://github.com/PowerShell/PowerShell/releases) |
>
> Launch **PowerShell 7** by searching "pwsh" in the Start menu.

---

## Table of Contents

- [Requirements](#requirements)
- [Quick Install](#quick-install)
- [After the Script Completes](#after-the-script-completes)
- [Auto-Start on Windows Login](#auto-start-on-windows-login)
- [Updating](#updating)
- [Teardown / Uninstall](#teardown--uninstall)
- [Troubleshooting](#troubleshooting)
- [Manual Setup Reference](#manual-setup-reference)

---

## Requirements

- **Windows 10 version 2004 or later**, or **Windows 11**
- **NVIDIA GPU driver ≥ 520** — download from [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx)
  - Check with `nvidia-smi` in PowerShell — the `CUDA Version` in the header must be **12.2 or higher**
  - CPU-only users: no GPU requirement
- **Git for Windows:**
  ```powershell
  winget install Git.Git
  ```

---

## Quick Install

A single script handles everything — WSL2, Ubuntu, Docker Engine, NVIDIA Container Toolkit, NAS mount, repo clone, `.env` configuration, and container launch:

```powershell
# In PowerShell — clone anywhere on Windows, just to get the scripts
cd $env:USERPROFILE\Documents
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup-gpu-wsl.ps1
```

**The script will prompt for:**
1. Deploy directory inside WSL2 (default: `~/py-captions-for-channels`)
2. Channels DVR URL (`http://YOUR_DVR_IP:8089`)
3. Whether recordings are on a NAS or local — then server/share/mount if NAS
4. NAS credentials (prompted at mount time, with retry on auth failure)

**Then it runs unattended:**
- Installs WSL2 + Ubuntu 22.04 (if not present)
- Installs Docker Engine + NVIDIA Container Toolkit inside WSL2
- Mounts the NAS share with the correct propagation settings for Docker
- Clones the repo inside WSL2 and configures `.env`
- Adds a `~/.bashrc` auto-start block (Docker + NAS mount + container)
- Pulls the image and starts the container

> **Re-running is safe** — all steps are idempotent. If something fails midway, fix the issue and re-run.

> **Ubuntu-24.04:** To use Ubuntu 24.04 instead of 22.04:
> ```powershell
> .\scripts\setup-gpu-wsl.ps1 -Distro Ubuntu-24.04
> ```

---

## After the Script Completes

Open the dashboard from Windows: **http://localhost:8000**

### Confirm GPU is active (NVIDIA only)

In WSL2:
```bash
cd ~/py-captions-for-channels
docker compose logs | grep -E "NVENC|GPU backend"
```
Expected:
```
INFO  NVENC detection: h264_nvenc=found, cuvid_decoders=[h264_cuvid, hevc_cuvid]
INFO  GPU backend: nvenc+cuvid (NVENC hardware encoding enabled)
```

### Verify recordings via Setup Wizard

Navigate to **⚙ gear icon → Setup Wizard** in the dashboard. The wizard auto-detects the DVR media folder and verifies the volume mount is working.

### Whitelist shows and go live

1. In the dashboard go to **Recordings** → check the shows you want captioned
2. Click **Manual Process** on a short recording to verify end-to-end
3. Set `DRY_RUN=false` in `.env` and restart:
   ```bash
   nano ~/py-captions-for-channels/.env   # set DRY_RUN=false
   cd ~/py-captions-for-channels && docker compose down && docker compose up -d
   ```

---

## Auto-Start on Windows Login

The setup script already adds a `~/.bashrc` block that starts Docker, mounts the NAS, and launches the container whenever a WSL2 terminal opens.

To start everything **automatically on Windows login** without opening a terminal:

1. Press `Win+R`, type `shell:startup`, press Enter
2. Right-click → **New → Shortcut**, target: `wsl.exe -d Ubuntu-22.04`
3. Name it "py-captions"

The session opens minimized, `~/.bashrc` runs, and everything comes up automatically.

---

## Updating

```bash
# In WSL2
cd ~/py-captions-for-channels
git pull
docker compose pull
docker compose down
docker compose up -d
```

---

## Teardown / Uninstall

A teardown script reverses everything the installer created:

```bash
# In WSL2
bash /mnt/c/Users/YOUR_USERNAME/Documents/py-captions-for-channels/scripts/teardown-wsl.sh

# Also remove the deploy directory and data:
bash .../teardown-wsl.sh --all
```

Or manually:
```bash
cd ~/py-captions-for-channels
docker compose down
docker rmi ghcr.io/jay3702/py-captions-for-channels:latest
sudo umount /mnt/channels    # if NAS was mounted
```

---

## Troubleshooting

### Script fails: "WSL2 not found" or Ubuntu install hangs

WSL2 may need a reboot after first install:
```powershell
wsl --install --no-distribution
# Reboot, then re-run setup-gpu-wsl.ps1
```

### GPU test fails: unknown or invalid runtime `nvidia`

The NVIDIA Container Toolkit runtime is not registered:
```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo service docker restart
docker info | grep -i runtime   # should show: nvidia runc
```

### NVENC not found / `h264_nvenc=NOT FOUND`

1. Confirm the container is using the nvidia runtime:
   ```bash
   docker inspect py-captions-for-channels | grep -i runtime
   ```
2. Confirm `.env` has `DOCKER_RUNTIME=nvidia` and `NVIDIA_VISIBLE_DEVICES=all`
3. Test manually:
   ```bash
   docker exec -it py-captions-for-channels \
     ffmpeg -f lavfi -i color=c=black:s=320x240:d=0 -frames:v 1 -c:v h264_nvenc -f null - 2>&1
   ```
   - `Cannot load libnvidia-encode.so.1` → nvidia runtime not active for the container
   - `No NVENC capable devices found` → GPU doesn't support NVENC (rare on GeForce ≥ GTX 700)

### NAS mount not visible in container

```bash
# Confirm mount and shared propagation
mountpoint /mnt/channels && ls /mnt/channels
cat /proc/mounts | grep channels   # should show: ... shared ...

# Re-apply propagation if missing, then restart container
sudo mount --make-shared /mnt/channels
docker compose down && docker compose up -d
```

### `mount error(13): Permission denied` (CIFS)

```bash
sudo cat /etc/cifs-credentials-py-captions   # confirm username= and password= are correct
```

### Container exits immediately on `docker compose up`

```bash
docker compose logs
```
Most common causes: missing `.env`, `CHANNELS_DVR_URL` still set to placeholder, or recordings mount path doesn't exist.

### Web dashboard not accessible from Windows (`http://localhost:8000`)

WSL2 auto-forwards ports to Windows. If localhost doesn't work:
```bash
ip addr show eth0 | grep "inet "   # get WSL2 IP
# Browse to http://WSL2_IP:8000
```

### `docker compose` not found after Docker Desktop was previously installed

Docker Desktop leaves stubs in `/usr/local/lib/docker/cli-plugins/` that shadow the real binaries:
```bash
sudo rm -f /usr/local/lib/docker/cli-plugins/docker-compose
sudo rm -f /usr/local/lib/docker/cli-plugins/docker-buildx
sudo ln -sf /usr/libexec/docker/cli-plugins/docker-compose \
  /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
```

---

### Container stops when the WSL terminal is closed

The setup script configures everything for background persistence. If you need to re-apply or repair it, run once from PowerShell:

```powershell
.\scripts\autostart.ps1
```

It will ask when to fire the startup task:

| Mode | When it fires | Password required? |
|------|--------------|-------------------|
| **Boot** (recommended) | At Windows startup AND at logon as fallback | Yes — stored encrypted by Windows |
| **Logon** | When you sign in to Windows | No |

Boot mode registers both triggers on the same task. If WSL starts successfully at boot, the logon trigger is silently skipped (`MultipleInstances = IgnoreNew`). If the boot trigger fails (e.g. user profile not yet loaded), logon fires as a guaranteed fallback.

**Why no dedicated service account?** WSL2 distros are registered per-user in the Windows registry. The startup task must run as your own account — it can't use a separate account that doesn't have the distro registered.  In Boot mode, your password is stored by Windows in LSA secrets (same mechanism used by all Windows services) and never transmitted anywhere.

**How it works — boot sequence:**

1. **Task Scheduler** fires `wsl.exe --exec dbus-launch true` (at boot or logon, depending on your choice)
2. **WSL boots** with systemd as PID 1 (`/etc/wsl.conf` → `[boot] systemd=true`)
3. **systemd** starts `docker.service` (enabled during setup)
4. **Docker** restarts the container automatically (`restart: unless-stopped`)
5. **`dbus-daemon`** (left running by `dbus-launch true`) keeps the WSL VM alive with no terminal open

No terminal is ever needed.

**Stopping and restarting manually:**

```powershell
# Stop everything (shuts down the WSL VM and all containers inside it)
wsl --shutdown

# Start everything back up (mimics what the startup task does)
wsl --distribution Ubuntu-22.04 --exec dbus-launch true
```

After `wsl --shutdown`, opening any WSL terminal will also bring Docker and the container back up via the `.bashrc` auto-start as a fallback.

---

## Manual Setup Reference

If you prefer to run the steps individually — for troubleshooting, partial reinstalls, or understanding what the script does — see [WINDOWS_SETUP_NVIDIA_GPU.md](WINDOWS_SETUP_NVIDIA_GPU.md) for the full manual procedure.
