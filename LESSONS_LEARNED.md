# Lessons Learned: CUDA and Python Package Dependencies

## Issue Summary
During the February 2026 update cycle, we encountered a cascade of dependency conflicts when attempting to fix production issues while maintaining CUDA 11.8 compatibility. This document captures the lessons learned to avoid similar issues in future updates.

## Timeline of Events

### Initial State
- **Base Image**: `nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04`
- **Problem 1**: Glances API returning 500 errors (missing `orjson` dependency)
- **Problem 2**: ctranslate2 auto-installed version 4.7.1 (requires CUDA 12.x)
- **Symptom**: All transcriptions failing with "Library libcublas.so.12 is not found"

### Attempted Fix #1: Pin ctranslate2 to CUDA 11.8-compatible version
```
ctranslate2>=3.0,<4.0  # CUDA 11.8 compatible
faster-whisper  # unpinned
```
**Result**: ❌ Failed
- faster-whisper resolved to older versions (1.0.1-1.0.2)
- These required `av==11.*` which needed compilation from source
- No pre-built wheels available for av 11.x

### Attempted Fix #2: Add FFmpeg dev headers for av compilation
- Installed libavformat-dev, libavcodec-dev, etc.
- Attempted to compile av from source during Docker build

**Result**: ❌ Failed
- Cython compilation errors in av package
- Build time increased significantly
- Unreliable and fragile build process

### Final Solution: Upgrade to CUDA 12.1
```
Base: nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04
ctranslate2: 4.7.1 (latest, pre-built)
faster-whisper: 1.2.1 (latest, pre-built)
av: 16.1.0 (pre-built wheel)
```
**Result**: ✅ Success
- All packages have modern pre-built wheels
- No compilation required
- Build time reduced
- Stable, maintained versions

## Root Cause Analysis

### The Dependency Chain
```
faster-whisper
    ├── ctranslate2
    │   └── CUDA runtime libraries (version-specific)
    └── av (PyAV)
        └── FFmpeg libraries

ctranslate2 4.x → requires CUDA 12.x cuBLAS libraries
ctranslate2 3.x → requires CUDA 11.8 cuBLAS libraries
```

### Why Downgrading Failed
1. **Package Ecosystem Evolution**: Python ML packages have moved to CUDA 12
2. **Pre-built Wheels**: Modern versions only ship pre-built wheels for CUDA 12
3. **Compilation Complexity**: Older versions require source compilation with complex C/C++ dependencies
4. **Maintenance Burden**: Older versions are no longer actively tested/fixed

## Key Lessons

### 1. Follow Upstream CUDA Requirements
**Lesson**: Don't fight against the ecosystem's CUDA version requirements.

- **Bad**: Pin packages to old versions to maintain old CUDA version
- **Good**: Upgrade CUDA runtime to match modern package requirements

**Why**: The Python ML ecosystem (PyTorch, ctranslate2, ONNX) moves quickly toward newer CUDA versions. Staying behind creates a cascade of compatibility issues.

### 2. Pre-built Wheels vs Source Compilation
**Lesson**: Prefer pre-built wheels over source compilation.

**Pre-built wheels**:
- ✅ Fast Docker builds
- ✅ Reproducible
- ✅ No build dependencies
- ✅ Tested by package maintainers

**Source compilation**:
- ❌ Slow builds
- ❌ Fragile (missing headers, version mismatches)
- ❌ Large images (build tools required)
- ❌ Security concerns (C/C++ compilation)

### 3. Check Compatibility BEFORE Making Changes
**Lesson**: Verify compatibility across the entire dependency chain before pinning versions.

**Pre-update checklist**:
```bash
# Check what versions pip would install
pip install --dry-run --report - ctranslate2 faster-whisper

# Check CUDA requirements for a specific package version
pip download ctranslate2==4.7.1
unzip ctranslate2-*.whl
cat ctranslate2-*.dist-info/METADATA

# Check if pre-built wheels exist for your platform
pip download --only-binary :all: av==11.0.0  # fails if no wheel
```

### 4. Update Base Images When Appropriate
**Lesson**: Don't be afraid to update base CUDA images when the ecosystem has moved on.

**When to upgrade**:
- Package dependencies require newer CUDA version
- Security updates available
- Current version approaching EOL
- Modern features needed

**When to stay**:
- Hardware constraints (old GPUs)
- Specific driver compatibility requirements
- Known working configuration needed

### 5. The Glances-Faster-Whisper Catch-22

**The Problem**: 
- Glances missing `orjson` (undeclared dependency)
- Faster-whisper needs CUDA 12 libraries
- Both issues discovered during production troubleshooting

**Why This Happened**:
1. Local development didn't catch orjson issue (different environment)
2. CUDA library check happens lazily (only during actual GPU operation)
3. Model loading succeeds even with wrong CUDA version (CPU fallback)
4. Error only appears during transcription (GPU tensor operations)

