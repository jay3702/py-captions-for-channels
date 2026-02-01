# Windows Deployment Guide

This guide covers deploying py-captions-for-channels on Windows in various configurations.

## Deployment Scenarios

### Scenario 1: Fully Containerized (Docker Desktop)
**Best for**: Development, testing, systems with discrete NVIDIA GPUs

**Requirements**:
- Docker Desktop with WSL2
- NVIDIA GPU (optional, for GPU acceleration)
- 16GB+ RAM recommended

**Pros**:
- Isolated environment
- Easy updates
- Consistent with Linux deployment
- NVIDIA GPU support via WSL2

**Cons**:
- Integrated GPUs (Intel/AMD) not supported
- Higher memory overhead
- WSL2 complexity

### Scenario 2: Native Python (Hybrid)
**Best for**: Integrated GPU systems, dedicated Channels DVR machines, Windows-only environments

**Requirements**:
- Python 3.10+
- ffmpeg installed natively
- Whisper dependencies
- ChannelWatch in Docker (optional)

**Pros**:
- Direct GPU access (NVIDIA, Intel, AMD)
- Lower memory footprint
- No WSL2 required
- Full Windows hardware acceleration

**Cons**:
- Manual dependency management
- Python environment conflicts possible
- Updates require manual steps

### Scenario 3: Mixed Architecture
**Best for**: Existing Channels DVR installations

**Requirements**:
- Channels DVR running natively on Windows
- ChannelWatch in Docker
- py-captions-for-channels (native or containerized)

**Pros**:
- Leverages existing Channels DVR setup
- Flexible caption service deployment
- Can choose best GPU approach per component

**Cons**:
- More complex networking
- Multiple service management

---

## Setup Instructions

### Option A: Full Docker Stack (Development/NVIDIA)

#### Prerequisites
1. **Install Docker Desktop**
   - Download: https://www.docker.com/products/docker-desktop
   - During install: Enable WSL2 backend
   - Restart when prompted

2. **Configure WSL2 Memory** (recommended for 64GB systems)
   
   Create/edit `%USERPROFILE%\.wslconfig`:
   ```ini
   [wsl2]
   memory=32GB
   processors=8
   swap=8GB
   ```

   Restart WSL: `wsl --shutdown` in PowerShell

3. **Install NVIDIA GPU Support** (if applicable)

   Open WSL2 terminal (Ubuntu):
   ```bash
   # Add NVIDIA repository
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
   curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

   # Install toolkit
   sudo apt-get update
   sudo apt-get install -y nvidia-container-toolkit
   
   # Configure Docker
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker
   ```

4. **Test GPU Access**
   ```powershell
   docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
   ```

#### Deploy
```powershell
cd C:\path\to\py-captions-for-channels

# Copy and edit configuration
Copy-Item .env.example .env
notepad .env  # Update settings

# Start services
docker compose up -d

# View logs
docker compose logs -f

# Access Web UI
# http://localhost:8000
```

#### Development Workflow
```powershell
# Make code changes in Windows
# Restart web service to see changes
docker compose restart py-captions-web

# View specific service logs
docker compose logs -f py-captions-web

# Stop all services
docker compose down
```

---

### Option B: Native Python (Hybrid/Integrated GPU)

#### Prerequisites

1. **Install Python 3.10+**
   - Download: https://www.python.org/downloads/
   - During install: Check "Add Python to PATH"
   - Verify: `python --version`

2. **Install ffmpeg**

   **Option 1 - Chocolatey** (recommended):
   ```powershell
   # Install Chocolatey first: https://chocolatey.org/install
   choco install ffmpeg
   ```

   **Option 2 - Manual**:
   - Download: https://www.gyan.dev/ffmpeg/builds/
   - Extract to `C:\ffmpeg`
   - Add `C:\ffmpeg\bin` to PATH

   **Verify**: `ffmpeg -version`

3. **Install Visual C++ Build Tools** (for some Python packages)
   - Download: https://visualstudio.microsoft.com/visual-cpp-build-tools/
   - Install "Desktop development with C++"

#### Setup

```powershell
cd C:\path\to\py-captions-for-channels

# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# For development
pip install -r requirements-dev.txt

# Setup pre-commit hooks
.\setup-hooks.ps1

# Copy and edit configuration
Copy-Item .env.example .env
notepad .env
```

#### GPU Configuration

