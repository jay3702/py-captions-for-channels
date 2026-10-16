# Multiple Channels DVRs, One GPU

If you run several Channels DVR servers (separate machines or VMs) but only one
machine has a GPU worth using, run **one instance of py-captions-for-channels
per DVR on the GPU machine**. Each instance watches its own DVR, keeps its own
queue, history and web UI, and reads that DVR's recordings over a network
share. The instances take turns on the GPU automatically.

```
GPU machine (Linux, or Windows with WSL2 / Docker Desktop)
┌───────────────────────────────────────────────────────────┐
│ py-captions-for-channels  (web UI :8000) ──► DVR 1         │
│   recordings: local disk, or a share from DVR 1            │
│ py-captions-bedroom-dvr   (web UI :8001) ──► DVR 2         │
│   recordings: share from DVR 2 at /mnt/channels-bedroom-dvr│
│              │                       │                     │
│              └──► GPU slots (shared) ◄┘                    │
└───────────────────────────────────────────────────────────┘
```

The instances never talk to each other. Every instance on the same machine
mounts one shared Docker volume, `py-captions-gpu-slots`. Before a caption job
starts it takes a slot there; if none is free, the job shows **"Waiting for GPU
(in use by Living Room DVR: Show Name)"** in its web UI and starts as soon as a
slot opens. Waiting jobs are served in arrival order across all instances, so a
busy DVR can't starve a quiet one.

## Before you start

