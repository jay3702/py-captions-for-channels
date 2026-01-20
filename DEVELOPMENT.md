# Development Status & Roadmap

**Current Version Estimate: 0.7**

## Project Summary

`py-captions-for-channels` is a production-grade video caption automation system for Channels DVR recordings. It monitors incoming webhook events, generates captions using OpenAI's Whisper, optionally transcodes to Fire TV format using GPU acceleration, and tracks processing state with persistence and recovery.

---

## ✅ Implemented Features (v0.7)

### Core Pipeline
- **Event Sources**: Webhook endpoint + legacy WebSocket support (Channels ChannelWatch)
- **Caption Generation**: OpenAI Whisper (medium model) with SRT output
- **Transcoding**: Optional Fire TV MP4 transcoding with burned-in subtitles using NVIDIA NVENC GPU acceleration
- **State Management**: JSON-backed atomic writes with persistent last-processed timestamp
- **Whitelist Filtering**: Title-based allow/deny rules with regex pattern support (auto-detects operators, falls back to substring)

### Processing Features
- **Reprocessing Queue**: Manual reprocessing via CLI with state persistence
- **Path Safety**: Proper shell quoting (`shlex.quote()`) for titles with special characters
- **Webhook Robustness**: Graceful handling of malformed payloads (missing status field)
- **DRY-RUN Mode**: Safe testing without actual transcoding

### Logging & Observability
- **Job ID Markers**: Each recording processing tagged with `[Title @ HH:MM:SS]` for log correlation
- **Verbosity Levels**: MINIMAL (warnings/errors only), NORMAL (info), VERBOSE (debug)
- **Dual Output**: Logs to both stdout and persistent file (`/app/logs/app.log`)
- **Incremental Log Parsing**: Health check utility parses new entries only (tracks offset)

### Health Monitoring
- **Health Check Script**: Compares processed recordings in log vs filesystem artifacts
  - Reports: processed OK, missing outputs (.mpg/.srt), unprocessed candidates
  - Incremental mode (uses offset) or lookback mode (last N days)
- **Validation**: 38 comprehensive unit tests (all passing)

### Deployment
- **Docker**: Multi-stage build with NVIDIA CUDA base + nvidia-container-toolkit GPU support
- **Configuration**: Environment variables for all settings (`.env` or docker-compose)
- **GPU Acceleration**: NVIDIA NVENC h264 encoder achieving 14.8–23.9x realtime (5x faster than CPU)
- **Production Tested**: Running on QNAP NAS with RTX 2080 Ti

### Quality Assurance
- **Code Quality**: Black formatter, flake8 linter (0 violations)
- **Test Coverage**: 38 tests covering pipeline, state, parser, channels API, whitelist, webhook
- **CI/CD**: GitHub Actions with automated testing, formatting, linting on each push

---

## 🚧 Partially Implemented

