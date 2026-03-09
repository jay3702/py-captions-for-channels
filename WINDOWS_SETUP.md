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

If your Channels DVR is on a NAS, Linux server, or another Windows machine, confirm Windows can reach the recordings folder before you configure Docker. The Setup Wizard handles all path formatting — you just need the server name (or IP) and the share name.

### Step 1 — Find the recordings path in Channels DVR

Open the Channels DVR web UI on the DVR server and go to **Settings → General**. The **DVR Storage** (or "Server Enabled") field shows the full path where recordings are stored — e.g. `/mnt/storage/dvr` or `D:\Channels`. This is the folder that must be accessible via network share from the Windows machine running this tool.

### Step 2 — Find or create the share

List existing shares on that server to find one that covers that path:

```powershell
net view \\YOUR_DVR_SERVER
```

The share name could be anything — `Channels`, `DVR`, `media`, `recordings`, etc. If none of the listed shares expose the recordings folder, you'll need to create one:

- **Windows DVR server:** File Explorer → right-click the recordings folder → Properties → Sharing
- **NAS:** check your NAS admin UI for the share covering that path
- **Linux (Samba):** add a share entry to `/etc/samba/smb.conf` pointing to the recordings directory

### Step 3 — Verify access from this machine

```powershell
# Use the share name you identified above
Get-ChildItem "\\YOUR_DVR_SERVER\YOUR_SHARE_NAME"
```

You should see the DVR's recording folders (e.g. `TV`, `Movies`). If access is denied or the path is not found, resolve the share permissions before continuing.

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

Set `CHANNELS_DVR_URL` to your DVR's IP address. Leave `DRY_RUN=true` until you've verified the setup.

### Configure the recordings volume

> **The recordings volume must be configured before the first deploy.** The Setup Wizard (Step 7) can update these settings later, but the container cannot start without a valid initial configuration.

Your `.env` file has two option blocks — **use Option A or Option B, not both.** Comment out the one you are not using.

**Option A — DVR is on this machine (same Windows PC running Docker):**

Open Channels DVR → **Settings → General** and note the DVR storage path. Fill it in as `DVR_MEDIA_DEVICE` using forward slashes:

```dotenv
DVR_MEDIA_TYPE=none
DVR_MEDIA_DEVICE=C:/path/to/your/Channels/DVR
DVR_MEDIA_OPTS=bind
DVR_MEDIA_MOUNT=/mnt/media
```

**Option B — DVR is on a different machine (NAS, Linux server, another Windows PC):**

Docker Desktop handles the share as a plain bind mount via `DVR_MEDIA_HOST_PATH`. The `DVR_MEDIA_TYPE`, `DVR_MEDIA_DEVICE`, and `DVR_MEDIA_OPTS` lines from Option A are not used here — leave them commented out.

**Step 1 — Store credentials in Windows Credential Manager (keeps passwords out of files)**

```powershell
cmdkey /add:YOUR_DVR_SERVER /user:USERNAME /pass:PASSWORD
```

Verify the share is accessible:

```powershell
Get-ChildItem \\YOUR_DVR_SERVER\YOUR_SHARE_NAME
```

**Step 1b (optional) — Map a persistent drive letter**

A drive letter is more reliable than a bare UNC path on Windows. Run once in PowerShell:

```powershell
net use Z: \\YOUR_DVR_SERVER\YOUR_SHARE_NAME /persistent:yes
```

Replace `Z:` with any free drive letter. If credentials are already stored (Step 1), no `/user:` needed. Verify: `Get-ChildItem Z:\`

**Step 2 — Comment out Option A and fill in Option B:**

With a mapped drive letter (Step 1b):

```dotenv
DVR_MEDIA_HOST_PATH=Z:/
DVR_MEDIA_MOUNT=/mnt/media
# DVR_PATH_PREFIX — leave unset; configure via the Setup Wizard (Step 7)
```

Or directly via UNC path (credentials must be in Credential Manager from Step 1):

```dotenv
DVR_MEDIA_HOST_PATH=//YOUR_DVR_SERVER/YOUR_SHARE_NAME
DVR_MEDIA_MOUNT=/mnt/media
# DVR_PATH_PREFIX — leave unset; configure via the Setup Wizard (Step 7)
```

> **Any slash style is accepted** — `\\server\share`, `//server/share` — the path is normalized automatically.

> **`LOCAL_PATH_PREFIX`** is set automatically from `DVR_MEDIA_MOUNT` — you do not need to include it in `.env`. It only needs to be set explicitly when using `DVR_PATH_PREFIX` for path translation (when the DVR server reports a different internal path from the mount point).

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

### Verify recordings access via Setup Wizard

Open the web dashboard:
```
http://localhost:8000
```

Navigate to: **⚙ gear icon → Setup Wizard**

The wizard auto-detects your DVR's media folder and verifies that the volume settings configured in Step 3 are working correctly. It can also regenerate the correct `DVR_MEDIA_*` values if you need to update them (e.g. the DVR server moved or the share changed). After the wizard writes updated values to `.env`, restart the container to apply them:

```powershell
docker compose down
docker compose up -d
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
| `.env` values | `DVR_MEDIA_HOST_PATH=Z:/` | `Z:\` |
| `.env` values | `DVR_MEDIA_DEVICE=//192.168.1.100/share` | `\\192.168.1.100\share` |
| `.env` values | `DVR_MEDIA_MOUNT=/mnt/channels` | `C:\mnt\channels` |
| `.env` comment describing a Windows DVR path | `D:/DVR` | `D:\DVR` |

Docker and the Python code inside the container run on Linux (via WSL2). Backslashes in `.env` cause silent failures. Forward slashes work everywhere.

---

## Troubleshooting

### "The system cannot find the file specified" / pipe error

Docker Desktop is not running. Start it from the Start menu or taskbar and wait for the whale icon to stop animating.

### Volume mount fails: `no such file or directory` / `failed to mount local volume`

```
Error response from daemon: failed to mount local volume: mount /mnt/media ... no such file or directory
```

The `DVR_MEDIA_*` variables in `.env` are not set (or are set to a path that doesn't exist). The container cannot start without a valid volume configuration — go back to **Step 3** and configure them before retrying `docker compose up -d`.

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

### SMB share: CIFS mount errors (`invalid argument`, `no such file or directory`)

The Docker Desktop CIFS named volume driver on Windows has unpredictable path-normalization behaviour and is not reliable. Use the `DVR_MEDIA_HOST_PATH` approach instead — see **Step 3** ("DVR on a different machine").
