# Feature: Library Items & Filesystem Processing

**Status:** Post-v1 Feature (Not Yet Implemented)  
**Created:** 2026-02-08  
**Priority:** Medium

## Overview

Extend py-captions-for-channels beyond DVR recordings to support:
1. Channels DVR library items (Movies, Videos, Imports)
2. General filesystem browsing for arbitrary video files
3. Caption detection to avoid reprocessing

## Current State (v1)

**Supported:**
- ✅ DVR recordings (via polling/webhook)
- ✅ Manual processing queue (user-selected recordings)

**Not Supported:**
- ❌ Movies library items
- ❌ Videos library items
- ❌ Imported media items
- ❌ Arbitrary filesystem files (non-Channels)
- ❌ Caption existence detection

## Feature 1: Channels Library Items

### Goal
Process media that exists in Channels DVR but isn't a recording:
- Movies library
- Videos library
- Imported items

### Channels DVR API Support

**Movies Endpoint:**
```
GET /dvr/files/movies
Returns: List of movie files with metadata
```

**Videos Endpoint:**
```
GET /dvr/files/videos
Returns: List of video files
```

**Imports Endpoint:**
```
GET /dvr/imports
Returns: List of imported media items
```

### Implementation Plan

**1. New API Methods (`channels_api.py`):**
```python
def get_movies(self, limit=100):
    """Get movies from Channels DVR library."""
    
def get_videos(self, limit=100):
    """Get videos from Channels DVR library."""
    
def get_imports(self, limit=100):
    """Get imported media items."""
```

**2. Web UI Enhancements (`web_app.py`):**
- New endpoint: `GET /api/library/movies` - List movies
- New endpoint: `GET /api/library/videos` - List videos
- New endpoint: `GET /api/library/imports` - List imports
- New endpoint: `POST /api/library/process` - Add library items to manual queue

**3. UI Tab:**
- Add "Library" tab in web interface
- Three sections: Movies, Videos, Imports
- Each shows table with:
  * Title
  * Path
  * Duration
  * Caption status (✅ has captions, ❌ missing, ⚠️ unknown)
  * Action button: "Process"

**4. Database Schema:**
No changes needed - library items use same execution tracking as recordings.

## Feature 2: Filesystem Browser

### Goal
Browse and process arbitrary video files on disk that aren't in Channels DVR catalog.

### Use Cases
- Process downloaded videos before importing to Channels
- Batch process video archives
- Test caption generation on sample files
- Process legacy media not yet cataloged

### Implementation Plan

**1. File Browser Service (`services/filesystem_service.py`):**
```python
class FilesystemService:
    def list_directory(self, path: str, extensions=['.mpg', '.mp4', '.mkv']):
        """List video files in directory."""
        
    def get_directory_tree(self, root: str, max_depth=3):
        """Get hierarchical directory tree."""
        
    def get_file_info(self, path: str):
        """Get file metadata (size, duration, etc.)."""
```

**2. Security Constraints:**
- Restrict browsing to configured root paths (prevent directory traversal)
- Environment variable: `FILESYSTEM_BROWSE_ROOTS=/tank/AllMedia,/mnt/videos`
- Validate all paths against allowed roots
- Reject paths with `..` or absolute paths outside roots

**3. Web UI Enhancements:**
- New endpoint: `GET /api/filesystem/browse?path={path}` - List directory
- New endpoint: `POST /api/filesystem/process` - Process selected files
- UI: Breadcrumb navigation, file list, multi-select checkboxes

**4. UI Tab:**
- Add "Files" tab
- Breadcrumb: `/tank/AllMedia > Channels > TV`
- File list table:
  * Checkbox (for multi-select)
  * Icon (folder/video)
  * Name
  * Size
  * Caption status
  * Action: "Process" or "Open" (for folders)

## Feature 3: Caption Detection

### Goal
Detect existing captions to avoid reprocessing and show status in UI.

### Caption Types to Detect

**1. Embedded Captions (in video container):**
- Detect using `ffprobe -show_streams`
- Check for subtitle streams: `codec_name=subrip` or `codec_name=mov_text`

**2. Sidecar SRT Files:**
- Check for `{basename}.srt` next to video file
- Check for `{basename}.en.srt` (language-specific)

**3. Our Generated Captions:**
- Check execution tracker database for completed executions matching path
- Status: completed + success = has our captions

### Implementation Plan

**1. Caption Detection Service (`services/caption_service.py`):**
```python
class CaptionService:
    def has_embedded_captions(self, video_path: str) -> bool:
        """Check for embedded subtitle tracks via ffprobe."""
        
    def has_sidecar_srt(self, video_path: str) -> bool:
        """Check for .srt file next to video."""
        
    def get_caption_status(self, video_path: str) -> dict:
        """
        Returns: {
            'has_embedded': bool,
            'has_srt': bool,
            'has_our_captions': bool,
            'status': 'complete' | 'missing' | 'partial'
        }
        """
```

**2. Execution Tracker Enhancement:**
```python
def has_been_processed(self, path: str) -> bool:
    """Check if path has completed execution."""
    executions = self.get_executions(limit=1000)
    return any(
        e.get('path') == path and 
        e.get('status') == 'completed' and 
        e.get('success')
        for e in executions
    )
```

