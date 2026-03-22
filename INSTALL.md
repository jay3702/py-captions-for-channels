# Installation Guide

Two installation tracks are available:

- **[Quick Install](#quick-install)** — run a single command on your server; the script handles everything interactively.
- **[Manual Install](#manual-install)** — clone the repo and configure by hand; suitable for troubleshooting, customization, or understanding how the system works.

Both tracks end at the same place: a running Docker container with a web dashboard at `http://YOUR_SERVER:8000`.

---

## Quick Install

### Linux

Run this on your server (Ubuntu, Debian, Fedora, RHEL/Rocky/Alma, or openSUSE). No prerequisites needed beyond `curl` and `sudo` access:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main/scripts/setup-linux.sh)
```

The script guides you through a TUI (whiptail) wizard and then runs unattended. It installs:
- Docker Engine
- NVIDIA Container Toolkit (if NVIDIA GPU detected)
- The pre-built Docker image
- Systemd service for auto-start

**The wizard will ask for:**
1. Deploy directory (default: `~/py-captions-for-channels`)
2. Channels DVR URL (`http://YOUR_DVR_IP:8089`)
3. Whether recordings live on a NAS — then server/share/mount details if so

Re-running is safe — all steps are idempotent.

---

### Windows

Run this in an **Administrator** PowerShell window. No prerequisites needed (not even Git):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
irm https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main/setup-windows.ps1 | iex
```

The script downloads the required installer files, then runs `setup-wsl.ps1`, which:
- Runs pre-flight checks (virtualization, disk space, port conflicts, Docker Desktop detection)
- Installs WSL2 + Ubuntu 22.04 (if not present) — you'll be prompted to create a Linux username and password
- Installs Docker Engine + NVIDIA Container Toolkit inside WSL2 (if NVIDIA GPU detected)
- Mounts the NAS share (if any)
- Deploys the container and configures auto-start on Windows login

**The wizard will ask for:**
1. Channels DVR URL
2. Whether recordings are on a NAS — then server/share/mount details if so
3. Auto-start mode (Boot or Logon)

> **Already using Docker Desktop?** The installer detects this and warns you. For full NVIDIA GPU acceleration (Whisper CUDA + ffmpeg NVENC), disable WSL integration for Ubuntu in Docker Desktop (*Settings → Resources → WSL Integration*) before running the installer, then re-run. Using Docker Desktop is supported for CPU-only or Whisper-CUDA-only setups — the installer will ask you to confirm.

> **Ubuntu-24.04:** `irm .../setup-windows.ps1 | iex` uses the default Ubuntu-22.04. To use 24.04, download the file first:
> ```powershell
> Invoke-WebRequest -Uri https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main/setup-windows.ps1 -OutFile setup-windows.ps1
> .\setup-windows.ps1 -Distro Ubuntu-24.04
> ```

---

### After Install — Both Platforms

1. **Open the dashboard** at `http://YOUR_SERVER_IP:8000` (Windows: `http://localhost:8000`)
2. **Setup Wizard** — click the ⚙ gear icon → **Setup Wizard** to verify the recordings mount. The wizard connects to your DVR, auto-detects the media folder path, and writes the Docker volume configuration.
3. **Whitelist shows** — go to **Recordings**, browse completed recordings from your DVR, and check the box next to each show you want captioned. Without a whitelist, nothing is processed.
4. **Test** — click **Manual Process** on one short recording. With `DRY_RUN=true` the pipeline logs what it would do without touching files. Review the result in **History**.
5. **Go live** — edit `.env` and set `DRY_RUN=false`, then restart:
   ```bash
   docker compose down && docker compose up -d
   ```
   From the web dashboard you can also update settings under ⚙ **Settings** and restart from there.

---

## Manual Install

### Prerequisites

- **Docker** (with compose plugin v2):
  ```bash
  # Linux quick-install
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER
  newgrp docker
  ```
  Windows: follow the [Quick Install](#windows) path above (installs Docker Engine inside WSL2), or use Docker Desktop.

- **NVIDIA Container Toolkit** (GPU hosts only):
  ```bash
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  ```
  Driver requirement: NVIDIA driver ≥ 520 (CUDA 12.2+). Verify with `nvidia-smi`.

---

### 1. Clone and Configure

```bash
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels
```

Copy the starter `.env` for your hardware:

```bash
cp .env.example.nvidia .env   # NVIDIA GPU
cp .env.example.cpu    .env   # CPU-only
cp .env.example.intel  .env   # Intel GPU
cp .env.example.amd    .env   # AMD GPU
```

Open `.env` and set at minimum:

```dotenv
CHANNELS_DVR_URL=http://YOUR_DVR_IP:8089
DRY_RUN=true    # set to false once verified
```

The full reference for every available option is in [.env.example](.env.example).

---

### 2. Start the Container

```bash
docker compose pull        # download the pre-built image (~5.5 GB, one-time)
docker compose up -d
docker compose logs -f     # watch startup
```

Open the dashboard at `http://YOUR_HOST_IP:8000` and follow the [post-install steps](#after-install--both-platforms) above.

---

### Recordings Path

The trickiest configuration is telling the container where to find your DVR recordings. The **Setup Wizard** handles this automatically. If you prefer to configure by hand:

**Same-host deployment** (DVR and container on the same machine): bind-mount the recordings directory:

```dotenv
DVR_MEDIA_TYPE=none
DVR_MEDIA_DEVICE=/path/to/recordings
DVR_MEDIA_MOUNT=/recordings
DVR_PATH_PREFIX=
LOCAL_PATH_PREFIX=/recordings
```

**Remote deployment** (recordings on a NAS or separate machine — SMB example):

```dotenv
DVR_MEDIA_TYPE=cifs
DVR_MEDIA_DEVICE=//NAS_IP/ShareName
DVR_MEDIA_OPTS=username=USER,password=PASS,uid=1000,gid=1000,file_mode=0755,dir_mode=0755
DVR_MEDIA_MOUNT=/recordings
DVR_PATH_PREFIX=/tank/AllMedia/Channels   # path as the DVR API reports it
LOCAL_PATH_PREFIX=/recordings
```

`DVR_PATH_PREFIX` and `LOCAL_PATH_PREFIX` together translate API-returned paths to the container's mount point so file I/O resolves correctly.

---

### Updating

```bash
cd ~/py-captions-for-channels
git pull
docker compose pull
docker compose down && docker compose up -d
```

Or from the web dashboard: ⚙ **Settings → Check for Updates**.

---

### Uninstall

```bash
docker compose down
docker rmi ghcr.io/jay3702/py-captions-for-channels:latest
sudo umount /mnt/channels    # if a NAS was mounted
rm -rf ~/py-captions-for-channels
```

Windows: run `teardown-wsl.sh` from inside WSL2:
```bash
bash /mnt/c/path/to/py-captions-for-channels/scripts/teardown-wsl.sh --all
```

---

## Troubleshooting

### Container won't start

```bash
docker compose logs
docker compose config   # validate .env substitution
```

Most common causes: missing `.env`, `CHANNELS_DVR_URL` still set to the placeholder, or the recordings mount path doesn't exist.

### Can't see recordings inside container

```bash
docker exec -it py-captions-for-channels ls -la /recordings
```

Verify `DVR_MEDIA_DEVICE` points to the correct host path and `DVR_MEDIA_MOUNT` matches what paths look like inside the container.

### GPU not working — `h264_nvenc=NOT FOUND`

1. Confirm `.env` has `DOCKER_RUNTIME=nvidia` and `NVIDIA_VISIBLE_DEVICES=all`
2. Confirm the runtime is registered:
   ```bash
   docker info | grep -i runtime   # should include: nvidia
   ```
3. If missing, re-register and restart:
   ```bash
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker   # Linux
   sudo service docker restart     # WSL2
   ```
4. Test NVENC directly:
   ```bash
   docker exec -it py-captions-for-channels \
     ffmpeg -f lavfi -i color=c=black:s=320x240:d=0 -frames:v 1 -c:v h264_nvenc -f null - 2>&1
   ```
   - `Cannot load libnvidia-encode.so.1` → nvidia runtime not active for this container
   - `No NVENC capable devices found` → GPU doesn't support NVENC

### NVIDIA runtime not found after Docker Desktop was previously installed

Docker Desktop leaves stubs that shadow the real binaries:

```bash
sudo rm -f /usr/local/lib/docker/cli-plugins/docker-compose
sudo rm -f /usr/local/lib/docker/cli-plugins/docker-buildx
sudo ln -sf /usr/libexec/docker/cli-plugins/docker-compose \
  /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
```

### NAS mount not visible in container (WSL2)

```bash
mountpoint /mnt/channels && ls /mnt/channels
cat /proc/mounts | grep channels   # shared propagation required

# Re-apply if missing
sudo mount --make-shared /mnt/channels
docker compose down && docker compose up -d
```

### `mount error(13): Permission denied` (CIFS)

```bash
sudo cat /etc/cifs-credentials-py-captions   # confirm username= and password= are correct
```

### Web dashboard not accessible from Windows (`http://localhost:8000`)

WSL2 auto-forwards ports. If localhost doesn't work:

```bash
# Get WSL2 IP
ip addr show eth0 | grep "inet "
# Browse to http://WSL2_IP:8000
```

### WSL-specific issues

See [docs/WSL_DOCKER_TROUBLESHOOTING.md](docs/WSL_DOCKER_TROUBLESHOOTING.md) for the full field guide: volume mount failures, NVENC loading issues, the bogus `.env`-as-directory trap, and more.

---

## Developer Setup

```bash
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# Pre-commit hooks (runs Black + flake8 on commit)
./setup-hooks.sh                 # Linux/macOS
# or
./setup-hooks.ps1                # Windows

pytest                           # run all tests
python -m py_captions_for_channels   # run watcher locally (reads .env)
```

**Building the Docker image locally** (instead of using the pre-built image from GHCR):

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
```

See [docs/DEV_QUICKSTART.md](docs/DEV_QUICKSTART.md) for VS Code setup, Copilot configuration, and the full development workflow. To customize the system for your own needs, fork the repository on GitHub — all configuration is in `.env` and the source is clean Python.
