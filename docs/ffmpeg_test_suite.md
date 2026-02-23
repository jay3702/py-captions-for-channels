# FFmpeg Caption-Mux Test Suite

## Overview

The FFmpeg Test Suite is a self-contained benchmark harness for testing different ffmpeg encoding and muxing strategies when embedding captions into Channels DVR recordings. It helps identify optimal configurations for different content types without requiring actual playback testing.

## Purpose

This tool helps answer questions like:
- Which ffmpeg preset gives the best performance for this content?
- Does GPU acceleration help or hurt for this specific recording format?
- Which container/codec combination provides the best compatibility?
- What's the performance/quality tradeoff between different encoding strategies?

## Usage

### Basic Usage

```bash
python -m tools.ffmpeg_test_suite \
    --input-video /path/to/test.mpg \
    --input-srt /path/to/test.srt \
    --out-dir ./test-results \
    --report-json report.json \
    --report-csv report.csv
```

### Options

- `--input-video`: Path to input video file (typically .mpg from Channels DVR)
- `--input-srt`: Path to caption sidecar file (.srt)
- `--out-dir`: Directory for test output files
- `--limit-variants`: Run only specific variants (comma-separated names)
- `--keep-temp`: Keep log files after test (default: delete)
- `--overwrite`: Overwrite existing output files
- `--report-json`: Generate detailed JSON report
- `--report-csv`: Generate flattened CSV report

### Example with Limited Variants

```bash
python -m tools.ffmpeg_test_suite \
    --input-video entertainment_tonight.mpg \
    --input-srt entertainment_tonight.srt \
    --out-dir ./output \
    --limit-variants "TRANSCODE_MPEG2_TO_H264_NVENC__MP4_MOVTEXT__AAC_FAST,TRANSCODE_MPEG2_TO_H264_NVENC__MP4_MOVTEXT__AAC_HP" \
    --report-json results.json
```

## Test Variants

The suite includes 6 predefined test variants:

### A. COPY_H264_OR_HEVC__MP4_MOVTEXT
- **Purpose**: No re-encode for already-encoded content
- **Strategy**: Copy video/audio, embed mov_text subtitles in MP4
- **Requirement**: Input must be H.264 or HEVC
- **Use case**: Fast muxing when input is already optimized

### B. COPY_H264_OR_HEVC__MP4_MOVTEXT__AAC
- **Purpose**: Android-friendly audio encoding
- **Strategy**: Copy video, re-encode to AAC 192kbps, mov_text subs
- **Requirement**: Input must be H.264 or HEVC
- **Use case**: Improve audio compatibility without video re-encode

### C. TRANSCODE_MPEG2_TO_H264_NVENC__MP4_MOVTEXT__AAC_FAST
- **Purpose**: Speed-first GPU encoding
- **Strategy**: NVENC with preset p1 (fastest), ultra-low latency
- **Settings**: qp=23, no B-frames, minimal lookahead
- **Use case**: OTA MPEG-2 content needing fast transcoding

### D. TRANSCODE_MPEG2_TO_H264_NVENC__MP4_MOVTEXT__AAC_HP
- **Purpose**: High-performance balanced encoding
- **Strategy**: NVENC with hp preset
- **Use case**: Compare against p1 for quality/speed tradeoff

### E. TRANSCODE_MPEG2_CUVID_YADIF_CUDA_TO_H264_NVENC__MP4_MOVTEXT__AAC
- **Purpose**: GPU-accelerated decode + deinterlace + encode
- **Strategy**: mpeg2_cuvid decoder + yadif_cuda filter + NVENC
- **Use case**: Interlaced 1080i OTA content (e.g., channel 4.1)
- **Requirement**: Requires CUDA hardware and yadif_cuda filter

### F. MKV_SRT__COPY_VIDEO_COPY_AUDIO
- **Purpose**: Container format compatibility test
- **Strategy**: MKV container with SRT subs, copy all streams
- **Requirement**: Input must be H.264 or HEVC
- **Use case**: Test if MKV with .mpg extension works in Channels DVR

## Output Files

For each variant, the suite generates:

1. **Encoded video**: `<input>__<variant_name>.mpg`
   - Note: Extension is always `.mpg` even for MP4/MKV containers
   - This mimics production behavior where Channels DVR expects .mpg

2. **Log file** (optional): `<input>__<variant_name>.log`
   - Full ffmpeg stdout/stderr
   - Kept only if `--keep-temp` is specified

## Reports

### JSON Report

Contains comprehensive data including:
- Run metadata (timestamp, ffmpeg versions, capabilities)
- Per-variant results:
  - Full command line used
  - Start/end timestamps
  - Elapsed seconds
  - Exit code
  - File size
  - ffprobe analysis (codecs, resolution, fps, field order, etc.)
  - stderr excerpts for debugging

### CSV Report

Flattened table with key metrics:
- Name, exit_code, elapsed_seconds, file_size_bytes
- Container format, video/audio/subtitle codecs
- Resolution, FPS, field order, audio channels
- Skip status and reason

## Interpreting Results

### Performance Metrics

- **elapsed_seconds**: Wall-clock time for entire encode
- **file_size_bytes**: Output file size (compare to input)
- **exit_code**: 0 = success, non-zero = failure

### Compatibility Signals

- **container_format**: mp4, matroska (MKV), etc.
- **video_codec**: h264, hevc, mpeg2video
- **subtitle_codec**: mov_text (MP4), srt (MKV)
- **field_order**: progressive, tt (top-top interlaced), etc.

### Common Patterns

**Good for OTA content:**
- Exit code: 0
- Elapsed: 600-800s for 1-hour video (depends on GPU)
- Container: mp4
- Codecs: h264 / aac / mov_text

**Signs of problems:**
- Non-zero exit code
- Missing subtitle_codec in output
- Probe errors
- Significantly larger file size than input

## Integration with Main Project

After identifying optimal variants for your content:

1. Review `py_captions_for_channels/encoding_profiles.py`
2. Add new profile with tested parameters
3. Update `match_profile()` logic to detect this content type
4. Test with actual recordings in production

## Requirements

- Python 3.7+
- ffmpeg in PATH (with desired encoders/filters compiled)
- ffprobe in PATH
- No external Python dependencies (uses stdlib only)

## Hardware Requirements

Some variants require specific hardware:
- **NVENC variants**: NVIDIA GPU with NVENC support
- **CUVID/CUDA variants**: NVIDIA GPU with CUDA support
- **yadif_cuda**: ffmpeg compiled with CUDA filter support

The suite auto-detects capabilities and skips unsupported variants.

## Troubleshooting

### "NVENC not available"
Your ffmpeg build doesn't have NVENC encoder support. Recompile with `--enable-nvenc` or use variants that don't require GPU.

### "yadif_cuda filter not available"
Your ffmpeg build doesn't have CUDA filter support. Recompile with `--enable-cuda-nvcc` or skip variant E.

### "Input codec is mpeg2video, not h264/hevc"
Some variants only work with already-encoded H.264/HEVC content. This is expected for MPEG-2 inputs - use transcode variants instead.

### Large output files
If outputs are much larger than inputs, check:
- QP/CRF settings (lower = higher quality/size)
- Preset choice (slower presets = better compression)
- Whether you're transcoding already-compressed content

## Example Workflow

```bash
# 1. Test a problematic OTA recording
python -m tools.ffmpeg_test_suite \
    --input-video /tank/Channels/TV/News/news.mpg \
    --input-srt /tank/Channels/TV/News/news.srt \
    --out-dir ~/test-results \
    --report-json report.json \
    --report-csv report.csv

# 2. Review CSV for fastest variant with good quality
cat report.csv

# 3. If variant E (GPU deinterlace) wins, update encoding_profiles.py
# to use yadif_cuda for interlaced content

# 4. Test in production with manual reprocess
# (via web UI or direct pipeline call)
```

## Future Enhancements

Potential additions:
- VMAF/SSIM quality scoring
- Automated profile creation from test results
- Database storage of variant results
- Integration with web UI for on-demand testing
- Additional variants (VP9, AV1, HEVC, etc.)
