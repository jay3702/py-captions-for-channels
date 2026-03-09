# Windows Setup Guide

> This guide covers Windows-specific steps and gotchas. For the general setup flow see [SETUP.md](SETUP.md).

> **All commands in this guide are for [PowerShell](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-windows).** Windows 10/11 ships with PowerShell 5.1 (`powershell.exe`), but PowerShell 7+ is recommended.
>
> **Install PowerShell 7** — use whichever option works for you:
>
> | Option | Command / Link |
> |--------|---------------|
> | winget (Windows 11 / Win 10 21H2+) | `winget install Microsoft.PowerShell` |
> | Microsoft Store | Search **"PowerShell"** and install from Microsoft |
> | Direct download (.msi) | [github.com/PowerShell/PowerShell/releases](https://github.com/PowerShell/PowerShell/releases) |
>
> **Don't have winget?** Install the **App Installer** from the [Microsoft Store](https://apps.microsoft.com/detail/9nblggh4nns1) to get it, or use one of the other options above.
>
> Once installed, launch **PowerShell 7** by searching "pwsh" in the Start menu (not the older "Windows PowerShell").

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1 — Install and Start Docker Desktop](#step-1--install-and-start-docker-desktop)
- [Step 2 — Clone the Repository](#step-2--clone-the-repository)
- [Step 2a — Verify DVR Network Share Access (remote DVR only)](#step-2a--verify-dvr-network-share-access-remote-dvr-only)
- [Step 3 — Configure .env](#step-3--configure-env)
- [Step 4 — GPU Setup (NVIDIA)](#step-4--gpu-setup-nvidia)
- [Step 5 — Pre-deploy Verification](#step-5--pre-deploy-verification)
- [Step 6 — Deploy](#step-6--deploy)
- [Step 7 — Post-deploy: Recordings and GPU Check](#step-7--post-deploy-recordings-and-gpu-check)
- [Path Syntax Rules](#path-syntax-rules)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Windows 10 version 2004 or later** (required for WSL2)
- **[Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)** — uses the WSL2 backend
- **WSL2** — installed automatically by Docker Desktop; or install manually:
  ```powershell
  wsl --install
  ```
- Git for Windows (comes with Git Bash, or use [winget](https://winget.run/)):
  ```powershell
  winget install Git.Git
  ```

---

## Step 1 — Install and Start Docker Desktop

1. Download and install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. During setup, choose **WSL2** as the backend (default on modern Windows)
3. After installation, **start Docker Desktop from the Start menu or taskbar**

> **The most common error:** Running `docker compose` before Docker Desktop has finished starting gives:
> ```
> open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
> ```
> **Fix:** Wait for the Docker Desktop whale icon in the taskbar notification area to stop animating, then try again.

Verify Docker is running:
```powershell
docker version
```

---

## Step 2 — Clone the Repository

```powershell
cd $env:USERPROFILE\Documents   # or wherever you want it
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels
```

---

## Step 2a — Verify DVR Network Share Access (remote DVR only)

> Skip this if Channels DVR is running on the same Windows machine.

If your Channels DVR is on a NAS, Linux server, or another Windows machine, confirm Windows can reach the share before you configure Docker. The Setup Wizard handles all path formatting — you just need the server name (or IP) and the share name.

### Find the share name

If you're not sure what shares exist on the DVR server, list them:

```powershell
net view \\YOUR_DVR_SERVER
```

Look for the share that points to your Channels DVR recordings folder. Note the exact share name — it could be anything (e.g. `Channels`, `DVR`, `media`, `recordings`).

**No share yet?** You'll need to create one on the server that exposes the Channels DVR recordings folder before continuing. How to do this depends on the server OS (Windows: File Explorer → right-click folder → Properties → Sharing; NAS: check your NAS admin UI; Linux: configure Samba).

### Verify access

```powershell
# Use the share name you found above
Get-ChildItem "\\YOUR_DVR_SERVER\YOUR_SHARE_NAME"
```

You should see the DVR's `TV` and `Movies` (or similar) folders. If access is denied or the path is not found, resolve the share permissions before continuing.

> **What the wizard needs:** When the Setup Wizard runs, it will ask for the server address and share name separately — e.g. `YOUR_DVR_SERVER` and `Channels`. You do not need to type UNC paths or backslashes manually.

---

## Step 3 — Configure .env

Choose the starter file that matches your hardware:

```powershell
# CPU-only (no GPU):
copy .env.example.cpu .env

# NVIDIA GPU:
copy .env.example.nvidia .env

# Intel GPU:
copy .env.example.intel .env

# AMD GPU:
copy .env.example.amd .env
```

Open it with Notepad or VS Code:
```powershell
notepad .env
# or:
code .env
```

Set `CHANNELS_DVR_URL` to your DVR's IP address — that's the only required change to get started. Leave `DRY_RUN=true` until you've verified the setup.

> **Leave the recordings volume settings for Step 7** — the Setup Wizard runs from the web dashboard after the container is started.

---

## Step 4 — GPU Setup (NVIDIA)

On Windows, Docker Desktop with the WSL2 backend passes NVIDIA GPUs through automatically — no Container Toolkit installation is required (unlike Linux).

### Requirements

- NVIDIA driver **≥ 520** — download from [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx)  
  Check the current version: `nvidia-smi` — look for "CUDA Version" ≥ 12.2
- Docker Desktop using the **WSL2 backend** (default)

### Enable GPU in .env

Your `.env.example.nvidia` starter already includes these; confirm they are present:

```dotenv
DOCKER_RUNTIME=nvidia
NVIDIA_VISIBLE_DEVICES=all
```

> GPU passthrough inside the container is verified in Step 7, after the container is running.

---

## Step 5 — Pre-deploy Verification

Before pulling the image, confirm everything is in order:

### 1. Docker is running
```powershell
docker version
```
You should see both Client and Server versions. If you get a pipe error, Docker Desktop is not running — start it and wait for the whale icon to stop animating.

### 2. GPU is visible on the host (NVIDIA only)
```powershell
nvidia-smi
```
The CUDA Version is in the **top-right corner of the first header row** — easy to miss:
```
+----------------------------------------------------------+
| NVIDIA-SMI 581.95   Driver Version: 581.95   CUDA Version: 13.0  |
```
Confirm the **CUDA Version** shown is **12.2 or higher**. If it's lower, GPU acceleration will fall back to CPU and the container logs a warning at startup.

### 3. Validate your .env
```powershell
docker compose config
```
This resolves all `${VAR}` substitutions and prints the final compose configuration. Look for obvious issues:
- `CHANNELS_DVR_URL` should not be `http://<CHANNELS_DVR_SERVER>:8089` (the placeholder)
- `DOCKER_RUNTIME` should show `nvidia` if you're using GPU
- No lines like `image: ` with an empty value

If any substitution looks wrong, edit `.env` and re-run `docker compose config` before proceeding.

---

## Step 6 — Deploy

```powershell
docker compose pull        # download the prebuilt image (~5.5 GB, one-time)
docker compose up -d       # start the container
docker compose logs -f     # watch startup logs (Ctrl+C to exit)
```

The startup log should end with something like:
```
INFO  Watcher started
INFO  Web UI listening on 0.0.0.0:8000
```
If it exits immediately instead, see Troubleshooting below.

---

## Step 7 — Post-deploy: Recordings and GPU Check

### Verify GPU passthrough (NVIDIA only)

With the container running:
```powershell
docker exec -it py-captions-for-channels nvidia-smi
```
You should see your GPU listed. If not, check that `DOCKER_RUNTIME=nvidia` and `NVIDIA_VISIBLE_DEVICES=all` are in `.env` and that your driver version is ≥ 520.

### Connect your DVR recordings via Setup Wizard

Open the web dashboard:
```
http://localhost:8000
```

Navigate to: **⚙ gear icon → Setup Wizard**

The wizard auto-detects your DVR's media folder and generates the correct Docker volume settings for your deployment type.

**Channels DVR running on the same Windows machine:**  
Choose *Same Host*. Docker Desktop on Windows mounts Windows paths into WSL2 containers automatically — the wizard handles the translation.

**Channels DVR on a different machine (NAS, Linux server, etc.):**  
Choose *Remote* and provide the SMB share address. Example values it will generate:

```dotenv
DVR_MEDIA_TYPE=cifs
DVR_MEDIA_DEVICE=//192.168.1.100/Channels
DVR_MEDIA_OPTS=addr=192.168.1.100,username=,password=,uid=0,gid=0,vers=3.0
DVR_MEDIA_MOUNT=/mnt/channels
DVR_PATH_PREFIX=D:/DVR/Channels    ← the path the Windows DVR server reports (use forward slashes)
LOCAL_PATH_PREFIX=/mnt/channels
```

### Whitelist shows and go live

In the dashboard, go to **Recordings**, check the shows you want captioned, then:

```powershell
# Edit .env: set DRY_RUN=false
notepad .env

# Restart to apply
docker compose down
docker compose up -d
```

New recordings that match your whitelist will now be processed automatically.

---

## Path Syntax Rules

> **Always use forward slashes in `.env` — even on Windows.**

| Context | Correct | Wrong |
|---------|---------|-------|
| `.env` values | `DVR_MEDIA_DEVICE=//192.168.1.100/share` | `\\192.168.1.100\share` |
| `.env` values | `DVR_MEDIA_MOUNT=/mnt/channels` | `C:\mnt\channels` |
| `.env` comment describing a Windows DVR path | `D:/DVR` | `D:\DVR` |

Docker and the Python code inside the container run on Linux (via WSL2). Backslashes in `.env` cause silent failures. Forward slashes work everywhere.

---

## Troubleshooting

### "The system cannot find the file specified" / pipe error

Docker Desktop is not running. Start it from the Start menu or taskbar and wait for the whale icon to stop animating.

### `docker compose up` starts but container exits immediately

Check the logs:
```powershell
docker compose logs
```
The most common causes are a missing or malformed `.env`, or a volume mount path that doesn't exist.

### Cannot reach http://localhost:8000

Check that the container is running:
```powershell
docker compose ps
```
If it shows "Exited", check the logs above. If running, confirm Windows Firewall isn't blocking port 8000.

### GPU not detected / falling back to CPU

- Confirm NVIDIA driver ≥ 520: run `nvidia-smi` in PowerShell
- Confirm Docker Desktop uses WSL2 backend: **Settings → General → Use the WSL2 based engine**
- Confirm `.env` has `DOCKER_RUNTIME=nvidia` and `NVIDIA_VISIBLE_DEVICES=all`
- After making changes, restart: `docker compose down && docker compose up -d`

### Recordings not found inside container

- In the web dashboard run the Setup Wizard again
- Make sure all `.env` paths use forward slashes
- Check the container can reach the share: `docker exec -it py-captions-for-channels ls /mnt/channels`

### SMB share needs credentials

Add your username and password to `DVR_MEDIA_OPTS`:
```dotenv
DVR_MEDIA_OPTS=addr=192.168.1.100,username=myuser,password=mypassword,uid=0,gid=0,vers=3.0
```
