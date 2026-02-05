# Manual Processing Refactor - Complete

## Summary
Successfully refactored the "reprocessing" feature into "manual processing" with recordings browser support.

## Changes Made

### Backend Files

#### 1. state.py ✓
- Renamed all methods from `reprocess` to `manual_process`:
  - `mark_for_reprocess()` → `mark_for_manual_process()`
  - `get_reprocess_queue()` → `get_manual_process_queue()`
  - `get_reprocess_settings()` → `get_manual_process_settings()`
  - `clear_reprocess_request()` → `clear_manual_process_request()`
- Renamed internal variable: `self.reprocess_paths` → `self.manual_process_paths`
- **Backward compatibility**: Still loads old `"reprocess_paths"` from state file
- Updated docstring to reflect "manual processing" purpose

#### 2. execution_tracker.py ✓
- Renamed function: `build_reprocess_job_id()` → `build_manual_process_job_id()`
- Updated job ID prefix: `"reprocess::"` → `"manual_process::"`

#### 3. watcher.py ✓
- Renamed function: `process_reprocess_queue()` → `process_manual_process_queue()`
- Renamed async loop: `_reprocess_loop()` → `_manual_process_loop()`
- Renamed task variable: `reprocess_task` → `manual_process_task`
- Updated all log messages from "reprocess" to "manual process"
- Changed execution kind: `"reprocess"` → `"manual_process"`
- Updated job title prefix: `"Reprocess:"` → `"Manual:"`
- Updated all comments referencing "reprocessing" to "manual processing"
- Updated import to use `build_manual_process_job_id`

#### 4. config.py ✓
- Added new config: `MANUAL_PROCESS_POLL_SECONDS` (reads from `MANUAL_PROCESS_POLL_SECONDS` env var)
- Kept `REPROCESS_POLL_SECONDS` as alias for backward compatibility
- Updated watcher.py to import and use `MANUAL_PROCESS_POLL_SECONDS`

#### 5. web_app.py ✓
- Updated import: `build_reprocess_job_id` → `build_manual_process_job_id`
- Renamed all API endpoints:
  - `/api/reprocess/candidates` → `/api/manual-process/candidates`
  - `/api/reprocess/add` → `/api/manual-process/add`
  - `/api/reprocess/remove` → `/api/manual-process/remove`
- Renamed functions:
  - `get_reprocess_candidates()` → `get_manual_process_candidates()`
  - `add_to_reprocess_queue()` → `add_to_manual_process_queue()`
  - `remove_from_reprocess_queue()` → `remove_from_manual_process_queue()`
- Updated all state backend method calls to use `manual_process` variants
- Updated status endpoint:
  - Changed response field: `"reprocess_queue_size"` → `"manual_process_queue_size"`
  - Updated documentation comment
- Updated execution deletion to check for `kind="manual_process"`
- Changed job title: `"Reprocess:"` → `"Manual:"`
- **NEW FEATURE**: Added `/api/recordings` endpoint
  - Fetches recordings from Channels DVR `/api/v1/all` endpoint
  - Returns formatted list with path, title, episode_title, date_added, etc.
  - Replaces old "candidates" approach with full recordings browser

### Frontend Files

#### 6. index.html ✓
- Updated status table label: "Reprocess Queue:" → "Manual Process Queue:"
- Updated status display ID: `reprocess-queue` → `manual-process-queue`
- Updated modal:
  - ID: `reprocess-modal` → `manual-process-modal`
  - Header: "Manage Reprocessing Queue" → "Manual Processing"
  - Description: Updated to "Browse recordings from Channels DVR and select items to process"
- Updated form controls:
  - IDs: `reprocess-*` → `manual-process-*`
  - Container: `reprocess-list` → `manual-process-list`
  - CSS classes: `reprocess-controls` → `manual-process-controls`
- Updated button onclick handlers:
  - `showReprocessModal()` → `showManualProcessModal()`
  - `closeReprocessModal()` → `closeManualProcessModal()`
  - `submitReprocessing()` → `submitManualProcessing()`

#### 7. main.js ✓
- Updated status display: `reprocess_queue_size` → `manual_process_queue_size`
- Updated execution list rendering:
  - Kind check: `'reprocess'` → `'manual_process'`
  - Tag label: "Reprocess" → "Manual"
  - Detail type: "Reprocess" → "Manual Processing"
- Renamed functions:
  - `showReprocessModal()` → `showManualProcessModal()`
  - `closeReprocessModal()` → `closeManualProcessModal()`
  - `submitReprocessing()` → `submitManualProcessing()`
  - `removeFromReprocessQueue()` → `removeFromManualProcessQueue()`
- **Major functionality change** in `showManualProcessModal()`:
  - Changed from `/api/reprocess/candidates` to `/api/recordings`
  - Now fetches full recordings list from Channels DVR API
  - Shows recordings with title, episode title, and date added
  - Removed old "success/error" status icons (not applicable for recordings browser)
- Updated all checkbox names: `reprocess-path` → `manual-process-path`
- Updated all CSS classes: `reprocess-*` → `manual-process-*`
- Updated all API endpoints to `/api/manual-process/*`
- Updated all alert messages to use "manual process" terminology

## API Changes

### Old Endpoints (removed)
- `GET /api/reprocess/candidates` - Returned previously processed executions
- `POST /api/reprocess/add` - Added paths to reprocess queue
- `POST /api/reprocess/remove` - Removed path from reprocess queue

### New Endpoints
- `GET /api/recordings` - **NEW**: Browse all recordings from Channels DVR
- `GET /api/manual-process/candidates` - Get previously processed executions (kept for compatibility)
- `POST /api/manual-process/add` - Add paths to manual process queue
- `POST /api/manual-process/remove` - Remove path from manual process queue

## State File Compatibility

The state backend maintains backward compatibility:
- Still loads old `"reprocess_paths"` key from existing state files
- Automatically migrates to `"manual_process_paths"` on next save
- No manual migration required

## Environment Variables

New (recommended):
- `MANUAL_PROCESS_POLL_SECONDS` - Polling interval for manual process queue (default: 10)

Old (still supported):
- `REPROCESS_POLL_SECONDS` - Legacy name, mapped to `MANUAL_PROCESS_POLL_SECONDS`

## Testing Recommendations

1. **Backend**:
   - Test `/api/recordings` endpoint fetches from Channels DVR
   - Test `/api/manual-process/add` adds items to queue
   - Test `/api/manual-process/remove` removes items
   - Test watcher processes manual queue correctly
   - Verify state file backward compatibility

2. **Frontend**:
   - Open web UI, verify "Manual Process Queue" label displays
   - Click "Manage" button, verify recordings browser modal opens
   - Verify recordings list loads from Channels DVR
   - Select recordings, verify submission adds to queue
   - Check execution list shows "Manual" tags correctly

3. **Integration**:
   - Add recordings via web UI
   - Verify they appear in manual process queue
   - Watch logs for "Processing manual process queue" messages
   - Verify executions complete and log correctly

## Migration Guide

No action required! The refactor is fully backward compatible:
- Existing state files will load automatically
- Old environment variables still work
- API endpoints cleanly replaced (clients should update URLs)

## Next Steps

- Test locally with Docker containers
- Verify recordings browser works with niu server
- Add search/filter to recordings browser (future enhancement)
- Add file system browser option (future enhancement)
