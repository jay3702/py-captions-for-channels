# NFS Setup Guide

This guide explains how to set up NFS (Network File System) for accessing Channels DVR recordings from Docker containers. NFS is recommended over CIFS/Samba for better Docker compatibility and reliability.

## Why NFS Instead of CIFS/Samba?

**Problems with CIFS/Samba + Docker:**
- Directory listing caching issues (Docker only sees subset of directories)
- UID/GID mapping complications
- Authentication headaches (domain vs workgroup)
- Slower performance
- Less reliable with Docker bind mounts

**Benefits of NFS:**
- ✅ No caching issues - Docker sees all files immediately
- ✅ Better performance
- ✅ Simpler permissions (native Unix permissions)
- ✅ More reliable network error handling
- ✅ Designed for Linux/Unix environments

## Setup Steps

### 1. Configure NFS Server (NIU/Recording Server)

On your NIU server (where recordings are stored):

```bash
# Copy the setup script to your NIU server
scp scripts/setup-nfs-server.sh jay@192.168.3.150:~/

# SSH to your NIU server
ssh jay@192.168.3.150

# Run the NFS setup script
sudo bash setup-nfs-server.sh
```

This will:
- Install `nfs-kernel-server`
- Export `/tank/AllMedia/Channels` via NFS
- Configure proper permissions (`no_root_squash` for Docker)
- Start and enable the NFS server

### 2. Configure WSL NFS Mount

On your Windows machine (WSL):

```bash
# Navigate to your project
cd /mnt/c/Users/jay/source/repos/py-captions-for-channels

# Make the script executable
chmod +x scripts/setup-wsl-nfs-mount.sh

# Run the WSL NFS mount setup
sudo bash scripts/setup-wsl-nfs-mount.sh
```

This will:
- Install NFS client tools (`nfs-common`)
- Remove old CIFS/Samba mount entries
- Add NFS mount to `/etc/fstab` for persistence
- Mount the NFS share at `/mnt/niu-recordings`
- Verify access and test write permissions

### 3. Restart Docker Containers

After setting up NFS:

```powershell
# Stop containers
docker compose -f docker-compose.local.yml --env-file .env.local down

# Optionally: Restart WSL for a clean slate
wsl --shutdown

# Start containers (wait a few seconds after shutdown)
docker compose -f docker-compose.local.yml --env-file .env.local up -d

# Verify container can see all recordings
docker exec py-captions-local ls /tank/AllMedia/Channels/TV | wc -l
```

You should now see **all** recording directories (not just a subset).

## Verification

### From WSL
```bash
# Check mount status
mount | grep niu-recordings

# List recordings
ls /mnt/niu-recordings/TV | wc -l

# Test write access
touch /mnt/niu-recordings/TV/test.txt
rm /mnt/niu-recordings/TV/test.txt
```

### From Docker Container
```bash
# Count directories
docker exec py-captions-local ls /tank/AllMedia/Channels/TV | wc -l

# Test write access
docker exec py-captions-local touch /tank/AllMedia/Channels/TV/test.txt
docker exec py-captions-local rm /tank/AllMedia/Channels/TV/test.txt
```

### From Another Machine
```bash
# List NFS exports
showmount -e 192.168.3.150

# Test mount
sudo mount -t nfs 192.168.3.150:/tank/AllMedia/Channels /mnt/test
```

## Troubleshooting

### NFS Server Not Responding
```bash
# On NIU server, check NFS is running
sudo systemctl status nfs-kernel-server

# Restart if needed
sudo systemctl restart nfs-kernel-server

# Verify exports
sudo exportfs -v

# Check firewall (allow port 2049)
sudo ufw allow from 192.168.3.0/24 to any port nfs
```

### Permission Denied
```bash
# On NIU server, verify export has no_root_squash
sudo exportfs -v

# Should show: /tank/AllMedia/Channels 192.168.3.0/24(rw,no_root_squash,...)
```

### Stale File Handle
```bash
# Unmount and remount
sudo umount -l /mnt/niu-recordings
sudo mount /mnt/niu-recordings

# Or restart WSL
wsl --shutdown
```

### Mount Not Persistent After Reboot
```bash
# Verify /etc/fstab entry exists
cat /etc/fstab | grep nfs

# Manually test fstab mount
sudo mount -a
```

## Performance Tuning

For better performance, you can adjust NFS mount options in `/etc/fstab`:

```
# High-performance options (less safe, better speed)
192.168.3.150:/tank/AllMedia/Channels /mnt/niu-recordings nfs rw,hard,intr,rsize=131072,wsize=131072,timeo=600,retrans=2,_netdev,x-systemd.automount 0 0

# Options explained:
# rsize=131072,wsize=131072 - 128KB read/write buffer (default is often 64KB)
# hard - don't give up on network errors (vs soft)
# intr - allow interrupting hung operations
# timeo=600 - 60 second timeout (600 deciseconds)
```

## Reverting to CIFS

If you need to go back to CIFS/Samba:

1. Remove NFS mount from `/etc/fstab`
2. Unmount: `sudo umount /mnt/niu-recordings`
3. Run the original CIFS setup script: `scripts/setup-wsl-mount.sh`

## Security Considerations

**NFS v3 (default) has no authentication** - it trusts the client's UID/GID. This is fine for trusted networks but:

- Only export to your local network (`192.168.3.0/24`)
- Use firewall rules to restrict access
- Consider NFS v4 with Kerberos for production/untrusted networks

For home lab use, NFS v3 is simpler and sufficient.

## References

- [NFS Kernel Server Documentation](https://linux.die.net/man/5/exports)
- [Docker Volumes with NFS](https://docs.docker.com/storage/volumes/#use-a-volume-driver)
- [WSL NFS Mounting](https://learn.microsoft.com/en-us/windows/wsl/filesystems)
