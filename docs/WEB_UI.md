# Web UI Reference

The web dashboard is available at `http://YOUR_SERVER:8000` once the container is running.

---

## Navigation Bar

The top bar is persistent across all views.

| Element | What it shows |
|---|---|
| App version | The running container version (e.g. `v1.2.0+build`). |
| **Services** dots | **Channels DVR** (blue) — reachability of the DVR API. **ChannelWatch** (green) — shown only in webhook mode. A grey dot means the service is unreachable. |
| **Polling** dot | Pulses blue when the polling source is actively checking for recordings; pulses green when a manual queue job is running. |
| **Processing** dots | Three dots: **File Ops**, **Whisper**, **ffmpeg**. One lights up while each stage is active, with a compact inline progress bar. |

**"MONITORING ONLY" banner** — an amber banner appears at the very top of the page when `DRY_RUN=true` (or `PROCESSING_ENABLED=false`). No files are modified while this is shown.

### Navbar Buttons

| Button | Opens |
|---|---|
| ☑ **Recordings** | Manual Processing dialog — select recordings to process now. |
| ⚙ (gear) | Settings dialog — configure all options and access the Setup Wizard. |

---

## Main Tabs

### Jobs

The default view. Shows the real-time processing queue and history.

**Queue section** lists:
- Any recording currently being captured by Channels DVR (shown as ⏺ Recording)
- Jobs currently running (⏳), waiting to run (⏸), or newly discovered (🔍)

**History section** lists completed, failed, cancelled, and dry-run jobs, sorted newest first.

| Status icon | Meaning |
|---|---|
| ⏳ | Running |
| ⏸ | Pending |
| 🔍 | Discovered, not yet queued |
| ✓ | Completed successfully |
| ✗ | Failed |
| ⏹ | Cancelled |
| 🔄 | Dry run (no changes made) |

**Click any row** to open the Execution Detail panel, which shows the full log output for that job and its start/end times, duration, and any error.

A **Cancel** button appears on currently running rows.

**Tab header buttons:**

| Button | What it does |
|---|---|
| **Clear Failures** | Removes failed, cancelled, dry-run, and stale entries from the list. Prompts for confirmation if there are pending jobs in the queue. |
| **Reset Cache** | Clears the polling cache so all recordings become eligible for re-processing. Useful if recordings were skipped or you want to reprocess everything. |

---

### System Monitor

Live view of what the system is doing right now.

**Pipeline Flow** panel (top) shows the active caption job:
- The file being processed
- Overall % complete and total elapsed time
- A segmented progress bar showing which stage is active:

  | Stage | What's happening |
  |---|---|
  | File Stability | Waiting for the recording file to stop growing (capture complete) |
  | Transcription | Whisper is generating the caption text |
  | Backup | Copying the original file before modification |
  | A/V Encode | ffmpeg is transcoding the video |
  | Probe | Examining the output file's streams |
  | Caption Delay / Clamp SRT | Adjusting caption timing |
  | Mux Captions | Embedding captions into the video |
  | Verify | Confirming the output is valid |
  | Finalize | Replacing the original with the captioned version |
  | Cleanup | Removing temporary files |

- **⚡ GPU Active** is shown when GPU hardware encoding/decoding is in use.
- After a job finishes, the panel shows "✓ Complete!" and clears itself after 30 seconds.

**System Metrics** charts (rolling 5-minute window, updated every second):
- **CPU Usage** — overall processor load
- **GPU** — GPU %, VRAM %, encode %, decode % (hidden when no GPU is present)
- **Disk I/O** — read and write throughput in MB/s
- **Network** — receive and transmit in Mbps

---

### Full Logs

Streams the container's log output in real time via WebSocket. Up to 500 lines are buffered in the browser. Automatically falls back to polling every 5 seconds if the WebSocket connection is unavailable.

The status indicator in the tab shows `(streaming)`, `(polling)`, or a line count.

---

### Quarantine

When a caption job runs, the original `.ts` file is renamed to `.orig` (backup) and the processed file takes its place. The `.orig` files are tracked here. After 30 days they are eligible for automatic purging.

**Summary line** at the top shows total quarantined size, number of expired files, last purge date, and space recovered in the past 30 days.

**Tab header buttons:**

| Button | What it does |
|---|---|
| **Scan (History)** | Looks through the processing history database for `.orig` and `.srt` files that were created but are no longer tracked — orphans from failed or interrupted jobs. |
| **Deep Scan (Filesystem)** | Performs a live filesystem scan across all configured scan paths to find `.orig` and `.srt` files not associated with any known job. Shows a streaming progress view as it scans. |
| **Restore Selected** | Moves checked files back to their original location, removing the captioned version. |
| **Delete Selected** | Permanently deletes checked files. Shows streaming progress during large batch deletes. |

**Quarantine table columns:** File, Type (`.orig` / `.srt`), Size, Date quarantined, Expiry date, Status (`Active` / `Expired`).

Click any column header to sort. Select individual rows with the checkbox, or use the header checkbox to select all.

**Scan Paths** (Configure button) — manage the filesystem paths that Deep Scan searches. Add, enable/disable, edit, or remove paths. The **Refresh** button in the Filesystem Topology sub-panel shows per-filesystem disk usage and warns about cross-filesystem moves.

