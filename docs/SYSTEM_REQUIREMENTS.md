# System Requirements and Performance Expectations

This document helps you understand the hardware requirements and expected performance for py-captions-for-channels.

## Overview

py-captions-for-channels uses **Whisper AI** for speech-to-text transcription and **ffmpeg** for video encoding. The transcription step is the most compute-intensive (70-80% of total processing time) and benefits significantly from GPU acceleration.

## Hardware Requirements

### Minimum Viable System

**GPU Path (Strongly Recommended)**
- **GPU**: NVIDIA GTX 1660 Super / RTX 2060 or better
  - **VRAM**: 6GB minimum (for `medium` model)
  - **4GB GPUs**: Can run `base` model only (lower quality)
- **CPU**: 4+ cores (Intel i5-8400, AMD Ryzen 5 2600)
- **RAM**: 8GB minimum, 16GB recommended
- **Storage**: 10GB free space for temporary files

**Performance Expectations:**
- GTX 1660 + medium model: **0.5-0.6x real-time**
  - 30-minute recording → 15-18 minutes
  - 60-minute recording → 30-36 minutes
- **Daily Capacity**: Can process 4-6 hours of recordings per day
- **Use Case**: Light DVR usage (2-3 recordings/day)

### Recommended System

- **GPU**: NVIDIA RTX 2060 or better (8GB VRAM)
- **CPU**: 6+ cores
- **RAM**: 16GB
- **Storage**: 10GB+ free space

**Performance Expectations:**
- RTX 2060/2070 + medium model: **0.3-0.4x real-time**
  - 30-minute recording → 9-12 minutes
  - 60-minute recording → 18-24 minutes
- **Daily Capacity**: Can process 12-16 hours of recordings per day
- **Use Case**: Typical DVR usage (5-10 recordings/day)

### Current Reference System (Developer)

- **CPU**: Intel i7-7700K (4 cores/8 threads, 2017)
- **GPU**: NVIDIA RTX 2080 (8GB VRAM, 1st gen Tensor cores)
- **RAM**: 16GB
- **Performance**: 0.3-0.4x real-time with medium model

This system is **well above minimum comfortable** and handles typical DVR workloads easily.

## Performance by Processing Stage

### Time Distribution (Typical)
1. **Whisper Transcription**: 70-80% of total time (GPU-bound)
2. **ffmpeg NVENC Encoding**: 15-20% of total time (GPU-bound)
3. **File Operations**: 5-10% of total time (CPU/disk I/O)

### GPU Impact

**Whisper Transcription** (Most Critical)
- GPU acceleration provides **10-20x speedup** vs CPU-only
- Modern GPUs with advanced Tensor cores provide additional gains:
  - RTX 2000 series: Baseline (1st gen Tensor)
  - RTX 3000 series: +20-30% faster (2nd gen Tensor)
  - RTX 4000 series: +40-60% faster (3rd gen Tensor, better memory)

**NVENC Encoding**
- RTX 2000+: All use 7th gen NVENC (similar speed)
- RTX 3000+: Can use 8th gen NVENC (same speed, better quality)
- CPU fallback (libx264): ~3x slower than NVENC

### CPU Impact

CPU is **not the bottleneck** for this workload. Modern multi-core CPUs provide minimal additional benefit since:
- Whisper runs on GPU (CPU just manages)
- ffmpeg NVENC runs on GPU
- File operations are I/O-bound

**Upgrading from 4 cores → 12 cores**: <5% total improvement

## Whisper Model Selection

Choose model based on your GPU VRAM and quality requirements:

| Model | VRAM | Quality | Speed | Best For |
|-------|------|---------|-------|----------|
| **tiny** | 1GB | Low | Fastest | Testing only |
| **base** | 2GB | Fair | Very Fast | 4GB GPUs, non-critical content |
| **small** | 4GB | Good | Fast | Balance on older GPUs |
| **medium** | 6GB | Very Good | Moderate | **Default, recommended** |
| **large** | 8GB | Excellent | Slower | Best quality, high-end GPUs |

**Default**: `medium` model provides the best quality/performance balance for news, sports, and entertainment content.

## CPU-Only Operation (Not Recommended)

