# Test Suite Integration & Language Selection - Implementation Plan

## Overview

Two major features to implement:
1. **Test Suite Integration**: UI-driven ffmpeg profile testing and learning
2. **Language Selection**: Primary feature for audio/subtitle track language filtering

---

## Feature 1: Test Suite Integration

### Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend: Test Suite Tab                                     │
│ - Recording selector (reuse RecordingTable)                  │
│ - Test execution controls                                    │
│ - Results viewer with variant comparison                     │
│ - File swap/restore actions                                  │
│ - Profile learning workflow                                  │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ Backend API: /api/test-suite/*                               │
│ - POST /api/test-suite/run                                   │
│ - GET  /api/test-suite/status/{job_id}                       │
│ - GET  /api/test-suite/results/{job_id}                      │
│ - POST /api/test-suite/swap-file                             │
│ - POST /api/test-suite/restore                               │
│ - POST /api/test-suite/save-profile                          │
│ - GET  /api/learned-profiles                                 │
│ - DELETE /api/learned-profiles/{id}                          │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ Business Logic: TestSuiteRunner                              │
│ - Prepare .orig backup                                       │
│ - Execute tools.ffmpeg_test_suite                            │
│ - Track progress in database                                 │
│ - Parse JSON results                                         │
│ - Manage file swaps and restore chain                        │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ Database: learned_profiles table                             │
│ - signature_hash (unique fingerprint)                        │
│ - signature_data (JSON: codec, res, fps, etc.)              │
│ - profile_name + variant_name (optimal config)              │
│ - performance_data (elapsed, size, real-time factor)        │
│ - usage tracking (times_used, last_used_at)                 │
└─────────────────────────────────────────────────────────────┘
```

### Database Schema (Already Complete)

**learned_profiles table:**
- `id`: Primary key
- `signature_hash`: SHA256 of canonical signature JSON (unique index)
- `signature_data`: JSON with video characteristics
- `profile_name`: e.g., "ota_hd_60fps_5.1"
- `variant_name`: Test suite variant that won
- `performance_data`: JSON with metrics
- `ffmpeg_command`: Reference command used
- `times_used`: Usage counter
- `created_at`, `last_used_at`: Timestamps
- `notes`: User annotations

**Signature Components:**
```json
{
  "video_codec": "mpeg2video",
  "audio_codec": "ac3",
  "width": 1280,
  "height": 720,
  "fps": "59.94",
  "field_order": "progressive",
  "audio_channels": 6,
  "channel_number": "4.1",
  "container": "mpegts",
  "duration": 3659.21,
  "bitrate": 5500000
}
```

### Backend Implementation

#### 1. File Management Module (`py_captions_for_channels/test_suite_manager.py`)

**Purpose:** Handle file operations for test suite workflow

```python
class TestSuiteFileManager:
    """Manages file backup, swap, and restore for test suite."""
    
    def ensure_orig_backup(recording_path: Path) -> Path:
        """
        Create .orig backup if doesn't exist.
        Returns path to .orig file.
        """
        
    def swap_recording(recording_path: Path, test_variant_path: Path) -> dict:
        """
        Swap current .mpg with test variant.
        Maintains restore chain:
        - .mpg.test_backup (current .mpg before swap)
        - .mpg (now test variant)
        Returns metadata about swap.
        """
        
    def restore_original(recording_path: Path) -> bool:
        """
        Restore .mpg from .orig backup.
        Cleans up test artifacts.
        """
        
    def restore_previous(recording_path: Path) -> bool:
        """
        Restore .mpg from .test_backup (undo last swap).
        """
        
    def get_file_status(recording_path: Path) -> dict:
        """
        Return status of all related files:
        {
            "recording_exists": bool,
            "recording_size": int,
            "orig_exists": bool,
            "orig_size": int,
            "test_backup_exists": bool,
            "test_variants": [
                {"name": "...__VARIANT.mpg", "size": int, "path": str}
            ],
            "can_restore_orig": bool,
            "can_restore_previous": bool
        }
        """
        
    def cleanup_test_artifacts(recording_path: Path, keep_orig: bool = True):
        """
        Remove all test suite artifacts:
        - .test_backup
        - test variant .mpg files
        - test suite log files
        Optionally keep .orig backup.
        """
```

#### 2. Test Suite Runner (`py_captions_for_channels/test_suite_runner.py`)

**Purpose:** Execute test suite and track progress

```python
class TestSuiteRunner:
    """Executes test suite and manages lifecycle."""
    
    def __init__(self, db_session, execution_service, progress_service):
        self.db = db_session
        self.exec_service = execution_service
        self.progress = progress_service
        self.file_mgr = TestSuiteFileManager()
    
    async def run_test_suite(
        recording_path: str,
        srt_path: str,
        output_dir: str,
        limit_variants: Optional[List[str]] = None,
    ) -> str:
        """
        Start test suite execution async.
        Returns job_id for tracking.
        
        Steps:
        1. Create execution record (status='running')
        2. Ensure .orig backup exists
        3. Launch ffmpeg_test_suite as subprocess
        4. Poll subprocess, update progress
        5. Parse JSON results on completion
        6. Update execution with results
        """
        
    def get_test_results(job_id: str) -> Optional[dict]:
        """
        Get parsed test results from execution.
        Returns None if not complete.
        """
        
    def compute_signature(video_path: str) -> dict:
        """
        Use ffprobe to extract signature data.
        Matches LearnedProfile.signature_data format.
        """
```

#### 3. API Endpoints (`py_captions_for_channels/web_app.py`)

Add new router section:

```python
# Test Suite Integration
@app.post("/api/test-suite/run")
async def run_test_suite(request: TestSuiteRunRequest):
    """
    Start test suite execution.
    
    Body:
    {
        "recording_path": "/path/to/recording.mpg",
        "variants": ["VARIANT_A", "VARIANT_B"] // optional
    }
    
    Returns:
    {
        "job_id": "test_suite::recording.mpg::20260223-120000",
        "status": "running",
        "output_dir": "/path/to/test-results"
    }
    """

@app.get("/api/test-suite/status/{job_id}")
async def get_test_status(job_id: str):
    """
    Poll test suite progress.
    
    Returns:
    {
        "job_id": "...",
        "status": "running" | "completed" | "failed",
        "progress_percent": 45.2,
        "current_variant": "VARIANT_C",
        "variants_completed": 2,
        "variants_total": 6
    }
    """

@app.get("/api/test-suite/results/{job_id}")
async def get_test_results(job_id: str):
    """
    Get full test results.
    
    Returns JSON report from ffmpeg_test_suite with additional metadata:
    {
        "job_id": "...",
        "recording_path": "...",
        "signature": {...},
        "variants": [
            {
                "name": "COPY_H264_OR_HEVC__MP4_MOVTEXT",
                "status": "passed",
                "elapsed_seconds": 85.2,
                "file_size_bytes": 1150000000,
                "output_path": ".../__COPY_H264_OR_HEVC__MP4_MOVTEXT.mpg",
                "codecs": {"video": "h264", "audio": "aac", "subtitle": "mov_text"},
                "real_time_factor": 7.2
            },
            ...
        ],
        "recommended": "TRANSCODE_MPEG2_TO_H264_NVENC__MP4_MOVTEXT__AAC_HP"
    }
    """

@app.post("/api/test-suite/swap-file")
async def swap_test_file(request: SwapFileRequest):
    """
    Replace current .mpg with test variant.
    
    Body:
    {
        "recording_path": "/path/to/recording.mpg",
        "variant_path": "/path/to/recording__VARIANT.mpg"
    }
    
    Returns:
    {
        "success": bool,
        "backup_path": "/path/to/recording.mpg.test_backup",
        "message": "Swapped successfully. Use Channels client to test."
    }
    """

@app.post("/api/test-suite/restore")
async def restore_recording(request: RestoreRequest):
    """
    Restore recording to original or previous state.
    
    Body:
    {
        "recording_path": "/path/to/recording.mpg",
        "restore_to": "original" | "previous"
    }
    """

@app.post("/api/test-suite/save-profile")
async def save_learned_profile(request: SaveProfileRequest):
    """
    Save optimal variant as learned profile.
    
    Body:
    {
        "recording_path": "/path/to/recording.mpg",
        "variant_name": "TRANSCODE_MPEG2_TO_H264_NVENC__MP4_MOVTEXT__AAC_HP",
        "profile_name": "ota_hd_60fps_5.1",
        "notes": "Optimal for channel 4.1 interlaced content"
    }
    
    Computes signature, saves to learned_profiles table.
    """

@app.get("/api/learned-profiles")
async def list_learned_profiles():
    """
    List all learned profiles with usage stats.
    """

@app.delete("/api/learned-profiles/{profile_id}")
async def delete_learned_profile(profile_id: int):
    """
    Delete a learned profile.
    """

@app.get("/api/test-suite/file-status")
async def get_file_status(recording_path: str):
    """
    Get status of recording and related files.
    Used by UI to show available actions.
    """
```

### Frontend Implementation

#### 1. Settings Toggle (`py_captions_for_channels/webui/templates/settings.html`)

Add checkbox in Advanced section:

```html
<div class="form-group">
    <label>
        <input type="checkbox" id="test_suite_enabled" />
        Enable Test Suite (Experimental)
    </label>
    <p class="help-text">
        Advanced feature for testing ffmpeg encoding profiles.
        Adds "Test Suite" tab to interface.
    </p>
</div>
```

#### 2. New Tab (`py_captions_for_channels/webui/templates/test-suite.html`)

**Layout:**

```
┌────────────────────────────────────────────────────────────┐
│ Test Suite: Optimize Encoding Profiles                     │
├────────────────────────────────────────────────────────────┤
│                                                             │
│ Step 1: Select Recording                                   │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ [Search box]                     [Filter: All ▼]       │ │
│ ├────────────────────────────────────────────────────────┤ │
│ │ Recording Title          | Duration | Size   | Channel │ │
│ │ ○ Entertainment Tonight  | 01:00:59 | 3.1 GB | 4.1     │ │
│ │ ○ Local News             | 00:30:00 | 1.5 GB | 11.1    │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                             │
│ Step 2: Configure Test                                     │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ Variants to test: [All (6) ▼]                          │ │
│ │                                                         │ │
│ │ ☑ A. Copy H.264/HEVC (fast, no re-encode)              │ │
│ │ ☑ B. Copy video + AAC audio                            │ │
│ │ ☑ C. NVENC p1 preset (speed-first)                     │ │
│ │ ☑ D. NVENC hp preset (balanced)                        │ │
│ │ ☑ E. CUVID + deinterlace (for 1080i)                   │ │
│ │ ☑ F. MKV container test                                │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                             │
│ [⚡ Start Test Suite]                                       │
│                                                             │
│ Step 3: Results (after test completes)                     │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ Variant            | Status | Time  | Size  | Action   │ │
│ │ A. Copy H.264      | PASSED | 85s   | 1.1GB | [Test]   │ │
│ │ B. Copy + AAC      | PASSED | 95s   | 1.1GB | [Test]   │ │
│ │ C. NVENC p1        | PASSED | 612s  | 1.1GB | [Test]   │ │
│ │ D. NVENC hp    ★   | PASSED | 643s  | 1.1GB | [Test]   │ │
│ │ E. CUVID+deint     | FAILED | -     | -     | [Logs]   │ │
│ │ F. MKV             | SKIPPED| -     | -     | -        │ │
│ └────────────────────────────────────────────────────────┘ │
│ ★ Recommended based on performance                          │
│                                                             │
│ Step 4: Live Testing                                       │
│ Click [Test] to swap .mpg with variant for client testing  │
│                                                             │
│ Current file: recording.mpg (original backup saved)        │
│ [🔄 Restore Original] [⬅ Restore Previous]                 │
│                                                             │
│ Step 5: Save Profile (once optimal variant found)          │
│ [💾 Save as Learned Profile]                                │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

#### 3. JavaScript Module (`py_captions_for_channels/webui/static/test-suite.js`)

**Key Functions:**

```javascript
class TestSuiteManager {
    constructor() {
        this.selectedRecording = null;
        this.testJobId = null;
        this.pollInterval = null;
    }
    
    async startTestSuite(recordingPath, variants) {
        // POST /api/test-suite/run
        // Start polling status
    }
    
    async pollTestStatus() {
        // GET /api/test-suite/status/{job_id}
        // Update progress bar, current variant
    }
    
    async loadTestResults() {
        // GET /api/test-suite/results/{job_id}
        // Populate results table
    }
    
    async swapFile(variantPath) {
        // POST /api/test-suite/swap-file
        // Update file status display
    }
    
    async restore(restoreTo) {
        // POST /api/test-suite/restore
        // Update file status display
    }
    
    async saveProfile(variantName, notes) {
        // POST /api/test-suite/save-profile
        // Show success notification
    }
    
    async loadFileStatus(recordingPath) {
        // GET /api/test-suite/file-status
        // Enable/disable restore buttons
    }
}
```

### Workflow Example

1. **User selects** "Entertainment Tonight" recording
2. **User clicks** "Start Test Suite"
3. **System**:
   - Creates `.orig` backup if missing
   - Generates `.srt` using existing caption generation
   - Launches `tools.ffmpeg_test_suite` with 6 variants
4. **UI polls** status every 2 seconds, shows progress
5. **Test completes**, results table populated
6. **User clicks** [Test] next to "NVENC hp" variant
7. **System swaps** `.mpg` with test variant, backs up current to `.test_backup`
8. **User tests** with Channels mobile/web client
9. **If good**: User clicks "Save as Learned Profile"
10. **System**: Computes signature, saves to `learned_profiles`
11. **Future recordings** matching signature automatically use learned profile

---

## Feature 2: Language Selection (Primary Feature)

### Problem Statement

Current system processes **all** audio/subtitle tracks from source recordings. For multi-language broadcasts:
- Wastes processing time on unwanted languages
- Creates bloated output files with unnecessary tracks
- Complicates client-side language selection

### Solution Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Settings: Default Language Configuration                     │
│ - Primary audio language (eng, spa, fra, etc.)              │
│ - Subtitle language (same, separate, or none)               │
│ - Fallback behavior (process all if language missing)       │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ Recording Detection                                          │
│ - Probe all audio/subtitle streams                          │
│ - FFprobe extracts language tags                            │
│ - Match against configured language                         │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ Selective Processing                                         │
│ Whisper: Transcribe only selected audio track               │
│ FFmpeg: Map only selected audio + subtitle tracks           │
│ - Primary audio (specified language)                        │
│ - Generated captions for primary audio                      │
│ - Optional: Native subtitles if language matches            │
└─────────────────────────────────────────────────────────────┘
```

### Settings Schema

**New settings:**
- `audio_language`: ISO 639-2 code (eng, spa, fra, etc.)
- `subtitle_language`: "same" | "none" | ISO code
- `language_fallback`: "all" | "first" | "skip"

**Default: English**
```python
{
    "audio_language": "eng",
    "subtitle_language": "same",
    "language_fallback": "first"
}
```

### Implementation Components

#### 1. Stream Detection (`py_captions_for_channels/stream_detector.py`)

```python
class StreamDetector:
    """Detect and filter audio/subtitle streams by language."""
    
    @staticmethod
    def probe_streams(video_path: str) -> dict:
        """
        Use ffprobe to get all streams with language tags.
        
        Returns:
        {
            "audio_streams": [
                {"index": 0, "codec": "ac3", "channels": 6, "language": "eng"},
                {"index": 1, "codec": "aac", "channels": 2, "language": "spa"}
            ],
            "subtitle_streams": [
                {"index": 0, "codec": "dvb_subtitle", "language": "eng"},
                {"index": 1, "codec": "dvb_subtitle", "language": "spa"}
            ],
            "video_streams": [...]
        }
        """
    
    @staticmethod
    def select_streams(
        streams: dict,
        audio_lang: str,
        subtitle_lang: Optional[str],
        fallback: str
    ) -> dict:
        """
        Select streams matching language preferences.
        
        Returns:
        {
            "audio_index": 0,  # Stream index to use
            "audio_language": "eng",
            "subtitle_index": 0,  # or None
            "subtitle_language": "eng"  # or None
        }
        """
```

#### 2. Modified Whisper Invocation (`embed_captions.py`)

**Current:**
```python
# Transcribes first audio stream
whisper input.mpg --model base.en --output_format srt
```

**Updated:**
```python
# Extract specific audio stream first
ffmpeg -i input.mpg -map 0:a:0 -vn -acodec copy audio_eng.m4a

# Transcribe extracted audio
whisper audio_eng.m4a --model base.en --output_format srt
```

#### 3. Modified FFmpeg Encoding (`embed_captions.py`)

**Current:**
```python
# Maps all audio streams
ffmpeg ... -map 0:v -map 0:a? ...
```

**Updated:**
```python
# Map only selected audio stream
ffmpeg ... -map 0:v:0 -map 0:a:{audio_index} -c:a aac ...
# Add generated caption track
-map 1:0 -c:s mov_text -metadata:s:s:0 language=eng
# Optionally add native subtitle if different language
-map 0:s:{subtitle_index} ...
```

#### 4. Settings UI (`settings.html`)

Add new section:

```html
<fieldset>
    <legend>Language Selection</legend>
    
    <div class="form-group">
        <label for="audio_language">Audio Language</label>
        <select id="audio_language">
            <option value="eng" selected>English (eng)</option>
            <option value="spa">Spanish (spa)</option>
            <option value="fra">French (fra)</option>
            <option value="deu">German (deu)</option>
            <option value="ita">Italian (ita)</option>
            <option value="por">Portuguese (por)</option>
            <!-- ISO 639-2 codes -->
        </select>
        <p class="help-text">
            Select primary audio language to process.
            Only this audio track will be transcribed and included.
        </p>
    </div>
    
    <div class="form-group">
        <label for="subtitle_language">Subtitle Language</label>
        <select id="subtitle_language">
            <option value="same" selected>Same as audio</option>
            <option value="none">None (captions only)</option>
            <option value="eng">English (eng)</option>
            <option value="spa">Spanish (spa)</option>
            <!-- ... -->
        </select>
        <p class="help-text">
            Include native subtitles if available.
            Generated captions always use audio language.
        </p>
    </div>
    
    <div class="form-group">
        <label for="language_fallback">If language not found</label>
        <select id="language_fallback">
            <option value="first" selected>Use first available</option>
            <option value="all">Process all tracks</option>
            <option value="skip">Skip recording</option>
        </select>
    </div>
</fieldset>
```

#### 5. Recording Metadata Display

Update Jobs/Queue tabs to show:
```
Entertainment Tonight S45E149
Audio: eng (5.1), spa (stereo) → Processing: eng only
```

### Benefits

1. **Performance**: 30-50% faster for multi-language content (only transcribe one track)
2. **File Size**: Smaller output (no unused audio tracks)
3. **User Experience**: Cleaner playback (no accidental language switches)
4. **Accuracy**: Better Whisper accuracy targeting specific language model

### Migration Path

**Phase 1: Settings (Non-breaking)**
- Add new settings with defaults matching current behavior
- UI updates
- No changes to pipeline yet

**Phase 2: Detection (Read-only)**
- Add stream detection to logging
- Show available languages in UI
- Still process all tracks

**Phase 3: Selective Processing (Breaking change)**
- Implement language filtering in embed_captions.py
- Users with multi-language content will see different output
- Release note: "Now processes only configured language"

---

## Implementation Priority

### Phase 1: Language Selection (High Priority, User-Facing)
**Timeline: 1-2 days**

1. Settings schema + UI (2-3 hours)
2. Stream detection module (2-3 hours)
3. Whisper audio extraction (1-2 hours)
4. FFmpeg stream mapping (2-3 hours)
5. Testing with multi-language recordings (2-3 hours)

**Estimated: 400-600 lines of code across 5 files**

### Phase 2: Test Suite Integration (Low Priority, Advanced Feature)
**Timeline: 3-4 days**

Implement in sub-phases:
1. **P2.1**: Backend API + file management (1 day)
2. **P2.2**: Test suite runner + progress tracking (1 day)
3. **P2.3**: Frontend UI (1.5 days)
4. **P2.4**: Profile learning auto-application (0.5 day)

**Estimated: 1200-1500 lines of code across 10+ files**

---

## Recommendation

**Start with Language Selection (Feature 2)** because:
- ✅ Higher user impact (affects all recordings)
- ✅ Performance improvement for multi-language content
- ✅ Smaller scope, clearer requirements
- ✅ Foundation for international deployments
- ✅ Can ship faster

**Defer Test Suite Integration** until:
- Language selection is stable in production
- User feedback on current encoding profiles
- Clear demand for custom profile testing

---

## Next Steps

1. **Confirm priorities** - Should we proceed with Language Selection first?
2. **Review architecture** - Any changes to the plans above?
3. **Start implementation** - I'll begin with settings schema and stream detection

Which approach do you prefer?