---

### Channels Files *(experimental)*

Available only when `CHANNELS_FILES_ENABLED=true`. Cross-references the Channels DVR API's file database against the actual filesystem to find discrepancies.

**Run Audit** streams progress as it works through three checks:
- **Missing Files** — the DVR API reports these files exist, but they are not on disk.
- **Orphaned Files** — files are present on disk but not tracked by the DVR API. A "Show trashed files" toggle includes files found in trash folders.
- **Empty Folders** — recording folders that contain no media files.

A **Cancel** button stops the audit mid-run.

---

## Dialogs

### Manual Processing

Opened by the **☑ Recordings** button. Select one or more completed recordings to send through the caption pipeline immediately, without waiting for the automatic workflow.

**Options at the top apply to all selected recordings:**

| Option | Default | Effect |
|---|---|---|
| **Generate SRT (Whisper)** | On | Run Whisper transcription to produce captions. Uncheck to skip transcription (e.g. you only want to transcode). |
| **Run Transcode** | On (matches `TRANSCODE_FOR_FIRETV` setting) | Run the ffmpeg encode/mux step. Uncheck to do transcription only. |
| **Log Verbosity** | Normal | Controls how much detail appears in the job log: Minimal, Normal, or Verbose. |

**Recordings table:**

| Column | Notes |
|---|---|
| Checkbox | Disabled while a recording is still in progress. |
| Recording | Show title and episode title. |
| Date | When the recording was created. |
| Processed | ✓ green = previously succeeded; ✗ red = previously failed; blank = not yet processed. |
| Whitelist | Interactive checkbox. Toggle whether this show is on the whitelist. Only shown when whitelist matching is enabled. |

Click **Submit** to add selected recordings to the processing queue. The UI will burst-refresh for 12 seconds to show the jobs appearing.

---

### Settings

Opened by the **⚙** button. Configure every aspect of the system without editing the `.env` file directly.

**Top panel (always visible):**
- Shows server timezone, last processed time, and manual queue count.

| Button | What it does |
|---|---|
| **Restart System** | Gracefully restarts the container. Required to apply most configuration changes. |
| **⚙ Setup Wizard** | Opens the Setup Wizard (see below). |
| **Save to .env** | Saves all form values. Settings that don't require a restart (whitelist, dry-run mode, log verbosity, whisper model, etc.) take effect immediately. Others take effect after a restart. A confirmation banner appears with a **Restart now** shortcut. |
| **Cancel** | Closes without saving. |

**Configuration sections:**

| Section | What's here |
|---|---|
| Channels DVR Configuration | DVR URL, media folder path, container mount path. |
| Event Source Configuration | Discovery mode: Polling or ChannelWatch Webhook. |
| Polling Source Configuration | Poll interval, polling limit. (Hidden in webhook mode.) |
| Webhook Server Configuration | Webhook port. (Hidden in polling mode.) |
| ChannelWatch Configuration | ChannelWatch WebSocket URL. (Hidden in polling mode.) |
| Caption Pipeline Configuration | Whisper model, transcription device (GPU), Fire TV transcode, dry-run mode, pipeline timeout. |
| State and Logging Configuration | Log level, state storage settings. |
| Advanced Configuration | API timeout, caption delay, stale execution threshold, etc. |
| Encoder Quality Tuning | Encoding quality settings — section title shows the active encoder name. |
| Recording Whitelist | One rule per line. Wildcards (`*`, `?`) and regex supported. Empty = process all recordings. Changes take effect on the next job without a restart. |

---

### Setup Wizard

Opened from the Settings dialog. A 6-step guided configurator — the recommended way to set up the system for the first time or reconfigure it after a move.

| Step | What you do |
|---|---|
| 1 — Connect to DVR | Enter your Channels DVR URL. Click **Test & Detect** to verify the connection and auto-detect the media folder path. |
| 2 — Deployment Type | Choose **Same host** (DVR and py-captions on one machine) or **Remote / Distributed** (DVR recordings on a NAS or different server). |
| 3 — Recordings Path | Same host: enter the local recordings path. Remote: configure a CIFS/SMB or NFS mount with credentials. |
| 4 — New Recording Events | Choose **Polling** (recommended — periodically checks the DVR API) or **ChannelWatch Webhook** (event-driven, requires ChannelWatch). Set server timezone. |
| 5 — Caption Engine | Choose Whisper model size, transcription device, Fire TV transcode option, and whether to start in dry-run mode. |
| 6 — Review & Apply | Confirms all settings. Expand the details section to see the raw `.env` values that will be written. |

At step 6, **Apply & Restart** writes the configuration and immediately restarts the container. **Apply Only** writes the configuration without restarting (a manual restart will be needed for most changes to take effect).

---

### Execution Detail

Opened by clicking any row in the **Jobs** tab.

Shows:
- Status, start time, end time, duration
- File path that was processed
- Error message (if the job failed)
- Full log output for that specific job, extracted from the container log

For pending manual queue jobs: a **Remove from Queue** button cancels the queued job before it starts.
