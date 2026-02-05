# Changes Required for Next Docker Image Build

## Date: 2026-02-02
## Context: Windows + Docker Desktop + NFS deployment fixes

---

## 1. Code Changes

### watcher.py - Manual Reprocessing Fix

**File:** `py_captions_for_channels/watcher.py`

**Issue:** Manual processing doesn't delete existing .srt files, so it skips already-captioned recordings instantly (0.0 seconds elapsed). Users need to reprocess files to fix errors or try different Whisper models.

**Fix:** Add SRT file deletion before manual processing (around line 56-58):

```python
            try:
                LOG.info("Manual processing: %s", path)
                mpg_path = path
                orig_path = path + ".orig"
                srt_path = path.rsplit(".", 1)[0] + ".srt"
                
                # 1. If .orig exists, restore it
                if os.path.exists(orig_path):
                    LOG.info(
                        "Restoring original from .orig: %s -> %s",
                        orig_path,
                        mpg_path,
                    )
                    shutil.copy2(orig_path, mpg_path)
                # If .orig does not exist, proceed with current .mpg (no subtitle check)

                # 2. Remove existing .srt to force reprocessing
                if os.path.exists(srt_path):
                    LOG.info("Removing existing SRT for reprocessing: %s", srt_path)
                    os.remove(srt_path)

                # Create a minimal event from the path with settings
```

**Reasoning:** Manual processing should allow reprocessing even if captions exist. This enables users to:
- Fix failed caption jobs
- Regenerate with different Whisper models
- Update captions for better quality

---

## 2. Docker Compose Configuration

### docker-compose.local.yml - Multiple Critical Fixes

#### Fix 1: Web Container Needs NFS Volume Mount

**Issue:** Web container couldn't access recordings to delete .srt files or run manual processing.

**Current (BROKEN):**
```yaml
  py-captions-web:
    volumes:
      - py-captions-data:/app/data
      - py-captions-logs:/app/logs
```

**Required:**
```yaml
  py-captions-web:
    volumes:
      # NFS mount for accessing recordings
      - channels-nfs:/tank/AllMedia/Channels:rw
      # Shared volumes with watcher
      - py-captions-data:/app/data
      - py-captions-logs:/app/logs
```

#### Fix 2: Web Container Missing CAPTION_COMMAND

**Issue:** Web container can't run pipeline for manual processing without CAPTION_COMMAND.

**Required addition to py-captions-web environment:**
```yaml
    environment:
      - STATE_FILE=/app/data/state.json
      - LOG_FILE=/app/logs/app.log
      - CHANNELS_API_URL=${CHANNELS_API_URL:-http://192.168.3.150:8089}
      - CAPTION_COMMAND=/app/scripts/embed_captions.sh {path}
```

#### Fix 3: CHANNELS_API_URL for Main Container

**Issue:** Main container was trying to use `host.docker.internal` which doesn't work from WSL Docker.

**Current (BROKEN):**
```yaml
      - CHANNELS_API_URL=${CHANNELS_DVR_URL:-http://host.docker.internal:8089}
```

**Required:**
```yaml
      - CHANNELS_API_URL=${CHANNELS_API_URL:-http://192.168.3.150:8089}
```

**Also update .env.local:**
```bash
# Changed from CHANNELS_DVR_URL to match code
CHANNELS_API_URL=http://192.168.3.150:8089
```

#### Fix 4: Docker NFS Volume (Already Working)

**Status:** This is already correctly configured and working. Document for reference:

```yaml
volumes:
  py-captions-data:
  py-captions-logs:
  channels-nfs:
    driver: local
    driver_opts:
      type: nfs
      o: addr=192.168.3.150,vers=3,nolock,noacl,rw
      device: ":/tank/AllMedia/Channels"
```

**Critical:** This uses Docker's native NFS volume driver, which solves the directory listing cache issue that plagued CIFS/SMB bind mounts.

---

## 3. NFS Server Configuration (NIU)

### Required NFS Export Settings

**File on NIU:** `/etc/exports`

**Required entry:**
```bash
/tank/AllMedia/Channels  192.168.0.0/16(rw,sync,no_subtree_check,no_root_squash,insecure)
```

**Key options:**
- `192.168.0.0/16` - Allows all 192.168.x.x addresses (supports VPN across multiple subnets)
- `no_root_squash` - Allows WSL root to access as root (required for Docker)
- `insecure` - Allows connections from ports >1024 (required for WSL)

