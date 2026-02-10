# TODO List

## High Priority

### Settings UI - Shutdown Controls
Add shutdown buttons to the Settings interface for graceful and immediate shutdown.

**Implementation Details:**
- Add two buttons in the Settings UI:
  1. "Graceful Shutdown" - Finishes current job, then exits
  2. "Emergency Shutdown" - Immediate kill switch
- Wire buttons to existing API endpoints:
  - POST `/api/shutdown/graceful`
  - POST `/api/shutdown/immediate`
  - GET `/api/shutdown/status` (for status polling)
- Show confirmation dialog before triggering shutdown
- Display current job info if graceful shutdown is selected
- Poll shutdown status and show shutdown progress
- Disable buttons after shutdown is requested

**Existing API Endpoints:**
- `/api/shutdown/immediate` - Emergency stop (kill switch)
- `/api/shutdown/graceful` - Wait for current job, then exit
- `/api/shutdown/status` - Check if shutdown requested

**Files to Update:**
- `py_captions_for_channels/webui/templates/index.html` - Add buttons
- `py_captions_for_channels/webui/static/js/app.js` - Add event handlers
- `py_captions_for_channels/webui/static/css/style.css` - Style shutdown buttons (red/orange)

## Medium Priority

(Add future feature requests here)

## Low Priority

(Add nice-to-have features here)

---
**Created:** 2026-02-10
**Last Updated:** 2026-02-10