**NVIDIA**:
```powershell
# Install CUDA toolkit if not present
# https://developer.nvidia.com/cuda-downloads

# PyTorch with CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

**Intel Iris Xe / Arc**:
```powershell
# Install Intel Extension for PyTorch
pip install intel-extension-for-pytorch
pip install oneccl_bind_pt --extra-index-url https://pytorch-extension.intel.com/release-whl/stable/cpu/us/
```

**AMD**:
```powershell
# ROCm support (if available for your GPU)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm5.7
```

#### Run Services

**Main Caption Service**:
```powershell
python -m py_captions_for_channels
```

**Web UI** (separate terminal):
```powershell
.\venv\Scripts\Activate.ps1
uvicorn py_captions_for_channels.web_app:app --host 0.0.0.0 --port 8000
```

**As Windows Service** (optional):
```powershell
# Using NSSM (Non-Sucking Service Manager)
choco install nssm

# Install service
nssm install PyCaptions "C:\path\to\py-captions-for-channels\venv\Scripts\python.exe" "-m" "py_captions_for_channels"
nssm set PyCaptions AppDirectory "C:\path\to\py-captions-for-channels"
nssm start PyCaptions
```

---

## Testing GPU Acceleration

### Test NVIDIA GPU
```powershell
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"CPU\"}')"
```

### Test Intel GPU
```powershell
python -c "import torch; import intel_extension_for_pytorch as ipex; print(f'Intel XPU available: {ipex.xpu.is_available()}')"
```

### Test Whisper with GPU
```powershell
# Create test audio file or use existing recording
whisper test.mp3 --model tiny --device cuda    # NVIDIA
whisper test.mp3 --model tiny --device xpu     # Intel
whisper test.mp3 --model tiny --device cpu     # CPU fallback
```

---

## Common Configurations

### Configuration 1: Development Machine
- **Channels DVR**: Not installed (using remote instance)
- **ChannelWatch**: Remote or Docker
- **py-captions**: Native Python with GPU
- **Web UI**: Uvicorn with --reload

### Configuration 2: Dedicated Channels Machine
- **Channels DVR**: Native Windows installation
- **ChannelWatch**: Docker container
- **py-captions**: Native Python, Windows Service
- **Web UI**: Part of main service

### Configuration 3: Docker Everything
- **Channels DVR**: Docker (or remote)
- **ChannelWatch**: Docker
- **py-captions**: Docker with GPU support
- **Web UI**: Docker

---

## Environment Variables

Key settings for Windows deployments:

```ini
# .env file

# Network paths for Windows
DVR_RECORDINGS_PATH=D:\Recordings
# Or UNC path: \\\\NAS\\Channels\\Recordings

# GPU selection (for multi-GPU systems)
CUDA_VISIBLE_DEVICES=0  # Use first GPU
# CUDA_VISIBLE_DEVICES=1  # Use second GPU

# Whisper model size (affects VRAM usage)
WHISPER_MODEL=medium  # ~5GB VRAM
# WHISPER_MODEL=small  # ~2GB VRAM
# WHISPER_MODEL=large  # ~10GB VRAM

# API endpoints
CHANNELS_API_URL=http://localhost:8089
CHANNELWATCH_URL=ws://localhost:8501/events

# Service ports
WEBHOOK_PORT=9000
WEB_UI_PORT=8000
```

---

## Troubleshooting

### Docker Issues

**WSL2 not starting**:
```powershell
wsl --update
wsl --shutdown
# Restart Docker Desktop
```

**GPU not detected in container**:
```powershell
# Check NVIDIA driver
nvidia-smi

# Verify Docker GPU support
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

### Native Python Issues

**Module not found**:
```powershell
# Ensure venv is activated
.\venv\Scripts\Activate.ps1

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

**ffmpeg not found**:
```powershell
# Check PATH
where ffmpeg

# If not found, add to PATH or specify full path in .env
# FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe
```

**GPU not detected**:
```powershell
# Check PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"

# Reinstall PyTorch with GPU support
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

---

## Performance Notes

### GPU Memory Requirements (Whisper)
- **tiny**: ~1GB VRAM
- **base**: ~1GB VRAM  
- **small**: ~2GB VRAM
- **medium**: ~5GB VRAM
- **large**: ~10GB VRAM

Your RTX 3050 (4GB VRAM): Use `small` or `medium` models

### CPU Fallback Performance
- **medium model**: ~10-20x slower than GPU
- **small model**: Good balance for CPU-only
- Use `--threads` to optimize CPU usage

---

## Next Steps

1. Choose deployment scenario based on your needs
2. Follow appropriate setup instructions
3. Test with a small recording first
4. Monitor GPU/CPU usage during processing
5. Adjust model size based on performance

## Additional Resources

- [Main README](README.md) - Project overview
- [Docker Deployment Guide](DOCKER_DEPLOYMENT.md) - Linux/general Docker info
- [Setup Guide](SETUP.md) - Quick start
- [Whisper Documentation](https://github.com/openai/whisper) - Model details
