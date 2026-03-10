# Windows NVIDIA GPU Setup — WSL2 Docker Engine

> **This guide is for NVIDIA GPU users who want full GPU acceleration** — Whisper inference AND ffmpeg NVENC hardware encoding. If you only need CPU captioning, the simpler [Docker Desktop path in WINDOWS_SETUP.md](WINDOWS_SETUP.md) works fine.

Docker Desktop on Windows does **not** expose NVIDIA NVENC encoding libraries to containers. NVENC requires the full NVIDIA Container Toolkit running inside WSL2 with the standard Linux Docker Engine. This guide walks through that setup end-to-end.

> **Already have Docker Desktop installed?** Uninstall it first — its leftover plugin stubs interfere with the Docker Engine installed in WSL2. See [If Docker Desktop was previously installed](#if-docker-desktop-was-previously-installed) before proceeding.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1 — Set Up WSL2 with Ubuntu](#step-1--set-up-wsl2-with-ubuntu)
- [Step 2 — Install Docker Engine in WSL2](#step-2--install-docker-engine-in-wsl2)
- [Step 3 — Install NVIDIA Container Toolkit](#step-3--install-nvidia-container-toolkit)
- [Step 4 — Configure NAS / Network Share](#step-4--configure-nas--network-share)
- [Step 5 — Clone and Configure the Repository](#step-5--clone-and-configure-the-repository)
- [Step 6 — Deploy](#step-6--deploy)
- [Step 7 — Verify GPU and Recordings](#step-7--verify-gpu-and-recordings)
- [Auto-Start on WSL2 Launch](#auto-start-on-wsl2-launch)
- [If Docker Desktop was previously installed](#if-docker-desktop-was-previously-installed)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Windows 10 version 2004 or later** (required for WSL2)
- **NVIDIA driver ≥ 520 on Windows** — download from [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx)
  - Check: open PowerShell and run `nvidia-smi`. Look for `CUDA Version: 12.x` or higher in the header row.
- **WSL2 enabled** — see Step 1
- **Docker Desktop uninstalled** (if previously installed) — see [cleanup steps](#if-docker-desktop-was-previously-installed)

> The NVIDIA driver only needs to be installed on Windows. You do **not** install NVIDIA drivers inside WSL2 — the Windows driver is shared with the WSL2 kernel.

---

## Step 1 — Set Up WSL2 with Ubuntu

Skip this step if you already have Ubuntu 22.04 (or 24.04) running in WSL2.

**On Windows (PowerShell):**
```powershell
# Enable WSL2 with Ubuntu (reboot if prompted)
wsl --install -d Ubuntu-22.04
```

After the reboot and Ubuntu first-run setup, confirm WSL2 is the version in use:
```powershell
wsl -l -v
```
The `VERSION` column should show `2` for your Ubuntu distro. If it shows `1`, upgrade it:
```powershell
wsl --set-version Ubuntu-22.04 2
```

**From this point on, all commands run inside WSL2** — open Ubuntu from the Start menu (search "Ubuntu") or run `wsl` in PowerShell.

---

## Step 2 — Install Docker Engine in WSL2

Run these commands inside your WSL2 Ubuntu terminal:

```bash
# Add Docker's official GPG key and repository
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

# Install Docker Engine and the compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

Add your user to the `docker` group so you don't need `sudo` for every Docker command:
```bash
sudo usermod -aG docker $USER
newgrp docker   # apply without logging out
```

Start the Docker daemon and enable it:
```bash
sudo service docker start
```

Verify:
```bash
docker version
docker compose version
```

### Fix the compose plugin symlink (if needed)

If `docker compose version` fails but `docker-compose version` works, the apt package installed the plugin to a path Docker Engine doesn't check. Fix it:

```bash
# Check if it's installed but in the wrong place
ls /usr/libexec/docker/cli-plugins/docker-compose

# If found, create the symlink Docker Engine expects:
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo ln -sf /usr/libexec/docker/cli-plugins/docker-compose \
  /usr/local/lib/docker/cli-plugins/docker-compose

docker compose version   # should work now
```

---

## Step 3 — Install NVIDIA Container Toolkit

The NVIDIA Container Toolkit injects the GPU libraries into containers at runtime — this is what enables both Whisper CUDA and ffmpeg NVENC inside Docker.

```bash
# Add the NVIDIA Container Toolkit repository
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Configure Docker to use the nvidia runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo service docker restart
```

Verify the `nvidia` runtime is registered:
```bash
docker info | grep -i runtime
# Should show: Runtimes: nvidia runc
```

Test GPU passthrough:
```bash
docker run --rm --runtime=nvidia --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```
You should see your GPU listed. If you get an error, see [Troubleshooting](#troubleshooting).

---

## Step 4 — Configure NAS / Network Share

> Skip this section if Channels DVR is on the **same machine** as this WSL2 instance. For local DVR, go straight to [Step 5](#step-5--clone-and-configure-the-repository).

If your Channels DVR and recordings are on a NAS or separate server, you need to mount that share inside WSL2 so Docker can bind-mount it into the container.

### Install CIFS utilities

```bash
sudo apt-get install -y cifs-utils
```

### Create a credentials file

Storing credentials in a file avoids special-character issues (e.g., `!` in passwords breaks bash history expansion):

```bash
sudo nano /etc/cifs-credentials
```

Add these two lines (replace with your actual username and password):
```
username=YOUR_NAS_USERNAME
password=YOUR_NAS_PASSWORD
```

Secure the file:
```bash
sudo chmod 600 /etc/cifs-credentials
```

### Create the mount point and mount the share

```bash
sudo mkdir -p /mnt/channels

# Mount the NAS share (replace with your server IP and share name)
sudo mount -t cifs //192.168.3.150/Channels /mnt/channels \
  -o credentials=/etc/cifs-credentials,uid=$(id -u),gid=$(id -g),iocharset=utf8

# Verify
ls /mnt/channels
```

You should see your DVR recordings folders (e.g. `TV`, `Movies`).

### Enable shared mount propagation for Docker

Docker bind mounts require the mount point to have shared propagation:

```bash
sudo mount --make-shared /mnt/channels
```

> **Important:** This `--make-shared` command must be run **after every mount** of `/mnt/channels`. Add it to your auto-start block in Step 8 so it runs automatically on WSL2 launch.

---

## Step 5 — Clone and Configure the Repository

Choose a deploy location inside WSL2. Using your Windows user profile (available via `/mnt/c/Users/`) makes it accessible from both Windows and WSL2:

```bash
cd /mnt/c/Users/$USER/Documents
git clone https://github.com/jay3702/py-captions-for-channels.git
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

> **`DVR_PATH_PREFIX`**: Only needed when the DVR server's recording paths (as returned by the API) don't match your local mount. For example, if the DVR stores at `/tank/AllMedia/Channels/TV/...` but you mount only the `Channels` subfolder, set `DVR_PATH_PREFIX=/tank/AllMedia/Channels`. Leave it unset if the paths match.

Validate the config:
```bash
docker compose config
```
Check that `CHANNELS_DVR_URL` is not the placeholder value and that `runtime` shows `nvidia`.

---

## Step 6 — Deploy

```bash
docker compose pull         # download the prebuilt image (~5.5 GB, one-time)
docker compose up -d        # start the container
docker compose logs -f      # watch startup (Ctrl+C to stop following)
```

Healthy startup log looks like:
```
INFO  Recordings mount OK: /mnt/channels (XX entries visible)
INFO  NVENC detection: h264_nvenc=found, cuvid_decoders=[h264_cuvid, ...]
INFO  GPU backend: nvenc+cuvid (NVENC hardware encoding enabled)
INFO  Watcher started
INFO  Web UI listening on 0.0.0.0:8000
```

If `NVENC detection` shows `h264_nvenc=NOT FOUND`, see [Troubleshooting](#troubleshooting).

Open the web dashboard from your Windows browser:
```
http://localhost:8000
```

---

## Step 7 — Verify GPU and Recordings

### Verify GPU passthrough

```bash
docker exec -it py-captions-for-channels nvidia-smi
```

You should see your GPU listed. If not, confirm `DOCKER_RUNTIME=nvidia` and `NVIDIA_VISIBLE_DEVICES=all` are set in `.env`.

### Verify recordings are visible

```bash
docker exec -it py-captions-for-channels ls /mnt/channels
```

Or use the web dashboard:
- Open **⚙ Settings → Setup Wizard**
- The wizard verifies the recordings mount and shows the entry count

### Test with a real recording

1. In the dashboard, go to **Recordings** and check one or two shows you want captioned
2. Click **Manual Process** and select a short recording
3. With `DRY_RUN=true`, review the **History** tab to confirm the pipeline ran without errors
4. When satisfied, set `DRY_RUN=false` in `.env` and restart:
   ```bash
   docker compose down && docker compose up -d
   ```

---

## Auto-Start on WSL2 Launch

WSL2 doesn't automatically run services (like `dockerd`, NAS mounts) on Windows startup. Add this block to `~/.bashrc` so everything comes up when you open a WSL2 terminal:

```bash
nano ~/.bashrc
```

Add at the end:
```bash
# ── py-captions auto-start ──────────────────────────────────────────
# Start Docker if not running
if ! pgrep -x dockerd > /dev/null; then
    sudo service docker start
fi

# Mount and share the NAS
if ! mountpoint -q /mnt/channels; then
    sudo mount -t cifs //192.168.3.150/Channels /mnt/channels \
        -o credentials=/etc/cifs-credentials,uid=$(id -u),gid=$(id -g),iocharset=utf8
fi
sudo mount --make-shared /mnt/channels

# Start the container if not already running
if ! docker ps --format '{{.Names}}' | grep -q py-captions-for-channels; then
    cd /mnt/c/Users/$USER/Documents/py-captions-for-channels
    docker compose up -d
fi
# ───────────────────────────────────────────────────────────────────
```

Update the `cd` path to match wherever you cloned the repo in Step 5.

The `sudo` commands (docker service, cifs mount) require passwordless sudo for these specific commands. Add to sudoers with `sudo visudo`:

```
# py-captions auto-start (add to bottom of sudoers)
%docker ALL=(ALL) NOPASSWD: /usr/sbin/service docker start
%docker ALL=(ALL) NOPASSWD: /sbin/mount.cifs
%docker ALL=(ALL) NOPASSWD: /bin/mount --make-shared /mnt/channels
```

> **Optional — Windows startup:** To have WSL2 open automatically on Windows login, create a Scheduled Task that runs `wsl -d Ubuntu-22.04` at log-on. The `.bashrc` block above will then execute and bring everything up automatically.

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
