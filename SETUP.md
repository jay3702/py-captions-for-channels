# Quick Setup Guide

Get up and running in three steps: configure, deploy, and whitelist your first shows.

---

## Prerequisites

- **Docker** installed on the host machine
  - Linux: `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER`
  - Windows/macOS: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **The repo** cloned locally (provides `docker-compose.yml` and `.env.example`):
  ```bash
  git clone https://github.com/jay3702/py-captions-for-channels.git
  cd py-captions-for-channels
  ```

> **Prebuilt image available:** The `docker-compose.yml` pulls the latest image automatically from
> `ghcr.io/jay3702/py-captions-for-channels:latest` — no local build required.

### GPU (optional but strongly recommended)

- **NVIDIA GPU** with 6 GB+ VRAM (GTX 1660 Super / RTX 2060 or newer)
- **NVIDIA driver ≥ 520** on the Docker host — this supports CUDA 12.2, which the container requires.
  Verify with `nvidia-smi`; the **"CUDA Version"** shown must be **12.2 or higher**.
  If it is lower, GPU acceleration silently falls back to CPU and a warning is logged at startup.
- **NVIDIA Container Toolkit** installed on the host:
  ```bash
  # Linux quick-install
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
  ```

> **CPU-only hosts** (no NVIDIA GPU) work fine — just skip the GPU steps. Jobs will be slower (~20 min/hr of TV instead of ~3 min with GPU).

---

## 1. Configure

```bash
cp .env.example .env
nano .env   # or vi, vim, etc.
```

### Minimum settings — CPU-only host

```bash
# Your Channels DVR server
CHANNELS_DVR_URL=http://YOUR_DVR_IP:8089

# Leave DRY_RUN=true until you've verified the setup
DRY_RUN=true
```

### Minimum settings — GPU host (NVIDIA)

Add the following on top of the CPU settings:

```bash
# Enable NVIDIA GPU passthrough
DOCKER_RUNTIME=nvidia
NVIDIA_VISIBLE_DEVICES=all
```

That's it for the minimum configuration. The system automatically discovers completed recordings by polling the Channels DVR API — no additional setup is needed.

### Recordings path — use the Setup Wizard

The trickiest part of setup is telling the container where to find your DVR recordings.
The **Setup Wizard** (web dashboard → ⚙ gear icon → **Setup Wizard**) walks you through this
step-by-step:

1. **Connect** — enter your DVR URL and test the connection; the wizard auto-detects the media folder path.
2. **Deployment type** — *Same Host* (DVR and container on the same machine) or *Remote* (recordings accessed over the network via SMB/CIFS or NFS).
3. **Mount configuration** — the wizard fills in the correct Docker volume settings for your chosen type and verifies the path is accessible from inside the container.
4. **Review & Apply** — writes the settings to `.env` and restarts the container.

> If you prefer to configure by hand, see the [Distributed Setup](#distributed-setup-dvr-on-a-different-host) section below.

### Distributed Setup (DVR on a different host)

If the Channels DVR runs on a separate machine and the captions host accesses recordings over the network (NFS, SMB, etc.), add path prefix mapping so API-returned paths resolve to the correct local mount:

```bash
# The path prefix as the DVR server reports it in its API
DVR_PATH_PREFIX=/tank/AllMedia/Channels

# The corresponding mount point on the captions host (managed by the wizard)
LOCAL_PATH_PREFIX=/mnt/channels
```

This translates every API path before file I/O — e.g.:
```
DVR API:  /tank/AllMedia/Channels/TV/Show Name/episode.mpg
Local:    /mnt/channels/TV/Show Name/episode.mpg
```

> **Tip:** Use forward slashes for all paths, including Windows UNC paths (`//server/share` instead of `\\server\share`). Python handles forward slashes natively on all platforms, and it avoids backslash escaping issues in `.env` files.

When the DVR and captions system run on the same host, skip these — paths pass through unchanged by default.

> An alternative webhook-based discovery mode using ChannelWatch is also supported. See [SETUP_ADVANCED.md](SETUP_ADVANCED.md#channelwatch-webhook-mode) for details.

The caption command is **auto-detected** — you don't need to set it. See [SETUP_ADVANCED.md](SETUP_ADVANCED.md) for GPU tuning, Fire TV transcoding, webhooks, and other advanced options.

## 2. Deploy

```bash
docker-compose up -d
docker-compose logs -f   # watch startup
```

Open the web dashboard at **http://YOUR_HOST_IP:8000**.

## 3. Create a Whitelist

**The whitelist controls which recordings get processed. Without it, nothing will be captioned.**

The fastest way to get started is from the **Recordings** view in the web dashboard:

1. Open the dashboard and go to the **Recordings** section
2. Browse the list of completed recordings from your DVR
3. Each recording has a **whitelist checkbox** — check the box next to any show you want to caption
4. The full title of each selected show is automatically added to your whitelist

This lets you build your initial whitelist by picking directly from real recordings on your DVR. Start with two or three shows you record frequently so you can observe the results quickly.

To refine your whitelist later — edit entries, use partial matches, or add regex patterns — go to **Settings → Whitelist** in the web UI. For the full whitelist reference including regular expressions, channel filters, and time-based rules, see [SETUP_ADVANCED.md](SETUP_ADVANCED.md#whitelist--full-reference).

> **Tip:** Every recording that arrives is checked against the whitelist. If no rule matches, it's silently skipped. You can always add more shows later.

### Test with Manual Processing

Before turning off dry-run mode, use **Manual Processing** to preview what would happen:

1. In the dashboard, click **Manual Process**
2. Select one or two completed recordings from the list
3. With `DRY_RUN=true`, the pipeline logs every step it *would* take without touching any files
4. Review the execution log in the **History** tab to confirm the recording was detected, matched the whitelist, and the caption command was constructed correctly

This is also useful for **performance testing** — turn off dry-run, manually process a single short recording, and note the execution time to gauge throughput before enabling automatic processing.

### Go Live

Once you're satisfied:

```bash
# Edit .env and set:
DRY_RUN=false

# Restart to pick up the change
docker-compose down && docker-compose up -d
```

New recordings that match your whitelist will now be processed automatically.

---

## Verify Setup

```bash
# Container running?
docker-compose ps

# Logs healthy?
docker-compose logs -f
```

---

## Troubleshooting

### Configuration not taking effect?

```bash
docker-compose down && docker-compose up -d
```

### Can't find recordings?

```bash
# Verify inside the container
docker exec -it py-captions-for-channels ls -la /recordings
```

Make sure `DVR_RECORDINGS_PATH` in `.env` matches the host path where your DVR stores recordings.

---

## Next Steps

| Step | Description |
|------|-------------|
| **Add shows** | Expand your whitelist from Recordings or Settings |
| **Turn off dry-run** | Set `DRY_RUN=false` and restart |
| **Advanced config** | See [SETUP_ADVANCED.md](SETUP_ADVANCED.md) for GPU, Fire TV transcoding, webhooks, whitelist regex |
| **Full reference** | See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for complete deployment documentation |
| **All settings** | See [.env.example](.env.example) for every configuration option |
