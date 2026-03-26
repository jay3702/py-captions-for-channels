# Library Processing

py-captions-for-channels can generate captions for personal media that lives outside the Channels DVR recordings folder — VHS transfers, home movies, ripped Blu-rays, MP4 downloads, etc.

## Overview

The feature works in two layers:

1. **Volume mount** — a host folder is bind-mounted into the container so the container can read (and write `.srt` files to) those files.
2. **Library paths** — one or more container-side directories are registered with the app. The Library tab in the web UI lists all media files found under those paths, shows whether captions already exist, and lets you queue files for processing.

This is a post-installation activity. The core DVR recording workflow requires no library configuration.

---

## Setup (single NAS / server)

This is the typical case: all personal media lives under one top-level folder on one machine or NAS.

### Step 1 — Discover

1. Open the web UI and go to **Library > Manage Library Paths**.
2. Click **Discover from Channels…**

The app queries Channels DVR for all personal media sources (Movies, TV, Videos) and calculates a proposed Docker volume mount from the file paths it finds. DVR recordings are automatically excluded.

The result panel shows:
- **Host path** — the directory on the Docker host that will be mounted (i.e. `LIBRARY_HOST_PATH`)
- **Container path** — where it will appear inside the container (`LIBRARY_CONTAINER_PATH`)
- **Paths to add** — the specific sub-directories that will be registered in the library

### Step 2 — Apply

Click **Apply (restart required)**.

The app writes `LIBRARY_HOST_PATH` and `LIBRARY_CONTAINER_PATH` to your `.env` file and pre-registers the container paths in the database. The paths won't be accessible yet — the container must be restarted to activate the new volume mount.

### Step 3 — Restart

```bash
docker compose restart
```

After the restart the volume mount is active, the paths are accessible, and the Library tab will show your files.

---

## Setup (media on multiple servers)

If your media spans two or more NAS devices or servers, Docker requires a separate volume mount for each one. Discovery handles this automatically.

**Example:** Movies on `/mnt/nas1/Movies` and home videos on `/mnt/nas2/Videos` have no common ancestor that is useful as a single mount root.

When Discovery detects this situation it proposes **two** (or up to three) mount slots:

| Slot | `.env` variable | Default container path |
|------|----------------|------------------------|
| 1 | `LIBRARY_HOST_PATH` / `LIBRARY_CONTAINER_PATH` | `/mnt/library` |
| 2 | `LIBRARY_HOST_PATH_2` / `LIBRARY_CONTAINER_PATH_2` | `/mnt/library2` |
| 3 | `LIBRARY_HOST_PATH_3` / `LIBRARY_CONTAINER_PATH_3` | `/mnt/library3` |

The discovery panel will show an amber warning when multiple mounts are required, and list each slot's host/container path pair individually. **Apply** writes all slot values to `.env` in one operation. A single restart activates all of them.

> **Limit:** Docker Compose supports three library mount slots in the provided `docker-compose.yml`. If your media spans more than three unrelated roots, you will need to manually edit `docker-compose.yml` to add additional mount lines and set corresponding `.env` variables.

---

## Manual configuration (without auto-discovery)

If you prefer not to use the Discovery feature, you can configure the mount manually.

### Edit `.env`

```ini
# Slot 1
LIBRARY_HOST_PATH=/tank/AllMedia
LIBRARY_CONTAINER_PATH=/mnt/library

# Slot 2 (omit if not needed)
LIBRARY_HOST_PATH_2=/mnt/nas2/Videos
LIBRARY_CONTAINER_PATH_2=/mnt/library2
```

### Add paths in the UI

1. Open **Library > Manage Library Paths**.
2. Type the container-side path (e.g. `/mnt/library/Movies`) in the input box and click **Add**, or use **Browse…** to navigate the filesystem and select a folder.

Paths can be added before or after the restart.

### Restart

```bash
docker compose restart
```

---

## Using the Library tab

After setup, the **Library** tab (accessible from the nav bar or the Library page) shows a file browser for each registered path.

| Column | Meaning |
|--------|---------|
| File | Filename |
| Type | File extension |
| Captions | Whether an `.srt` file exists alongside the media |
| Status | Last processing result (✓ success / ✗ failed / — not processed) |
| Actions | Queue for captioning; restore original if transcoded |

You can process individual files or select multiple and use **Process Selected**.

The **Recursive** toggle includes files in sub-folders of a registered path.

---

## Supported file types

By default: `.mpg`, `.ts`, `.mkv`, `.mp4`, `.avi`, `.wmv`

To change the list, set `MEDIA_FILE_EXTENSIONS` in `.env`:

```ini
MEDIA_FILE_EXTENSIONS=.mpg,.ts,.mkv,.mp4,.avi,.wmv,.mov,.m4v
```

Changes take effect immediately — no restart required.

---

## Restore original files

If you processed a file with `TRANSCODE_FOR_FIRETV=true`, the original was replaced and a `.cc4chan.orig` backup was created. The **Restore** action in the Library tab moves the original back and removes the transcoded copy.

---

## DVR overlap protection

The discovery and manual-add workflows both prevent you from accidentally registering a path that overlaps with the Channels DVR recordings folder. Overlap is detected by inode comparison (not just string prefix), so bind-mount aliases are also caught. Overlapping paths are blocked with an error message.

---

## Non-Docker deployment

If you are running without Docker (e.g. directly with `python -m py_captions_for_channels`), the container-side path concept does not apply. Just register the host filesystem path directly in **Library > Manage Library Paths**. The `.env` mount variables are only used by Docker Compose.
