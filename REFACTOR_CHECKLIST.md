# Manual Processing Refactor - Changes Summary

## Completed:
✅ state.py - All methods renamed from reprocess to manual_process

## Remaining:

### watcher.py:
- Rename process_reprocess_queue() → process_manual_process_queue()
- Update all references to state.get_reprocess_queue() → state.get_manual_process_queue()
- Update all references to state.clear_reprocess_request() → state.clear_manual_process_request()  
- Update all references to state.get_reprocess_settings() → state.get_manual_process_settings()
- Update log messages: "reprocess" → "manual process"
- Update kind="reprocess" → kind="manual_process"

### execution_tracker.py:
- Rename build_reprocess_job_id() → build_manual_process_job_id()

### web_app.py:
- Rename /api/reprocess/* endpoints → /api/manual-process/*
- Add new endpoint: GET /api/recordings (fetch from Channels DVR API)
- Update all state.mark_for_reprocess() → state.mark_for_manual_process()
- Update all state.get_reprocess_queue() → state.get_manual_process_queue()

### index.html:
- Rename "Reprocess" section → "Manual Processing"
- Add recordings browser UI with search/filter
- Update API endpoints from /api/reprocess/* → /api/manual-process/*

### main.js:
- Update all fetch calls to use /api/manual-process/*
- Add recordings browser functionality
- Add recording selection and queue management