**After editing:**
```bash
sudo exportfs -ra
```

---

## 4. Deployment Documentation Updates

### Add to README or DEPLOYMENT.md:

**Pattern 2: Separate File Server (NFS)**

For deployments where recordings are on a NAS/file server:

1. **Use NFS, not CIFS/SMB**
   - CIFS/SMB has directory listing cache issues with Docker bind mounts
   - Docker's native NFS volume driver solves this problem

2. **NFS Server Configuration**
   - Export with `no_root_squash` and `insecure` options
   - Use `/16` network mask for VPN compatibility
   - Example: `192.168.0.0/16` covers all 192.168.x.x addresses

3. **Docker Compose NFS Volume**
   ```yaml
   volumes:
     channels-nfs:
       driver: local
       driver_opts:
         type: nfs
         o: addr=YOUR_NFS_SERVER,vers=3,nolock,noacl,rw
         device: ":/path/to/recordings"
   ```

4. **Web Container Requirements**
   - Must mount same NFS volume as main container
   - Must have CAPTION_COMMAND environment variable
   - Required for manual processing feature to work

---

## 5. Known Issues Fixed

### Docker + Network Filesystems

**Problem:** Docker bind mounts cache directory listings from network filesystems (CIFS/NFS), causing:
- Missing directories/files in containers
- Stale directory counts
- Files invisible even when present on NFS

**Solution:** Use Docker's native NFS volume driver (`driver: local`, `type: nfs` in driver_opts) instead of bind-mounting WSL-mounted network shares.

**Wrong approach:**
```yaml
volumes:
  - /mnt/nfs-mount:/recordings  # Bind mount - WILL CACHE
```

**Correct approach:**
```yaml
volumes:
  - nfs-volume:/recordings  # Docker NFS volume - NO CACHE

volumes:
  nfs-volume:
    driver: local
    driver_opts:
      type: nfs
      o: addr=server,vers=3,...
      device: ":/export/path"
```

---

## 6. Testing Manual Processing After Build

1. Start containers with updated image
2. Navigate to web UI at http://localhost:8000
3. Go to Manual Processing
4. Select a recording that already has captions
5. Add to manual processing queue
6. **Expected:** Status shows "Running" for 15+ minutes (Whisper processing)
7. **Previously (bug):** Status showed "Success" in 0.0 seconds (skipped)
8. Check logs: Should see "Removing existing SRT for reprocessing" message

---

## 7. Build Commands

### Quick Rebuild (Recommended - Avoids FFmpeg Compilation)

The full Dockerfile rebuild fails on FFmpeg compilation (missing nvcc in build stage). Use the quick rebuild instead:

```bash
# Quick rebuild using existing image as base (2 seconds vs 30+ minutes)
docker build -f Dockerfile.quickbuild -t py-captions-local:latest .

# Restart with new image
docker compose -f docker-compose.local.yml down
docker compose -f docker-compose.local.yml --env-file .env.local up -d
```

### Full Rebuild (If Needed)

Only use if you need to rebuild FFmpeg or update system dependencies:

```bash
# Full build - may fail on nvcc (CUDA compiler) in FFmpeg stage
docker build -t py-captions-local:latest .

# Or with docker compose
docker compose -f docker-compose.local.yml build
```

**Note:** The full Docker build currently fails because the FFmpeg build stage (`FROM ubuntu:22.04`) doesn't have CUDA toolkit installed, so `./configure --enable-cuda-nvcc` fails with "ERROR: failed checking for nvcc". The quick rebuild avoids this by using the existing working image as a base.

---

## Summary of Changes

- [x] watcher.py: Delete .srt before manual reprocessing
- [x] docker-compose.local.yml: Add NFS volume to web container
- [x] docker-compose.local.yml: Add CAPTION_COMMAND to web container
- [x] docker-compose.local.yml: Fix CHANNELS_API_URL for both containers
- [x] .env.local: Rename CHANNELS_DVR_URL to CHANNELS_API_URL
- [x] Documentation: NFS deployment pattern for separate file servers
- [x] NFS server: Update /etc/exports with proper options

**Impact:** Enables proper manual reprocessing of recordings, fixes web container manual processing, ensures reliable NFS deployment on Docker Desktop.
