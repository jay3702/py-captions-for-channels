# Windows NVIDIA GPU Setup — WSL2 Docker Engine

> **This guide is for NVIDIA GPU users who want full GPU acceleration** — Whisper inference AND ffmpeg NVENC hardware encoding. If you only need CPU captioning, the [Docker Desktop path in WINDOWS_SETUP.md](WINDOWS_SETUP.md) is simpler.

Docker Desktop on Windows does **not** expose NVIDIA NVENC encoding libraries to containers. Full GPU acceleration requires the NVIDIA Container Toolkit running inside WSL2 with the standard Linux Docker Engine.

---

## Quick Install (Recommended)

A single setup script handles everything:
- Installs Docker Engine + NVIDIA Container Toolkit in WSL2
- Mounts your NAS share with the right propagation settings for Docker
- Clones the repo, configures `.env`, sets up auto-start
- Pulls the image and starts the container

**Requirements before running:**
- NVIDIA driver **≥ 520** installed on Windows — check with `nvidia-smi` in PowerShell (look for `CUDA Version: 12.x` in the header)
- Windows 10 2004+ or Windows 11

### Option A — From PowerShell (Windows)

Handles WSL2 and Ubuntu setup automatically, then runs the bash installer inside WSL2:

```powershell
cd $env:USERPROFILE\Documents
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels

# If your DVR recordings are on a NAS:
.\scripts\setup-gpu-wsl.ps1

# If the DVR is on the same machine (no NAS):
.\scripts\setup-gpu-wsl.ps1 -LocalDvr
```

**What it prompts for:**
1. Deploy directory (default: `~/py-captions-for-channels` inside WSL2)
2. Channels DVR URL (`http://YOUR_DVR_IP:8089`)
3. NAS server address, share name, mount point, and credentials
4. DVR path prefix (only if DVR API paths need translation, e.g. `/tank/AllMedia/Channels`)

Everything else — Docker Engine, toolkit, sudoers, `.bashrc` auto-start, image pull — is automated.

### Option B — From WSL2 Ubuntu terminal

If you already have Ubuntu 22.04 or 24.04 in WSL2:

```bash
# One-liner (inside Ubuntu WSL2):
curl -fsSL https://raw.githubusercontent.com/jay3702/py-captions-for-channels/main/scripts/setup-gpu-wsl.sh | bash

# Or clone first and run locally:
git clone https://github.com/jay3702/py-captions-for-channels.git ~/py-captions-for-channels
bash ~/py-captions-for-channels/scripts/setup-gpu-wsl.sh
```

> **Re-running is safe** — all steps are idempotent. If something fails midway, fix the issue and re-run.

---

## After the Script Completes

Open the dashboard from your Windows browser: **http://localhost:8000**

### Confirm GPU is active
```bash
# In WSL2:
cd ~/py-captions-for-channels
docker compose logs | grep -E "NVENC|GPU backend"
```
Expected:
```
INFO  NVENC detection: h264_nvenc=found, cuvid_decoders=[h264_cuvid, hevc_cuvid]
INFO  GPU backend: nvenc+cuvid (NVENC hardware encoding enabled)
```

### Whitelist shows and go live
1. In the dashboard go to **Recordings** → check the shows you want captioned
2. Click **Manual Process** on a short recording to verify
3. Set `DRY_RUN=false` in `.env` and restart:
   ```bash
   nano ~/py-captions-for-channels/.env   # set DRY_RUN=false
   cd ~/py-captions-for-channels && docker compose down && docker compose up -d
   ```

---

## Auto-Start on Windows Login

The setup script adds a `~/.bashrc` block that starts Docker, mounts the NAS, and launches the container whenever a WSL2 terminal opens.

To start everything **automatically on Windows login** without opening a terminal:
1. Press `Win+R`, type `shell:startup`, press Enter
2. Right-click → **New → Shortcut**, target: `wsl.exe -d Ubuntu-22.04`
3. Name it "py-captions"

