# Advanced Setup

This guide covers topics beyond the [Quick Setup Guide](SETUP.md): caption embedding modes, GPU configuration, webhook-based discovery, and the full capabilities of the whitelist system.

---

## Table of Contents

- [Caption Embedding Modes (EMBED\_CAPTIONS)](#caption-embedding-modes-embed_captions)
- [GPU Configuration](#gpu-configuration)
- [ChannelWatch (Webhook Mode)](#channelwatch-webhook-mode)
- [Whitelist — Full Reference](#whitelist--full-reference)
  - [How Matching Works](#how-matching-works)
  - [Regular Expressions](#regular-expressions)
  - [Channel and Time Filters](#channel-and-time-filters)
  - [Examples](#examples)

---

## Caption Embedding Modes (EMBED_CAPTIONS)

By default, the system generates `.srt` (sidecar) caption files alongside your recordings. Most clients — Apple TV, Roku, and the Channels web player — pick these up automatically.

`EMBED_CAPTIONS` controls how (or whether) captions are also embedded directly into the recording file:

| Value | Behaviour |
|---|---|
| `auto` (default) | Auto-select based on content: lossless remux for most recordings, SRT-only for variable-frame-rate content |
| `remux` | Always mux captions losslessly into the recording file (fast — ~10 s ffmpeg, no re-encode) |
| `h264` | Re-encode the recording to H.264+AAC MP4 with embedded captions (slower: ~4–10 min GPU, ~10–30 min CPU) |
| `srt_only` | Never modify the recording file — write a `.srt` sidecar only |

**You do not need `h264` for Android or Fire TV.** The `auto`/`remux` modes already produce an MP4 with compatible audio and an embedded captions track that these clients recognise.

`h264` is useful when you specifically want to convert recordings to H.264 — for example:
- Reducing storage for MPEG2 OTA recordings (~2–3× smaller)
- Devices that cannot decode the source codec at all
- VFR (variable-frame-rate) content such as screen recordings (`auto` routes these to `h264` automatically)

```bash
# .env
EMBED_CAPTIONS=auto   # recommended default
```

> **Legacy alias:** `TRANSCODE_FOR_FIRETV=true` still works and is silently treated as `EMBED_CAPTIONS=h264`.

### Hardware Acceleration for H.264 Encoding

When `EMBED_CAPTIONS=h264`, the system uses ffmpeg to re-encode the video. These settings control GPU use during that encoding step:

```bash
# Hardware-accelerated video decoding
# auto | cuda | qsv | vaapi | off
HWACCEL_DECODE=auto

# GPU video encoder
# auto | nvenc | qsv | vaapi | cpu
GPU_ENCODER=auto
```

`auto` is recommended. If you’re troubleshooting encoding issues, you can force a value to bypass auto-detection.

---

## GPU Configuration

An NVIDIA GPU dramatically accelerates both Whisper transcription and video encoding.

This system was developed and tested on an **Intel i7-7700K** with an **NVIDIA RTX 2080 (8 GB VRAM)**. The Docker image includes the required CUDA drivers and toolkits, which should work for most NVIDIA GPUs.

### Minimum Requirements

- NVIDIA GPU with **6 GB+ VRAM** (GTX 1660 Super / RTX 2060 or better)
- NVIDIA driver **525+** on the host
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed

### Key Settings

```bash
# GPU device selection for Whisper AI transcription
# auto | nvidia | amd | intel | none
WHISPER_DEVICE=auto
```

`auto` is recommended. If you're troubleshooting transcription GPU issues, try forcing `nvidia` to see if auto-detection is the problem.

> **Note:** Hardware acceleration for video encoding (`HWACCEL_DECODE`, `GPU_ENCODER`) is only relevant when `EMBED_CAPTIONS=h264`. See [Caption Embedding Modes](#caption-embedding-modes-embed_captions) above.

### NVIDIA Encoding Quality

> Only applies when `EMBED_CAPTIONS=h264`.

```bash
# Constant-quality level for NVENC (0–51, lower = better quality)
# 18 = near-transparent, 23 = balanced (default), 28 = smaller files
NVENC_CQ=23
```

### Docker Compose GPU Passthrough

The default `docker-compose.yml` includes GPU passthrough. Verify your setup:

```bash
# Confirm the GPU is visible inside the container
docker exec -it py-captions-for-channels nvidia-smi
```

### Performance Benchmarks (Approximate)

Measured on an i7-7700K + RTX 2080 (8 GB). Newer GPUs will be proportionally faster.

| Mode | Per 1-hour recording |
|---|---|
| SRT-only (GPU) | ~1–2 min |
| Remux (GPU or CPU) | ~10–20 s |
| H.264 encode (GPU) | ~4–10 min |
| SRT-only (CPU-only) | ~10 min |
| H.264 encode (CPU-only) | ~10–20 min |

> CPU-only benchmarks are estimates — your mileage may vary depending on CPU. See [docs/SYSTEM_REQUIREMENTS.md](docs/SYSTEM_REQUIREMENTS.md) for more detailed benchmarks.

---

## ChannelWatch (Webhook Mode)

By default, the system discovers completed recordings by **polling** the Channels DVR API. This requires no extra setup.

An alternative is **webhook mode**, which uses [ChannelWatch](https://github.com/biscuitehh/ChannelWatch) to push recording events to the system in real time. The system responds only to the **recording complete** event provided by ChannelWatch. This can be slightly faster (events arrive immediately instead of on the next poll cycle) but requires ChannelWatch to be installed and configured.

### Enable Webhook Mode

Set this in `.env`:

```bash
DISCOVERY_MODE=webhook
```

### Configure ChannelWatch

1. Open ChannelWatch: `http://YOUR_DVR_IP:8501`
2. Go to **Settings → Notification Providers**
3. Enable **Custom URL**
4. Set **Custom Apprise URL**:
   - Same machine: `json://localhost:9000`
   - Remote machine: `json://YOUR_DOCKER_HOST_IP:9000`
5. Save settings

### Webhook Server Settings

```bash
# Host to bind webhook server to (default: 0.0.0.0)
WEBHOOK_HOST=0.0.0.0

# Port for webhook server (default: 9000)
WEBHOOK_PORT=9000
```

### Troubleshooting Webhooks

```bash
# Check logs for webhook activity
docker-compose logs -f | grep webhook

# Verify port is accessible
netstat -tuln | grep 9000

# Test from the DVR machine
curl http://YOUR_DOCKER_HOST:9000
```

---

## Whitelist — Full Reference

The whitelist controls which recordings the system processes. **If the whitelist is empty or missing, all recordings are skipped.**

Edit the whitelist in the web UI (**Settings → Whitelist**) or directly in `whitelist.txt` (one rule per line). Lines starting with `#` are comments.

### How Matching Works

All matching is **case-insensitive**.

A plain text entry is treated as a **substring match** — it matches any recording whose title contains that text anywhere. For example:

```
News
```

matches "NBC Nightly News", "CBS Evening News", "Fox News Sunday", etc. The equivalent full regular expression would be:

```
(?i).*News.*
```

That is: case-insensitive (`(?i)`), any characters before (`.*`), the text, any characters after (`.*`).

You don't need to write the full expression — just entering `News` does the same thing. The regex form is only useful if you need more precise control (anchoring, alternation, exclusions).

### Regular Expressions

If a rule contains any regex operator character (`. * + ? ^ $ { } ( ) [ ] \ |`), it's automatically treated as a regular expression instead of a plain substring. All regex patterns are **case-insensitive**.

#### Useful Patterns

| Pattern | What it matches | Use case |
|---|---|---|
| `^NBC` | Titles that **start with** "NBC" | Match only NBC-branded shows |
| `News$` | Titles that **end with** "News" | Avoid matching "Newsroom" |
| `News\|Weather` | Titles containing "News" **or** "Weather" | Match multiple keywords in one rule |
| `^(Dateline\|60 Minutes\|48 Hours)$` | Exactly "Dateline", "60 Minutes", or "48 Hours" | Precise multi-show list |
| `Late.*Show` | "Late" followed (eventually) by "Show" | Matches "Late Show", "Late Night Show" |
| `S\d{2}E\d{2}` | "S" + 2 digits + "E" + 2 digits | Match season/episode patterns like S03E12 |
| `\bLive\b` | "Live" as a whole word | Avoid matching "Olive" or "Liverpool" |
| `^(?!.*Rerun).*News` | Contains "News" but **not** "Rerun" | Exclude reruns of news programs |

#### Quick Regex Reference

| Syntax | Meaning |
|---|---|
| `.` | Any single character |
| `*` | Zero or more of the previous |
| `+` | One or more of the previous |
| `?` | Zero or one of the previous |
| `^` | Start of title |
| `$` | End of title |
| `\b` | Word boundary |
| `\d` | Any digit (0–9) |
| `(A\|B)` | "A" or "B" |
| `[abc]` | Any one of a, b, c |
| `[^abc]` | Any character except a, b, c |

### Channel and Time Filters

For more targeted rules, use the semicolon-delimited extended format:

```
ShowName;DayOfWeek;Channel(s);Time
```

| Field | Format | Example | Notes |
|---|---|---|---|
| Show name | Text or regex | `Dateline` | Required |
| Day of week | Full name | `Friday` | Optional (omit to match any day) |
| Channel(s) | Comma-separated | `11.1,113` | Optional (omit to match any channel) |
| Time | `HH:MM` (24-hour) | `21:00` | Optional (omit to match any time) |

Omitted trailing fields are treated as wildcards. Examples:

```
# Dateline on any channel, any day, any time
Dateline

# Dateline only on Fridays
Dateline;Friday

# Dateline on Fridays on channels 11.1 or 113
Dateline;Friday;11.1,113

# Dateline on Fridays on channels 11.1 or 113 at 9 PM
Dateline;Friday;11.1,113;21:00
```

> **Note on delayed captions:** Some programs — such as Dateline, 48 Hours, and 20/20 — have delayed (out-of-sync) captions only when they are first aired. Repeats and repackaged versions (e.g. "Dateline: Secrets Uncovered") always have synchronized captions. If you notice caption timing issues, the original broadcast airing is likely the cause. Channel and time filters can help you target only first airings if desired.

### Examples

A complete `whitelist.txt` showing various rule types:

```
# Simple substring matches (case-insensitive)
News
60 Minutes
Jeopardy
Wheel of Fortune

# Regex: all NBC or CBS branded shows
^(NBC|CBS)

# Regex: anything with "Late" and "Show" in the title
Late.*Show

# Regex: match either Dateline or 20/20
Dateline|20/20

# Time-restricted: local news on weeknights at 11 PM
News;Monday;11.1;23:00
News;Tuesday;11.1;23:00
News;Wednesday;11.1;23:00
News;Thursday;11.1;23:00
News;Friday;11.1;23:00
```

> **Tip:** Use the Recordings dialog to quickly toggle individual shows without editing the whitelist setting directly. You can also use it to verify that all of the desired shows are whitelisted, and no others.
