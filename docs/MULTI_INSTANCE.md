# Multiple Channels DVRs, One GPU

If you run several Channels DVR servers (separate machines or VMs) but only one
machine has a GPU worth using, run **one instance of py-captions-for-channels
per DVR on the GPU machine**. Each instance polls its own DVR, keeps its own
queue, history and web UI, and reads that DVR's recordings over a network
mount. A shared *GPU slot directory* makes the instances take turns on the GPU.

```
GPU machine
┌──────────────────────────────────────────────────────┐
│ py-captions-dvr1  (UI :8000) ──polls──► DVR 1         │
│   data: /srv/py-captions/dvr1   media: NFS from DVR 1 │
│ py-captions-dvr2  (UI :8001) ──polls──► DVR 2         │
│   data: /srv/py-captions/dvr2   media: SMB from DVR 2 │
│              │                    │                   │
│              └──► /var/lib/py-captions/gpu-slots ◄────┘
└──────────────────────────────────────────────────────┘
```

The instances never talk to each other. Before a caption job starts, it takes
a slot in the shared directory; if none is free, the job shows
**"Waiting for GPU (in use by dvr1: Show Name)"** in that instance's UI and
starts as soon as a slot opens. Waiting jobs are served in arrival order across
all instances, so a busy DVR can't starve a quiet one.

## Setting up each instance

Give every instance its own folder (or Portainer stack) containing
`docker-compose.yml` and its own `.env`. In each `.env`:

| Setting | Must be | Example (second DVR) |
|---|---|---|
| `CHANNELS_DVR_URL` | this instance's DVR | `http://192.168.1.21:8089` |
| `HOST_DATA_DIR` | different per instance | `/srv/py-captions/dvr2` |
| `WEB_UI_PORT` | different per instance | `8001` |
| `WEBHOOK_PORT` | different per instance | `9001` |
| `CONTAINER_NAME` | different per instance | `py-captions-dvr2` |
| `GLANCES_PORT` | different per instance | `61209` |
| `GPU_SLOT_HOST_DIR` | **the same** in every instance | `/var/lib/py-captions/gpu-slots` |
| `GPU_SLOTS` | **the same** in every instance | `1` |
| `INSTANCE_NAME` | a friendly name | `Bedroom DVR` |

Plus the media mount for that DVR's recordings — the same settings as any
setup where captions run on a different machine from the DVR:
`DVR_PATH_PREFIX` (the DVR's own media folder path) and the
`DVR_MEDIA_*` mount settings. For an NFS export, for example:

```
DVR_MEDIA_TYPE=nfs
DVR_MEDIA_OPTS=addr=192.168.1.21,rw,nfsvers=4
DVR_MEDIA_DEVICE=:/tank/AllMedia/Channels
DVR_MEDIA_MOUNT=/mnt/channels
DVR_PATH_PREFIX=/tank/AllMedia/Channels
```

With plain `docker compose`, start each folder under its own project name so
the per-instance volumes don't collide:

```
cd /srv/py-captions/dvr2-stack && docker compose -p py-captions-dvr2 up -d
```

(Portainer already gives each stack its own project.)

## Notes

- **The slot directory must be a local directory on the GPU machine**, not an
  NFS/SMB share. Slots are file locks, which are only reliable within one
  machine.
- **A crashed or killed instance never leaves the GPU locked.** The lock
  belongs to the running job's process and is released by the operating
  system when it exits.
- **`GPU_SLOTS`** is how many jobs may use the GPU at once across all
  instances. Keep it at 1 unless the GPU has memory for more than one Whisper
  model plus an encode at the same time.
- **Canceling** a job that is waiting for the GPU removes it from the line.
- **A single instance** uses the same mechanism: without `GPU_SLOT_HOST_DIR`,
  its automatic and manual-process jobs take turns with each other instead of
  running side by side.