The session opens minimized, `~/.bashrc` runs, and everything comes up automatically.

---

## Manual Setup Reference

> The scripts above handle all of this. These steps are for troubleshooting, partial reinstalls, or understanding what the script does.

### WSL2 + Ubuntu

```powershell
# In PowerShell on Windows:
wsl --install -d Ubuntu-22.04
# After reboot, verify:
wsl -l -v   # VERSION column should show 2
```

### Install Docker Engine in WSL2

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
sudo service docker start
```

#### Fix compose plugin symlink (if `docker compose` not found)

```bash
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo ln -sf /usr/libexec/docker/cli-plugins/docker-compose \
  /usr/local/lib/docker/cli-plugins/docker-compose
```

### Install NVIDIA Container Toolkit

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

sudo nvidia-ctk runtime configure --runtime=docker
sudo service docker restart

# Verify
docker info | grep -i runtime   # should show: nvidia runc
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

### Mount NAS Share

```bash
sudo apt-get install -y cifs-utils

# Store credentials (avoids issues with special characters in passwords)
sudo bash -c 'printf "username=YOUR_USER\npassword=YOUR_PASS\n" > /etc/cifs-credentials'
sudo chmod 600 /etc/cifs-credentials

sudo mkdir -p /mnt/channels
sudo mount -t cifs //YOUR_NAS_IP/Channels /mnt/channels \
  -o credentials=/etc/cifs-credentials,uid=$(id -u),gid=$(id -g),iocharset=utf8

# Required for Docker bind mount visibility
sudo mount --make-shared /mnt/channels
```

### Configure .env

```bash
cp .env.example.nvidia .env
nano .env
```

Minimum settings:
```dotenv
CHANNELS_DVR_URL=http://YOUR_DVR_IP:8089
DOCKER_RUNTIME=nvidia
NVIDIA_VISIBLE_DEVICES=all
DVR_MEDIA_HOST_PATH=/mnt/channels
DVR_MEDIA_MOUNT=/mnt/channels
LOCAL_PATH_PREFIX=/mnt/channels
# DVR_PATH_PREFIX=/tank/AllMedia/Channels  # only if DVR API paths need translation
```

### Deploy

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```
cd py-captions-for-channels
```

Or use a pure WSL2 path (faster I/O, WSL2-only access):
```bash
mkdir -p ~/deploy
cd ~/deploy
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels
```

### Configure .env

Start from the NVIDIA GPU example:
```bash
cp .env.example.nvidia .env
nano .env
```

Minimum required settings:

```dotenv
# Your Channels DVR server address
CHANNELS_DVR_URL=http://192.168.3.X:8089

# GPU settings (already set in .env.example.nvidia)
DOCKER_RUNTIME=nvidia
NVIDIA_VISIBLE_DEVICES=all

# Recordings volume — path on WSL2 host and mount point inside container
DVR_MEDIA_HOST_PATH=/mnt/channels
DVR_MEDIA_MOUNT=/mnt/channels

# Path translation (if DVR reports a different path than your mount point)
# DVR_PATH_PREFIX=/tank/AllMedia/Channels   # what the DVR API returns
LOCAL_PATH_PREFIX=/mnt/channels             # your local mount point

# Keep dry-run on until you've verified everything
DRY_RUN=true
```

---

## If Docker Desktop was previously installed

Docker Desktop installs placeholder plugin stubs in `/usr/local/lib/docker/cli-plugins/` inside WSL2. After uninstalling Docker Desktop from Windows, these stubs remain and take precedence over the real plugins installed by the Docker Engine apt package.

Symptoms: `docker compose version` fails or produces errors even though `docker-compose-plugin` is installed.

**Fix:**
```bash
# Remove Desktop stubs
sudo rm -f /usr/local/lib/docker/cli-plugins/docker-compose
sudo rm -f /usr/local/lib/docker/cli-plugins/docker-buildx