**Prevention Strategy**:
```dockerfile
# Add smoke test to Dockerfile to catch issues early
RUN python3 -c "
import ctranslate2
import faster_whisper
import torch
print(f'ctranslate2: {ctranslate2.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
print(f'CUDA version: {torch.version.cuda}')
# Verify GPU can be used
assert torch.cuda.is_available(), 'CUDA not available'
"

# Test Glances API can start
RUN timeout 5 glances --version && \
    python3 -c "from glances.outputs.glances_restful_api import *; print('Glances API imports OK')"
```

## Best Practices for Future Updates

### 1. Document Dependencies
Maintain a `DEPENDENCIES.md` with:
- CUDA version and why it was chosen
- Key package versions and their requirements
- Known compatibility constraints

### 2. Test in Stages
```bash
# 1. Test locally with new requirements.txt
pip install -r requirements.txt  # Does it resolve?

# 2. Test Docker build
docker build -t test .  # Does it build?

# 3. Test GPU functionality
docker run --gpus all test python -c "import torch; print(torch.cuda.is_available())"

# 4. Test actual workload
docker run --gpus all test python -m py_captions_for_channels.embed_captions --test
```

### 3. Use Explicit Version Constraints
```python
# Bad: Loose constraints leave room for surprises
faster-whisper
ctranslate2

# Good: Document why versions are pinned
# faster-whisper 1.2.1: Latest with pre-built wheels for CUDA 12.1
faster-whisper>=1.2.0,<2.0
# ctranslate2 4.7.1: Requires CUDA 12.x, has pre-built wheels
ctranslate2>=4.0,<5.0
```

### 4. Monitor for Warnings
Watch Docker build output for:
- `WARNING: The candidate selected for download or install is a yanked version`
- `Building wheels for collected packages` (indicates no pre-built wheel)
- `Requirement already satisfied` (dependency conflict resolution)

### 5. Keep CI in Sync
Our CI uses CPU-only PyTorch but production uses GPU. Document the difference:
```yaml
# .github/workflows/ci.yml
- name: Install dependencies
  run: |
    # CI uses CPU-only PyTorch (no GPU available)
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    # Production uses CUDA 12.1 (see Dockerfile)
    pip install -r requirements.txt
```

## Quick Reference: Checking Package Compatibility

### Check CUDA Version Requirements
```bash
# For installed package
pip show ctranslate2 | grep -A 20 Requires

# For specific version
pip download ctranslate2==4.7.1 --no-deps
unzip -q ctranslate2-*.whl
cat ctranslate2-*.dist-info/METADATA | grep -i cuda
```

### Check Available Wheels
```bash
# List available versions and platforms
pip index versions ctranslate2

# Check if wheel exists for your platform
pip download --only-binary :all: --platform manylinux2014_x86_64 ctranslate2==4.7.1
```

### Verify GPU Runtime
```dockerfile
# Add to Dockerfile for early detection
RUN python3 << EOF
import torch
import ctranslate2
import faster_whisper

# Check CUDA is available
assert torch.cuda.is_available(), f"CUDA not available. Torch CUDA: {torch.version.cuda}"

# Check versions match
cuda_version = torch.version.cuda.split('.')[0]  # e.g., "12" from "12.1"
print(f"Runtime CUDA version: {cuda_version}")

# Try to initialize model on GPU (smoke test)
try:
    model = faster_whisper.WhisperModel("tiny", device="cuda", compute_type="float16")
    print("✅ GPU model initialization successful")
except Exception as e:
    print(f"❌ GPU model initialization failed: {e}")
    raise
EOF
```

## Decision Framework

When encountering dependency conflicts, ask:

1. **Is there a pre-built wheel?**
   - Yes → Prefer it
   - No → Reconsider version choice

2. **What does the package require?**
   - CUDA version match?
   - Specific library versions?
   - Compilation dependencies?

3. **Is the ecosystem moving forward?**
   - Yes → Move with it
   - No → Safe to pin older versions

4. **What's the blast radius?**
   - Just one package → Pin/upgrade that package
   - Entire stack → Upgrade base image

## Conclusion

The root issue was attempting to maintain CUDA 11.8 compatibility when the package ecosystem had moved to CUDA 12. The solution was to upgrade the base CUDA runtime to match modern package requirements, which eliminated all compilation issues and provided stable, pre-built packages.

**Key Takeaway**: When the ML/AI Python ecosystem upgrades its CUDA requirements, upgrade your base image rather than fighting it with version pins and source compilation.

---

**Last Updated**: February 15, 2026  
**Related Commits**: 
- `3316add` - Initial ctranslate2 3.x pin (failed approach)
- `bbea676` - faster-whisper pin attempt (failed)
- `e204b90` - FFmpeg dev headers for av compilation (failed)
- `f6953ad` - Final solution: CUDA 12.1 upgrade (success)