**3. Web API Enhancement:**
All listing endpoints return caption status:
```json
{
  "path": "/tank/AllMedia/movie.mp4",
  "title": "Movie Title",
  "captions": {
    "has_embedded": false,
    "has_srt": true,
    "has_our_captions": true,
    "status": "complete"
  }
}
```

**4. UI Indicators:**
- ✅ Green checkmark: Complete (has our captions + SRT)
- ⚠️ Yellow warning: Partial (has SRT but we didn't process)
- ❌ Red X: Missing (no captions detected)
- 🔄 Blue spinner: Processing (execution in progress)

## Technical Considerations

### Performance
- Caption detection via `ffprobe` can be slow for large file lists
- Solution: Background worker to cache caption status in database
- New table: `caption_cache` (path, has_embedded, has_srt, checked_at)

### Permissions
- Filesystem browsing requires read access to media directories
- Docker volume mounts must include all browsable paths
- Security: Never expose system paths, only media directories

### Filtering
- Add filters to all browse views:
  * "Show only missing captions"
  * "Show only unprocessed"
  * "Show all"

## API Design Examples

### List Movies with Caption Status
```http
GET /api/library/movies?filter=missing_captions&limit=50

Response:
{
  "items": [
    {
      "id": "movie-123",
      "title": "The Matrix",
      "path": "/tank/AllMedia/Movies/The Matrix.mp4",
      "duration_seconds": 8136,
      "size_bytes": 2147483648,
      "captions": {
        "has_embedded": false,
        "has_srt": false,
        "has_our_captions": false,
        "status": "missing"
      }
    }
  ],
  "total": 147,
  "filtered": 89
}
```

### Browse Filesystem
```http
GET /api/filesystem/browse?path=/tank/AllMedia/Channels/Movies

Response:
{
  "current_path": "/tank/AllMedia/Channels/Movies",
  "parent_path": "/tank/AllMedia/Channels",
  "items": [
    {
      "type": "directory",
      "name": "Action",
      "path": "/tank/AllMedia/Channels/Movies/Action"
    },
    {
      "type": "file",
      "name": "Movie.mp4",
      "path": "/tank/AllMedia/Channels/Movies/Movie.mp4",
      "size_bytes": 1073741824,
      "extension": ".mp4",
      "captions": {
        "status": "complete"
      }
    }
  ]
}
```

### Process Library Items
```http
POST /api/library/process
Content-Type: application/json

{
  "items": [
    {
      "type": "movie",
      "id": "movie-123",
      "path": "/tank/AllMedia/Movies/The Matrix.mp4"
    }
  ],
  "skip_caption_generation": false,
  "log_verbosity": "NORMAL"
}

Response:
{
  "queued": 1,
  "execution_ids": ["manual_process::/tank/AllMedia/Movies/The Matrix.mp4"]
}
```

## Implementation Phases

### Phase 1: Caption Detection (Foundation)
1. Create `CaptionService` with detection methods
2. Add `caption_cache` database table
3. Enhance execution tracker with `has_been_processed()`
4. Add caption status to existing `/api/manual-process/candidates`

### Phase 2: Channels Library Items
1. Add Channels API methods for movies/videos/imports
2. Create `/api/library/*` endpoints
3. Add "Library" tab to web UI
4. Test with real Channels DVR library

### Phase 3: Filesystem Browser
1. Create `FilesystemService` with security constraints
2. Add `FILESYSTEM_BROWSE_ROOTS` configuration
3. Create `/api/filesystem/*` endpoints
4. Add "Files" tab to web UI

### Phase 4: UI Polish
1. Add filtering (missing captions, unprocessed, etc.)
2. Multi-select and batch operations
3. Caption status indicators and icons
4. Background caption status caching

## Configuration

### New Environment Variables
```bash
# Filesystem browsing (comma-separated allowed roots)
FILESYSTEM_BROWSE_ROOTS=/tank/AllMedia,/mnt/videos

# Caption detection cache expiry (hours)
CAPTION_CACHE_EXPIRY=24

# Enable/disable features
ENABLE_LIBRARY_PROCESSING=true
ENABLE_FILESYSTEM_BROWSE=true
```

## Testing Plan

### Caption Detection Tests
- Test `ffprobe` detection of embedded captions
- Test SRT file detection
- Test execution tracker integration
- Test cache performance

### Library Items Tests
- Mock Channels API responses for movies/videos/imports
- Test filtering by caption status
- Test batch processing

### Filesystem Browser Tests
- Test path security (prevent directory traversal)
- Test filtering by extension
- Test nested directory browsing
- Test multi-select processing

## Migration Notes

**No breaking changes** - all features are additive.

**Database migration:**
```sql
-- Add caption_cache table
CREATE TABLE caption_cache (
    path TEXT PRIMARY KEY,
    has_embedded BOOLEAN NOT NULL,
    has_srt BOOLEAN NOT NULL,
    checked_at DATETIME NOT NULL
);

CREATE INDEX idx_caption_cache_checked_at ON caption_cache(checked_at);
```

## Success Metrics

- Users can browse and process Movies library items
- Users can browse filesystem and process arbitrary videos
- Caption status visible in all browse views
- No reprocessing of files that already have captions
- Secure filesystem access (no directory traversal vulnerabilities)

## Future Enhancements

- **Batch operations**: Select 50 movies, queue all at once
- **Smart scheduling**: Process library items during off-peak hours
- **Caption validation**: Parse SRT files to verify quality
- **Import integration**: Auto-process when new imports detected
- **Watch folders**: Monitor directories for new files
