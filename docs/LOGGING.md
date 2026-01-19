# Logging Improvements

This document describes the enhanced logging system in py-captions-for-channels, which provides job ID markers and configurable verbosity levels for better observability.

## Features

### 1. Job ID Markers

All log messages related to a specific recording are now prefixed with a job ID marker for easy visual separation and log parsing. Job IDs follow the format:

```
[Recording Title @ HH:MM:SS] Log message
```

For example:
```
[CNN News Central @ 22:01:16] Running caption pipeline: /tank/AllMedia/Channels/CNN_News_Central.ts
[CNN News Central @ 22:01:16] Caption pipeline completed for /tank/AllMedia/Channels/CNN_News_Central.ts
```

For reprocessed recordings, the marker includes `[REPROCESS]`:
```
[REPROCESS] CNN_News_Central.ts
```

### 2. Verbosity Levels

The logging system supports three verbosity levels controlled via the `LOG_VERBOSITY` environment variable:

| Level | Description | Output |
|-------|-------------|--------|
| `MINIMAL` | Only warnings and errors | Critical information only; silences info/debug messages |
| `NORMAL` (default) | Info and above | Standard operational logs; good for production monitoring |
| `VERBOSE` | Debug and above | Detailed diagnostic output; useful for troubleshooting |

## Configuration

### Environment Variables

```bash
# Set verbosity level (MINIMAL, NORMAL, or VERBOSE)
export LOG_VERBOSITY=NORMAL

# Docker Compose example (.env file)
LOG_VERBOSITY=VERBOSE
```

### Default Behavior

If `LOG_VERBOSITY` is not set, the system defaults to `NORMAL` (INFO level and above).

## Usage Examples

### Production Deployment (MINIMAL)

For production environments, use `MINIMAL` to focus only on critical issues:

```bash
export LOG_VERBOSITY=MINIMAL
python -m py_captions_for_channels
```

Output:
```
2026-01-19 22:01:16 [WARNING] py_captions_for_channels.webhook_source: Webhook validation failed for peer 192.168.1.100
2026-01-19 22:01:17 [ERROR] py_captions_for_channels.pipeline: Caption pipeline failed for /tank/AllMedia/Channels/show.ts (exit code 1)
```

### Standard Operations (NORMAL)

Default production setting showing key operational events:

```bash
python -m py_captions_for_channels
```

Output:
```
2026-01-19 22:01:16 [INFO] py_captions_for_channels.watcher: Processing reprocess queue: 1 items
[CNN News Central @ 22:01:16] [INFO] py_captions_for_channels.watcher: Reprocessing: /tank/AllMedia/Channels/CNN_News_Central.ts
[CNN News Central @ 22:01:16] [INFO] py_captions_for_channels.pipeline: Running caption pipeline: /tank/AllMedia/Channels/CNN_News_Central.ts
[CNN News Central @ 22:01:16] [INFO] py_captions_for_channels.pipeline: whisper output: Transcribed 1500 frames in 8.23s
[CNN News Central @ 22:01:16] [INFO] py_captions_for_channels.pipeline: Caption pipeline completed for /tank/AllMedia/Channels/CNN_News_Central.ts
```

### Debugging/Development (VERBOSE)

Enable debug output for detailed troubleshooting:

```bash
export LOG_VERBOSITY=VERBOSE
python -m py_captions_for_channels
```

Output includes:
```
2026-01-19 22:01:16 [DEBUG] py_captions_for_channels.channels_api: Fetching /api/v1/all (timeout=10)
2026-01-19 22:01:16 [DEBUG] py_captions_for_channels.parser: Parsed event: title=CNN News Central, start_time=2026-01-19 22:00:00
[CNN News Central @ 22:01:16] [DEBUG] py_captions_for_channels.pipeline: stdout: Model loaded in 0.34s
```

## Docker Deployment

### Docker Compose

Add the `LOG_VERBOSITY` variable to your `.env` file:

```env
# Production
LOG_VERBOSITY=NORMAL

# Development/Debugging
LOG_VERBOSITY=VERBOSE
```

The docker-compose.yml will read this automatically:

```yaml
services:
  py-captions:
    environment:
      - LOG_VERBOSITY=${LOG_VERBOSITY:-NORMAL}
```

### Runtime Override

Override the log verbosity at runtime:

```bash
docker-compose run --rm -e LOG_VERBOSITY=VERBOSE py-captions
```

## Implementation Details

### Core Components

1. **[logging_config.py](../py_captions_for_channels/logging_config.py)**
   - `JobIDFormatter`: Custom formatter that adds job ID markers
   - `VerbosityFilter`: Filters log records based on verbosity level
   - `set_job_id()`: Sets the current job ID for context tracking
   - `configure_logging()`: Initializes the logging system

2. **[__main__.py](../py_captions_for_channels/__main__.py)**
   - Initializes logging with configured verbosity level

3. **[pipeline.py](../py_captions_for_channels/pipeline.py)**
   - Sets job ID before executing caption command
   - Clears job ID after completion (finally block)

4. **[watcher.py](../py_captions_for_channels/watcher.py)**
   - Sets job ID for webhook events
   - Sets job ID for reprocess queue items
   - Proper cleanup with finally blocks

### Context Variables

The logging system uses Python's `contextvars.ContextVar` for thread-safe job ID tracking. This ensures:

- Job IDs work correctly in async/concurrent environments
- No cross-contamination between concurrent processing tasks
- Clean context cleanup after each job

## Future Enhancements

Potential improvements for Phase 2:

1. **Structured Logging**: JSON output format for log aggregation tools (ELK, Splunk)
2. **Metrics Collection**: Job duration, success rates, GPU utilization
3. **Log Rotation**: Automatic archival and compression of log files
4. **Remote Logging**: Send logs to external services (CloudWatch, DataDog)
5. **Job History API**: Query and filter past jobs via REST endpoint

## Testing

All logging features are covered by existing unit tests:

```bash
pytest tests/ -v
```

Current test coverage: 25 tests passing, all logging integration verified.

## Backward Compatibility

The logging improvements are fully backward compatible:

- Existing deployments work without configuration changes
- Default verbosity is `NORMAL` (INFO level)
- Job ID markers do not affect log parsing or analysis
- No changes required to existing scripts or automation