# Symlink the real compose binary
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo ln -sf /usr/libexec/docker/cli-plugins/docker-compose \
  /usr/local/lib/docker/cli-plugins/docker-compose

# Verify
docker compose version
```

Also remove any containers or volumes that Docker Desktop was managing before starting fresh with the Docker Engine:
```bash
docker ps -a        # list any leftover containers
docker compose down # stop the stack from the project directory
```

---

## Troubleshooting

### `docker compose` not found / errors after Docker Desktop removal

See [If Docker Desktop was previously installed](#if-docker-desktop-was-previously-installed) above.

### GPU test fails: `docker: Error response from daemon: unknown or invalid runtime name: nvidia`

The NVIDIA Container Toolkit runtime is not registered with Docker:
```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo service docker restart
docker info | grep -i runtime   # should show: nvidia runc
```

### `pytorch not found` / Whisper falls back to CPU

The container logs `WARNING: torch not found, will use CPU` — this is expected if no GPU is available. If your GPU test works (`nvidia-smi` from inside container shows the GPU), Whisper should use it. Check:
```bash
docker compose logs | grep -i "whisper\|cuda\|pytorch\|device"
```

### NVENC not found / `h264_nvenc=NOT FOUND`

1. Confirm the runtime test is running — look for `NVENC detection:` in startup logs
2. Run the nvenc detection manually to see the ffmpeg error:
   ```bash
   docker exec -it py-captions-for-channels \
     ffmpeg -f lavfi -i color=c=black:s=320x240:d=0 -frames:v 1 -c:v h264_nvenc -f null - 2>&1
   ```
3. Common causes:
   - `Cannot load libnvidia-encode.so.1` — the `nvidia` runtime is not active for this container. Check `DOCKER_RUNTIME=nvidia` in `.env` and `docker info | grep -i runtime`
   - `No NVENC capable devices found` — your GPU doesn't support NVENC (rare; most GeForce GPUs ≥ GTX 700 do)

### NAS mount not visible in container

```bash
# Confirm mount exists on WSL2 host
mountpoint /mnt/channels && ls /mnt/channels

# Confirm shared propagation is set
cat /proc/mounts | grep channels
# Should show: ... shared ...

# Apply propagation if missing
sudo mount --make-shared /mnt/channels

# Then restart the container to re-apply the bind mount
docker compose down && docker compose up -d
```

### `mount error(13): Permission denied` when mounting CIFS

Verify the credentials file is correct and the share permissions allow the specified user:
```bash
cat /etc/cifs-credentials   # confirm username= and password= lines
sudo chmod 600 /etc/cifs-credentials
```

### Container exits immediately on `docker compose up`

```bash
docker compose logs
```
Most common causes: missing `.env` file, `CHANNELS_DVR_URL` still set to the placeholder, or the recordings mount path doesn't exist on the host.

### Web dashboard not accessible from Windows browser

The container binds to `0.0.0.0:8000` inside WSL2. WSL2 auto-forwards ports to Windows, so `http://localhost:8000` should work. If it doesn't:
```bash
# Confirm the container is running and port is bound
docker compose ps
docker port py-captions-for-channels

# Check WSL2's IP (use this if localhost doesn't work)
ip addr show eth0 | grep "inet "
# Then browse to http://WSL2_IP:8000
```

---

## Updating

```bash
cd /path/to/py-captions-for-channels

git pull                        # get latest compose/config
docker compose pull             # pull updated image
docker compose down
docker compose up -d
```

Persistent data in `HOST_DATA_DIR` (default `./data`) is preserved across updates.

## Teardown / Uninstall

```bash
cd /path/to/py-captions-for-channels

docker compose down             # stop and remove container
docker rmi ghcr.io/jay3702/py-captions-for-channels:latest   # remove image

# Optional: remove persistent data
rm -rf data/

# Optional: unmount NAS
sudo umount /mnt/channels
```
