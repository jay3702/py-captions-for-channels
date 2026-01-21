# Deployment Checklist

## ? Pre-Deployment Complete
- [x] Old services stopped (channels-watcher.service/timer)
- [ ] ChannelWatch notification webhook ready to update
- [ ] Docker installed on target server

---

## Deployment Steps

### 1. SSH to Your Server
```bash
ssh user@<SERVER_IP>
```

### 2. Clone repository
```bash
cd /share/Container
git clone https://github.com/jay3702/py-captions-for-channels.git
cd py-captions-for-channels
```

### 3. Create .env file
```bash
cp .env.example .env
nano .env
```

**Update these values in .env:**
```bash
CHANNELS_API_URL=http://localhost:8089
DVR_RECORDINGS_PATH=/tank/AllMedia/Channels
CAPTION_COMMAND=/usr/local/bin/whisper --model medium {path}
DRY_RUN=true  # Start with dry-run for testing
```

### 4. Create directories
```bash
mkdir -p data logs
```

### 5. Start container
```bash
docker-compose up -d
```

### 6. View logs
```bash
docker-compose logs -f
```

### 7. Update ChannelWatch
1. Open: `http://<CHANNELWATCH_SERVER>:8501`
2. Go to: **Settings ? Notification Providers**
3. Enable: **Custom URL**
4. Set URL: `json://localhost:9000`
5. Save

### 8. Test
- Trigger a short recording
- Watch logs: `docker-compose logs -f`
- Verify event received and path lookup works

### 9. Go Live
When ready for production:
```bash
# Edit .env and set DRY_RUN=false
nano .env

# Restart container
docker-compose down
docker-compose up -d
```

---

## Verification Commands

```bash
# Check container status
docker-compose ps

# View recent logs
docker-compose logs --tail=50

# Check webhook port
netstat -tuln | grep 9000

# Test webhook manually
curl -X POST http://localhost:9000 \
  -H "Content-Type: application/json" \
  -d '{"version":"1.0","title":"Test","message":"Test\nStatus: ?? Stopped\nProgram: Test Show"}'
```

---

## Troubleshooting

**Container won't start:**
```bash
docker-compose logs
docker-compose config  # Verify configuration
```

**Not receiving webhooks:**
```bash
# Check if port is accessible
netstat -tuln | grep 9000

# Verify ChannelWatch config
curl http://localhost:8501
```

**Can't find recordings:**
```bash
# Check volume mount
docker exec -it py-captions-for-channels ls -la /recordings

# Verify DVR_RECORDINGS_PATH in .env matches actual path
```

---

## Next Steps After Deployment

- [ ] Monitor for 24 hours
- [ ] Verify captions are being generated
- [ ] Check disk space usage
- [ ] Set up backup of ./data directory
- [ ] Consider adding monitoring/alerts