- **Monitoring & Alerting** (Feature #5): Not prioritized; infrastructure exists for future implementation

---

## 📋 Not Yet Implemented (Future Roadmap)

### Phase 1: Web GUI (UI Layer)
- [ ] **Real-time Log Viewer**: FastAPI + WebSocket streaming of live logs with job markers
- [ ] **Config Editor**: UI for whitelist, verbosity, log level, enable/disable processing
- [ ] **Status Dashboard**: Job history, success/failure rates, GPU utilization, processing speed (realtime/speed ratio)

### Phase 2: Observability & Operations
- [ ] **Metrics Collection**: Job duration, success rates, GPU memory/utilization, throughput
- [ ] **Structured Logging**: JSON format for log aggregation tools (ELK, Splunk, DataDog)
- [ ] **Log Rotation**: Automatic archival and compression of old log files
- [ ] **Remote Logging**: Send logs to external services (CloudWatch, DataDog, Sentry)

### Phase 3: Advanced Features
- [ ] **Monitoring & Alerting** (Feature #5): Email/Slack alerts on failures, GPU overtemp, disk full
- [ ] **Retry Logic**: Exponential backoff for transient failures (API timeouts, network issues)
- [ ] **Batch Processing**: Process multiple recordings in parallel
- [ ] **Custom Captions**: Support alternative caption engines (other Whisper models, commercial APIs)
- [ ] **Database Backend**: Replace JSON state with SQLite/PostgreSQL for scalability

### Phase 4: Performance & Optimization
- [ ] **Adaptive Quality**: Adjust Whisper model (tiny/base/small/medium) based on runtime constraints
- [ ] **Caching**: Cache captions across similar recordings (e.g., same show, same recording setup)
- [ ] **Incremental Transcoding**: Skip re-transcoding if caption file already exists

---

## 📊 Version History

| Version | Date | Highlights |
|---------|------|-----------|
| **0.1** | Jan 18, 2026 | Initial project setup, Whisper integration, basic webhook |
| **0.2** | Jan 18 | Test suite foundation (25 tests), black/flake8 automation |
| **0.3** | Jan 19 | Feature #4: Reprocessing CLI, Feature #6: GPU NVENC encoding |
| **0.4** | Jan 19 | Bug fix: Path quoting for spaces in titles, production verified |
| **0.5** | Jan 19 | Logging improvements: Job ID markers, verbosity levels |
| **0.6** | Jan 20 | Regex whitelist support, webhook robustness, health check script |
| **0.7** | Jan 20 | File logging, persistent logs, docker-compose environment setup |
| **0.8** (planned) | — | Web GUI Phase 1 (real-time log viewer, config editor) |

---

## 🎯 Development Velocity & Estimation

**Lines of Code**: ~1,500 (core) + ~500 (scripts) + ~800 (tests)  
**Commits to v0.7**: 15+ feature/fix commits  
**Test Coverage**: 38 tests (comprehensive for core pipeline, state, API, whitelist)  
**Documentation**: Inline docstrings, README, LOGGING.md, SETUP.md  

**Estimated Path to 1.0:**
- **v0.8** (1–2 weeks): Web GUI Phase 1 (log viewer, config editor)
- **v0.9** (1 week): Metrics & structured logging
- **v1.0** (1 week): Production hardening, monitoring/alerting, release notes

---

## 🔧 Current Deployment

**Environment**: QNAP NAS (niu, 192.168.3.150)  
**Hardware**: RTX 2080 Ti, 32GB RAM  
**Status**: ✅ Fully operational, processing news/entertainment recordings  
**Processing Rate**: 14.8–23.9x realtime (GPU-accelerated)  
**Uptime**: Continuous (restart unless-stopped policy)  
**Log Location**: `/tank/AllMedia/Channels/logs/app.log`  

---

## 📝 Next Steps

1. **v0.8 (Near-term)**: Implement FastAPI web GUI with real-time log viewer and config editor
2. **Monitoring**: Add Slack/email alerting for processing failures, disk/GPU alerts
3. **Metrics**: Collect and expose job statistics (duration, throughput, success rate)
4. **Scaling**: Consider batch processing for multiple recordings concurrently

---

## Key Design Decisions

- **Async-first**: Python asyncio for webhook handling and pipeline orchestration
- **File-backed state**: JSON for persistence + atomic writes for safety (no database needed at this scale)
- **GPU-first**: NVIDIA NVENC as default for Fire TV transcoding (5x speedup vs CPU)
- **Defensive logging**: Job markers + verbosity levels + file output for observability
- **Graceful degradation**: Invalid regex patterns, malformed webhooks, missing files don't crash the system

---

## Testing & Quality

- **Unit Tests**: 38 tests covering pipeline, state, parser, API, whitelist, webhook
- **Code Quality**: Black formatter + flake8 linter (0 violations)
- **CI/CD**: GitHub Actions on every push (test, format, lint)
- **Production Verified**: Tested on real DVR recordings, GPU transcoding validated

---

## Known Limitations

1. **Single Job Processing**: Processes one recording at a time (could parallelize in Phase 3)
2. **No Database**: JSON state is simple but not suitable for thousands of recordings (SQL backend planned for Phase 3)
3. **Limited Retry**: No exponential backoff for transient API failures (add in Phase 3)
4. **Hardcoded Whisper Model**: Uses `medium` model; could make configurable (Phase 3)
5. **No Monitoring**: No alerts for failures or resource issues (Phase 2)

---

## Success Metrics

✅ **Achieved**:
- 25→38 tests passing consistently
- Zero linting/formatting violations
- GPU encoding 5x faster than CPU
- Production deployment stable (>24h uptime)
- Path quoting handles edge cases (spaces, special chars)

🎯 **In Progress**:
- Persistent logging with health checks
- Regex whitelist support with fallback

📋 **Planned**:
- Web GUI (v0.8)
- Metrics & monitoring (v0.9)
- Release v1.0

---

**Last Updated**: January 20, 2026  
**Maintained By**: GitHub Copilot  
**Repository**: [jay3702/py-captions-for-channels](https://github.com/jay3702/py-captions-for-channels)
