# Quick Setup Guide

Get up and running in three steps: configure, deploy, and whitelist your first shows.

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

That's it for the minimum configuration. The caption command is **auto-detected** — you don't need to set it. See [ADVANCED_SETUP.md](ADVANCED_SETUP.md) for GPU tuning, custom caption commands, and other options.

## 2. Deploy

```bash
docker-compose up -d
docker-compose logs -f   # watch startup
```

Open the web dashboard at **http://YOUR_HOST_IP:8000**.

## 3. Create a Whitelist

**The whitelist controls which recordings get processed. Without it, nothing will be captioned.**

The fastest way to bootstrap your whitelist is through the web dashboard:

1. Open **Settings** in the web UI
2. Scroll to the **Whitelist** section
3. Add one show title per line — partial names work (e.g. `News` matches "NBC Nightly News", "CBS News", etc.)
4. Save

Start small: pick two or three shows you record frequently so you can observe the results quickly.

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

## ChannelWatch Configuration (Webhook Mode)

If you're using webhook-based discovery (the default), configure ChannelWatch to send events:

1. Open ChannelWatch: `http://YOUR_DVR_IP:8501`
2. Go to **Settings → Notification Providers**
3. Enable **Custom URL**
4. Set **Custom Apprise URL**:
   - Same machine: `json://localhost:9000`
   - Remote machine: `json://YOUR_DOCKER_HOST_IP:9000`
5. Save settings

> Alternatively, set `DISCOVERY_MODE=polling` in `.env` to skip ChannelWatch entirely. Polling checks the DVR API periodically and requires no external setup.

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

### Not receiving webhooks?

```bash
docker-compose logs -f | grep webhook
netstat -tuln | grep 9000
curl http://YOUR_DOCKER_HOST:9000
```

---

## Next Steps

| Step | Description |
|------|-------------|
| **Add shows** | Expand your whitelist as you gain confidence |
| **Turn off dry-run** | Set `DRY_RUN=false` and restart |
| **Advanced config** | See [ADVANCED_SETUP.md](ADVANCED_SETUP.md) for GPU, whitelist regex, caption command customization |
| **Full reference** | See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for complete deployment documentation |
| **All settings** | See [.env.example](.env.example) for every configuration option |