If you don't have a compatible NVIDIA GPU:

- **CPU**: 8+ cores minimum (Intel i7-9700K, AMD Ryzen 7)
- **RAM**: 16GB minimum
- **Performance**: **3-5x real-time** (60-min recording → 3-5 hours)
- **Problem**: Creates queue backlog on heavy recording days
- **Verdict**: Only viable for very light usage (1-2 recordings/week)

**Recommendation**: Used GTX 1660 (~$150-200) provides far better value than CPU upgrade for this workload.

## Modern Hardware Upgrades

### From i7-7700K + RTX 2080 to Modern System

**GPU Upgrade (RTX 3060/4060):**
- Whisper: +20-60% faster (Tensor cores)
- ffmpeg: Same speed
- **Total improvement**: 25-35% faster overall
- **Worth it?** Only if experiencing queue backlog

**CPU Upgrade (12+ cores):**
- Minimal impact (<5%)
- **Worth it?** Not for this workload alone

**RAM Upgrade (16GB → 32GB):**
- No benefit for caption generation
- **Worth it?** Only if needed for other uses

## Practical Scenarios

### Light User (2-3 recordings/day)
- **System**: GTX 1660 + 4-core CPU + 8GB RAM
- **Budget**: $300-400 (used components)
- **Result**: No queue buildup, captions within hours

### Typical User (5-10 recordings/day)
- **System**: RTX 2060 + 6-core CPU + 16GB RAM
- **Budget**: $500-700
- **Result**: Comfortable processing, minimal backlog

### Heavy User (15+ recordings/day)
- **System**: RTX 3060/4060 + 8+ core CPU + 16GB RAM
- **Budget**: $800-1200
- **Result**: Fast processing, handles peak loads

## Queue Management

### Preventing Backlog
- Monitor Web UI "Queue" section
- If queue grows consistently:
  1. Use `base` model (faster, lower quality)
  2. Enable `WHISPER_MODE=automatic` (optimized encoding)
  3. Upgrade GPU (biggest impact)
  4. Add second processing node (future feature)

### Peak Recording Times
- Evening primetime: 5-10 recordings may complete simultaneously
- Weekend sports: Multiple overlapping events
- Hardware should handle 2-3x average daily load

## Automatic Optimization

The `WHISPER_MODE=automatic` setting optimizes both Whisper and ffmpeg based on source characteristics:

- **OTA Content** (720p60, 5.1 audio): Aggressive encoding presets (30-50% faster)
- **TV Everywhere** (720p30, stereo): Standard encoding presets

Enable in `.env`:
```bash
WHISPER_MODE=automatic
```

See [AUTOMATIC_WHISPER_OPTIMIZATION.md](AUTOMATIC_WHISPER_OPTIMIZATION.md) for details.

## Benchmarking Your System

Run a test recording to measure performance:

```bash
# Time a 30-minute recording
time python scripts/embed_captions.py \
  --input /path/to/recording.mpg \
  --srt /path/to/output.srt \
  --model medium

# Check Web UI for detailed timing per stage
```

**Target**: 30-min recording should complete in <15 minutes (0.5x real-time or better)

## Network/Docker Considerations

### Docker Deployment
- GPU must be accessible to container (NVIDIA Container Toolkit required)
- CPU/RAM overhead: Minimal (<1% difference)
- Storage: Use volume mounts for recording paths

### Network Requirements
- Minimal: Only API calls to Channels DVR
- Local network latency: ~1-5ms (negligible)
- No internet required after initial setup

## Summary

**For most users:**
- Minimum: GTX 1660 + 4-core CPU + 8GB RAM ($300-400 used)
- Comfortable: RTX 2060+ + 6-core CPU + 16GB RAM ($500-700)
- GPU matters most, CPU upgrade provides minimal benefit
- `medium` model recommended for quality/speed balance
- Modern GPUs (RTX 3000/4000) provide ~25-35% improvement

**If you have:**
- i7-7700K + RTX 2080: You're already in the "comfortable" range
- Older than GTX 1660: Upgrade GPU (biggest impact)
- 4GB GPU: Use `base` model or upgrade
- No GPU: Budget ~$200 for used GTX 1660 minimum
