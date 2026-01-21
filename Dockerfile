# Use NVIDIA CUDA base image for GPU acceleration
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Install Python 3.10 (comes with Ubuntu 22.04) and system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.10 as default python
RUN ln -sf /usr/bin/python3 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt ./

# Install PyTorch with CUDA 11.8 support explicitly FIRST
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Install remaining requirements (will skip torch since already installed)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY py_captions_for_channels/ ./py_captions_for_channels/
COPY scripts/ ./scripts/
COPY whitelist.txt ./whitelist.txt

# Make scripts executable
RUN chmod +x ./scripts/*.sh

# Create directories for state and logs
RUN mkdir -p /app/data /app/logs

# Set Python to run in unbuffered mode (better for logs)
ENV PYTHONUNBUFFERED=1

# Expose webhook and web UI ports
EXPOSE 9000
EXPOSE 8000

# Run the watcher
CMD ["python", "-u", "-m", "py_captions_for_channels"]
