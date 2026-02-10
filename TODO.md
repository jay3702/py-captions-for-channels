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

## Post-v1 Features

### AI-Assisted Video Format Detection & Configuration
Automatically detect and handle diverse video encoding formats using AI and a learning knowledge base.

**Concept:**
Instead of hardcoding format-specific handling, use AI to suggest optimal ffmpeg parameters for unknown video formats, then cache successful configurations in a database.

**Implementation Approach:**
1. **Enhanced Metadata Collection**: Extract comprehensive video metadata fingerprint
   - Container, codecs, frame rates, timebases, color space, encoder tags
   - Create signature hash for format matching
   
2. **Knowledge Base (SQLite)**: Store proven configurations
   ```sql
   format_configurations (
     signature_hash, metadata_json, ffmpeg_params,
     success_count, failure_count, confidence,
     ai_suggested, last_used, notes
   )
   ```

3. **AI Consultation**: For unknown formats, query LLM with metadata
   - Prompt: "Given this video metadata, suggest ffmpeg params for subtitle embedding without transcoding"
   - Validate AI suggestions against whitelist of safe parameters
   - Optional dry-run testing before production use

4. **Learning Loop**: Track success/failure, update confidence scores
   - System gets smarter over time
   - High-confidence configs become permanent
   - Failed configs are flagged for manual review

**Benefits:**
- Self-learning system handles new formats automatically
- No code changes needed for new encoding sources
- AI only called for unknown formats (cached after first success)
- Safe with validation and dry-run modes
- Could enable community sharing of configurations

**Challenges to Address:**
- AI hallucinations (validate against safe parameter whitelist)
- Format variation granularity (fuzzy matching vs exact signatures)
- API costs (aggressive caching, optional local LLM)
- Validation strategy (how to verify AI suggestion worked)

**Implementation Phases:**
1. Phase 1: Enhanced metadata logging (analyze what formats appear in wild)
2. Phase 2: Manual knowledge base population (document known formats)
3. Phase 3: AI integration as optional experimental feature
4. Phase 4: Full learning loop with confidence scoring
5. Phase 5: Optional community config sharing

**Use Case:**
When users process personal libraries with recordings from DVRs, capture cards, streaming services, screen capture tools (cc4c, OBS, etc), the system automatically determines optimal embedding parameters instead of requiring manual configuration or code updates.

---
**Created:** 2026-02-10
**Last Updated:** 2026-02-10
