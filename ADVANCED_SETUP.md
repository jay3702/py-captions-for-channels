# Advanced Setup

This guide covers topics beyond the [basic setup](SETUP.md): GPU configuration, custom caption commands, and the full capabilities of the whitelist system.

---

## Table of Contents

- [ChannelWatch (Webhook Mode)](#channelwatch-webhook-mode)
- [Custom Caption Command](#custom-caption-command)
- [GPU Configuration](#gpu-configuration)
- [Whitelist — Full Reference](#whitelist--full-reference)
  - [How Matching Works](#how-matching-works)
  - [Regular Expressions](#regular-expressions)
  - [Channel and Time Filters](#channel-and-time-filters)
  - [Examples](#examples)

---

## ChannelWatch (Webhook Mode)

By default, the system discovers completed recordings by **polling** the Channels DVR API. This requires no extra setup.

An alternative is **webhook mode**, which uses [ChannelWatch](https://github.com/biscuitehh/ChannelWatch) to push recording events to the system in real time. This can be slightly faster (events arrive immediately instead of on the next poll cycle) but requires ChannelWatch to be installed and configured.

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

## Custom Caption Command

By default the caption command is auto-detected at startup — you don't need to set it. The auto-detection logic:

| `TRANSCODE_FOR_FIRETV` | Command used |
|---|---|
| `false` (default) | `whisper --model medium --output_format srt --output_dir "<dir>" "<file>"` |
| `true` | `python -m py_captions_for_channels.embed_captions --input {path}` |

To override the default, set `CAPTION_COMMAND` in `.env`. The `{path}` placeholder is replaced with the recording's file path at runtime.

```bash
# Example: use a specific Whisper model
CAPTION_COMMAND=whisper --model large-v2 --output_format srt --output_dir "$(dirname "{path}")" "{path}"

# Example: use faster-whisper instead
CAPTION_COMMAND=faster-whisper "{path}" --model medium --output_format srt

# Example: dry-run placeholder (no-op)
CAPTION_COMMAND=echo "Would process: {path}"
```

### Fire TV / Android Transcoding

If your clients need burned-in captions (Fire TV, some Android devices), enable full transcoding:

```bash
TRANSCODE_FOR_FIRETV=true
KEEP_ORIGINAL=true    # archive the original .mpg as .mpg.orig
```

This is significantly slower (10–30 min per hour of recording vs 3–6 min for SRT-only) but produces MP4 files with embedded subtitle tracks.

---

## GPU Configuration

An NVIDIA GPU dramatically accelerates both Whisper transcription and video encoding.

### Minimum Requirements

- NVIDIA GPU with **6 GB+ VRAM** (GTX 1660 Super / RTX 2060 or better)
- NVIDIA driver **525+** on the host
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed

### Key Settings

```bash
# GPU device selection for Whisper AI transcription
# auto | nvidia | amd | intel | none
WHISPER_DEVICE=auto

# Hardware-accelerated video decoding (for transcoding mode)
# auto | cuda | qsv | vaapi | off
HWACCEL_DECODE=auto

# GPU video encoder (for transcoding mode)
# auto | nvenc | qsv | amf | vaapi | cpu
GPU_ENCODER=auto
```

### NVIDIA Encoding Quality

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

| Hardware | SRT-only (1-hr recording) | Full Transcode (1-hr recording) |
|---|---|---|
| RTX 2060 | ~4 min | ~12 min |
| RTX 2080 Ti | ~3 min | ~8 min |
| RTX 3070 | ~2.5 min | ~7 min |
| CPU-only (i7-10700) | ~25 min | ~45 min |

> See [docs/SYSTEM_REQUIREMENTS.md](docs/SYSTEM_REQUIREMENTS.md) for more detailed benchmarks.

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

> **Tip:** Use the web UI's interactive whitelist checkboxes to quickly toggle individual shows without editing the file directly.
