# Deployment to niu (Server)

## Critical Bug Fixes Included
- **SRT Clamping Bug**: Fixed `clamp_srt_to_end()` to preserve sequence numbers and write final cue
- **Timezone Issues**: Replaced `datetime.now()` with `datetime.now(timezone.utc)` across codebase

## Deployment Steps on niu

### 1. SSH to Server
```bash
ssh jay@niu
cd ~/py-captions-for-channels
```

### 2. Pull Latest Changes
```bash
git pull origin main
```

### 3. Rebuild and Restart Container
```bash
# Stop current container
docker compose down

# Rebuild with latest code
docker compose build --no-cache

# Start container
docker compose up -d
```

### 4. Verify Deployment
```bash
# Check container is running
docker ps | grep py-captions

# Check logs
docker logs py-captions-for-channels-py-captions-1 --tail 50

# Verify web UI is accessible
curl http://localhost:8000/health
```

### 5. Test with Existing Recording

Remove any malformed SRT files from previous tests:
```bash
# Find and remove SRT files that were created during buggy clamping
find /path/to/recordings -name "*.srt" -type f -newer /path/to/some/reference/file -delete
```

Or test with a fresh recording.

### 6. Monitor First Execution

Watch the logs during the first recording processing:
```bash
docker logs -f py-captions-for-channels-py-captions-1
```

Expected flow:
1. File stability check (30 seconds)
2. Whisper caption generation (~55 min for 1-hour video with base model)
3. Preserve original (.orig backup)
4. Encode video-only MP4 (CPU fallback if no GPU)
5. Probe durations
6. **Clamp SRT** (should now preserve sequence numbers)
7. **Mux subtitles** (should succeed without "Invalid data" error)
8. Verify durations
9. Atomic replace (final .mpg has embedded subs)

## Expected Result

The pipeline should complete successfully with:
- `.mpg.orig` - Original file backup
- `.srt` - Properly formatted subtitle file
- `.mpg` - Final file with embedded subtitles

Check the final file:
```bash
ffprobe -v error -select_streams s:0 -show_entries stream=codec_name,index /path/to/recording.mpg
```

Should show: `codec_name=mov_text`

## Troubleshooting

If the pipeline still fails:
1. Check SRT file format: `head -20 /path/to/file.srt`
   - Should have sequence numbers (1, 2, 3...)
   - Should have timestamps in format `HH:MM:SS,mmm --> HH:MM:SS,mmm`
   - Should have blank lines between entries

2. Check executions.json for detailed error messages:
   ```bash
   docker exec py-captions-for-channels-py-captions-1 cat /app/data/executions.json | python -m json.tool | tail -100
   ```

3. Test FFmpeg mux manually:
   ```bash
   docker exec py-captions-for-channels-py-captions-1 ffmpeg -y \
     -i /path/to/file.mpg.av.mp4 \
     -i /path/to/file.srt \
     -c:v copy -c:a copy -c:s mov_text \
     -map 0:v -map 0:a? -map 1 \
     -movflags +faststart \
     /path/to/test_output.mp4
   ```

## Performance Note

Server should perform significantly better than laptop for Whisper processing due to:
- Better CPU/GPU resources
- No container performance overhead from WSL2
- Direct hardware access vs virtualization layer

Expect ~55 minutes for 1-hour video with base model on server vs 2-3x longer on laptop.