- One instance is already installed on the GPU machine.
- You know the second DVR's address, e.g. `http://192.168.1.21:8089`.
- The second DVR's recordings folder is shared over the network (NFS or SMB).
  If that DVR runs on Windows, see [DVRs running on Windows](#dvrs-running-on-windows).

## Adding an instance

Run the **same installer you used the first time**, on the GPU machine. It
notices the existing instance and offers to add another one. You give the new
instance a name (for example *Bedroom DVR*), then answer the usual DVR and
recordings questions for the *new* DVR. The installer picks everything that has
to differ from the first instance — its own folder, container name, web UI and
webhook ports, NAS mount point and mount service — and shows the new web UI
address at the end.

If the first instance was installed before GPU sharing existed, the installer
also offers to update it (about a minute); without that update the two would
not take turns on the GPU.

### Linux

Run the Linux quick-install command from [INSTALL.md](../INSTALL.md#linux) again.
When it reports the existing installation, choose **Add an instance for another
Channels DVR**.

### Windows (WSL2 installer)

Run the Windows install command from [INSTALL.md](../INSTALL.md#windows) again
in an **Administrator** PowerShell window. When it reports that ports 8000/9000
are in use, choose **A** (add another instance) — not **C**, which stops the
existing one. The installer inside the Ubuntu window then offers **Add an
instance for another Channels DVR**.

At the end, the auto-start step opens the new instance's ports in Windows
Firewall and LAN forwarding, alongside the first instance's.

### Windows with Docker Desktop

Run `scripts\setup-dockerdesktop.ps1` again and answer **Y** to *Add another
instance*. For the recordings path, give the other DVR's share as a UNC path
(`\\192.168.1.21\Channels`) or a mapped drive letter. A UNC path needs the
share's login saved in Windows Credential Manager first.

### Portainer

Run the pre-flight script from [INSTALL.md](../INSTALL.md#docker--portainer)
again and answer **Y** to *Set up an additional instance*. It writes a new env
file in a new folder. Then create a **new stack** with the name it suggests,
paste [docker-compose.yml](../docker-compose.yml), and **Load variables from
.env file** with the new file.

If it lists existing stacks that need updating, open each one → **Editor**,
replace its contents with the current `docker-compose.yml`, and **Update the
stack** with *Re-pull image* on.

### Then, in the new web UI

Open the address the installer showed (e.g. `http://GPU_MACHINE_IP:8001`),
run ⚙ → **Setup Wizard** to confirm the recordings are visible, and set up the
whitelist for that DVR.

## DVRs running on Windows

A Channels DVR on a Windows PC can be captioned from the GPU machine like any
other DVR — its recordings folder just has to be shared:

1. On the DVR PC, find the recordings folder (Channels DVR → Settings →
   Storage), right-click it → **Properties** → **Sharing** → **Advanced
   Sharing** → *Share this folder*. Under **Permissions**, give a Windows
   account **Change** (read/write) access — captioning writes the captioned
   recording back into the folder.
2. In the installer on the GPU machine, choose the NAS / network share option
   and enter the DVR PC's address, the share name, and that account's
   username and password.

The DVR reports recording paths in Windows form (`D:\Channels\TV\…`); the
Setup Wizard detects that prefix and maps it to the share automatically.

## Checking that they take turns

1. In each instance, ⚙ → Settings → **Processing Rules** (advanced) shows its
   **Instance Name**.
2. On the GPU machine (inside the Ubuntu window, for the WSL2 install), every
   instance should show the same slot volume:
   ```
   for c in $(docker ps --filter label=com.docker.compose.service=py-captions --format '{{.Names}}'); do
     docker inspect "$c" --format '{{.Name}}: {{range .Mounts}}{{if eq .Destination "/gpu-slots"}}{{.Name}}{{.Source}}{{end}}{{end}}'
   done
   ```
   Each line should end in `py-captions-gpu-slots`. A line that ends after the
   colon is an instance that predates GPU sharing — update it.
3. Start a manual reprocess in one instance, then one in the other. The second
   shows **"Waiting for GPU (in use by …)"** and starts when the first finishes.

## Setting up an instance by hand

Without an installer, give the new instance its own folder (a `git clone` of
this repository), copy `.env.example.nvidia` (or `.intel` / `.cpu`) to `.env`,
and set:

```
CHANNELS_DVR_URL=http://192.168.1.21:8089

# Recordings: the second DVR's share, already mounted on this machine
DVR_MEDIA_TYPE=none
DVR_MEDIA_OPTS=bind
DVR_MEDIA_DEVICE=/mnt/channels-bedroom
DVR_MEDIA_MOUNT=/mnt/channels-bedroom

# Must be different from every other instance on this machine
WEB_UI_PORT=8001
WEBHOOK_PORT=9001
CONTAINER_NAME=py-captions-bedroom
GLANCES_PORT=61209
INSTANCE_NAME=Bedroom DVR
```

Then `docker compose pull && docker compose up -d` in that folder. Mount the
share however you like (for example an `/etc/fstab` line with
`_netdev,x-systemd.before=docker.service`, so Docker waits for it at boot) —
just not with the name of a mount another instance already uses.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Conflict. The container name "/py-captions-for-channels" is already in use` | The new instance needs its own `CONTAINER_NAME` — use the installer's *add an instance* option, or set it by hand. |
| `port is already allocated` | Give the new instance its own `WEB_UI_PORT`, `WEBHOOK_PORT` and `GLANCES_PORT`. |
| Jobs in both instances run at the same time | One of them predates GPU sharing — see *Checking that they take turns*, step 2. |
| New instance's web UI unreachable from other PCs (Windows) | Re-run `scripts\autostart.ps1` as Administrator; it opens every instance's ports. |
| After a reboot, an instance sees no recordings | Its share didn't mount: check the DVR is on and the share is reachable, then restart the instance. |

## Notes

- **A crashed or killed instance never leaves the GPU locked.** The lock
  belongs to the running job's process and is released by the operating
  system when it exits.
- **`GPU_SLOTS`** is how many jobs may use the GPU at once across all
  instances (default 1; set the same value everywhere). Raise it only if the
  GPU has memory for more than one Whisper model plus an encode at the same
  time.
- **Two GPUs in one machine?** Give the instances on the second GPU their own
  `GPU_SLOT_VOLUME` name so the two groups don't wait on each other.
- **Canceling** a job that is waiting for the GPU removes it from the line.
- **Each instance downloads its own copy of the Whisper model** on its first
  job, so expect that job to take a few minutes longer.
- **A single instance** uses the same mechanism: its automatic and
  manual-process jobs take turns with each other instead of running side by
  side.
