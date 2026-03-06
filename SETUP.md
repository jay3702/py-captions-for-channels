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
- **NVIDIA GPU users only:** [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) must also be installed, and you'll need `DOCKER_RUNTIME=nvidia` + `NVIDIA_VISIBLE_DEVICES=all` in your `.env` (see step 1 below).

---

## 1. Configure

```bash
cp .env.example .env
nano .env   # or vi, vim, etc.
```

Set these three values:

```bash
# Your Channels DVR IP address
CHANNELS_DVR_URL=http://YOUR_DVR_IP:8089

# Path to your DVR recordings on the HOST machine
DVR_RECORDINGS_PATH=/path/to/your/recordings

# Leave DRY_RUN=true until you've verified the setup
DRY_RUN=true
```

That's it for the minimum configuration. The system automatically discovers completed recordings by polling the Channels DVR API — no additional setup is needed.

### Distributed Setup (DVR on a different host)

If the Channels DVR runs on a separate machine and the captions host accesses recordings over the network (NFS, SMB, etc.), add path prefix mapping so API-returned paths resolve to the correct local mount:

```bash
# The path prefix as the DVR server reports it in its API
DVR_PATH_PREFIX=/tank/AllMedia/Channels

# The corresponding mount point on the captions host
LOCAL_PATH_PREFIX=//192.168.3.150/Channels
```

This translates every API path before file I/O — e.g.:
```
DVR API:  /tank/AllMedia/Channels/TV/Show Name/episode.mpg
Local:    //192.168.3.150/Channels/TV/Show Name/episode.mpg
```

> **Tip:** Use forward slashes for all paths, including Windows UNC paths (`//server/share` instead of `\\server\share`). Python handles forward slashes natively on all platforms, and it avoids backslash escaping issues in `.env` files.

To find your DVR's path prefix, query a recording from the API:
```bash
curl http://YOUR_DVR_IP:8089/api/v1/all?source=recordings
# Look for the "path" field — the root portion is your DVR_PATH_PREFIX
```

When the DVR and captions system run on the same host, skip these — paths pass through unchanged by default.

> An alternative webhook-based discovery mode using ChannelWatch is also supported. See [SETUP_ADVANCED.md](SETUP_ADVANCED.md#channelwatch-webhook-mode) for details.

The caption command is **auto-detected** — you don't need to set it. See [SETUP_ADVANCED.md](SETUP_ADVANCED.md) for GPU tuning, custom caption commands, and other advanced options.

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
| **Advanced config** | See [SETUP_ADVANCED.md](SETUP_ADVANCED.md) for GPU, webhooks, whitelist regex, caption command customization |
| **Full reference** | See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for complete deployment documentation |
| **All settings** | See [.env.example](.env.example) for every configuration option |
