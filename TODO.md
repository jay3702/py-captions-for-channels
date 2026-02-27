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

### AI-Assisted Whitelist Generation
Simplify whitelist creation by letting users select desired/undesired recordings, then using AI to generate optimal regex patterns.

**User Workflow:**
1. Browse recordings in manual processing interface
2. Mark recordings as "Want" (✓) or "Don't Want" (✗)
3. Click "Generate Whitelist" button
4. AI analyzes titles and creates concise regex patterns
5. Preview generated whitelist with explanations
6. Accept/edit/refine the generated rules

**AI Analysis:**
- **Input**: List of desired titles vs undesired titles
  ```
  Desired: ["CNN News Central", "NBC Bay Area News at 11", "The Daily Show", ...]
  Undesired: ["Infomercial", "Paid Programming", "Shopping", ...]
  ```

- **AI Task**: Generate minimal regex patterns that:
  - Match all desired titles
  - Exclude all undesired titles
  - Group similar shows efficiently (e.g., "News" catches many)
  - Use appropriate specificity (broad vs narrow patterns)

- **Output**: Whitelist rules with confidence scores
  ```
  News                    # Matches 15 desired, 0 undesired (confidence: 1.0)
  ^CNN                    # Matches 8 desired, 0 undesired (confidence: 1.0)
  The Daily Show          # Exact match (confidence: 1.0)
  60 Minutes              # Exact match (confidence: 1.0)
  ```

**Implementation Details:**
- Add selection checkboxes to manual processing UI
- Store user preferences (desired/undesired flags)
- AI prompt: "Given these desired/undesired titles, generate minimal whitelist rules"
- Validate generated patterns against both lists
- Show coverage stats (X of Y titles matched)
- Allow iterative refinement (add more examples, regenerate)

**Benefits:**
- No regex knowledge required from users
- Optimal pattern efficiency (minimal rules, maximum coverage)
- Catches common patterns users might miss
- Safe validation before applying

**Advanced Features (future):**
- Learn from historical processing (auto-suggest based on completed jobs)
- Time-based patterns (e.g., "News;Friday;21:00")
- Channel-specific rules
- Negative patterns (explicit exclusions)

(Add other future feature requests here)

## Low Priority

(Add nice-to-have features here)

---

## Post-v1 Features

### Channels Files Audit (Experimental — Implemented)
Cross-reference the Channels DVR `/dvr/files` API with the actual filesystem to detect discrepancies. Gated behind `CHANNELS_FILES_ENABLED=true`.

**Current capabilities (v1):**
- 3-phase audit: index API records → check for missing files → scan for orphaned files
- SSE streaming progress with cancellation support
- Summary cards, missing/orphaned/empty-folder tables in UI
- Feature flag gating (`CHANNELS_FILES_ENABLED`)

**Suggested future enhancements:**
1. **File modification dates & sorting** — Add mtime to orphan records so users can correlate orphans with known events (disk failures, manual cleanups)
2. **Grouping by show/folder** — Aggregate missing and orphaned counts per series/folder to identify which shows are most affected
3. **Delete stale API records** — For confirmed-missing files, call `DELETE /dvr/files/{id}` to clean up Channels DVR's database
4. **Quarantine orphaned files** — Integrate with the existing quarantine system to safely move orphans before permanent deletion
5. **Scheduled/periodic audits** — Run audits on a timer (like orphan cleanup) and alert on new discrepancies
6. **Export report** — CSV/JSON download of audit results for offline analysis
7. **Size breakdown** — Show total disk usage per category (missing vs orphaned) and per-show sizes
8. **Diff between runs** — Track audit results over time and highlight what changed since the last audit
9. **Selective re-import** — For orphaned files that look like valid recordings, offer to re-register them with Channels DVR

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
