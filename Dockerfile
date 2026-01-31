
# syntax=docker/dockerfile:1

# --- Build stage: Compile FFmpeg with NVENC support ---
FROM ubuntu:22.04 AS ffmpeg-build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    git \
    curl \
    ca-certificates \
    yasm \
    nasm \
    libx264-dev \
    libx265-dev \
    libnuma-dev \
    libvpx-dev \
    libfdk-aac-dev \
    libmp3lame-dev \
    libopus-dev \
    libass-dev \
    libfreetype6-dev \
    libfontconfig1-dev \
    libfribidi-dev \
    libxcb1-dev \
    libxcb-shm0-dev \
    libxcb-xfixes0-dev \
    libunistring-dev \
    libssl-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# nv-codec-headers
RUN git clone https://github.com/FFmpeg/nv-codec-headers.git && \
    cd nv-codec-headers && \
    make && make install

# FFmpeg
ARG FFMPEG_VERSION=6.1.1
RUN git clone --branch n${FFMPEG_VERSION} --depth 1 https://github.com/FFmpeg/FFmpeg.git ffmpeg
WORKDIR /ffmpeg
RUN ./configure \
    --prefix=/ffmpeg_build \
    --pkg-config-flags="--static" \
    --extra-cflags="-I/usr/local/include" \
    --extra-ldflags="-L/usr/local/lib" \
    --extra-libs="-lpthread -lm" \
    --bindir=/ffmpeg_build/bin \
    --enable-gpl \
    --enable-nonfree \
    --enable-cuda-nvcc \
    --enable-libnpp \
    --enable-nvenc \
    --enable-cuda \
    --enable-libx264 \
    --enable-libx265 \
    --enable-libvpx \
    --enable-libfdk-aac \
    --enable-libmp3lame \
    --enable-libopus \
    --enable-libass \
    --enable-libfreetype \
    --enable-libfontconfig \
    --enable-libfribidi \
    --enable-openssl \
    --disable-debug \
    --disable-doc \
    --disable-static \
    --enable-shared \
    && make -j$(nproc) && make install

# --- Runtime stage ---
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt ./

# Install PyTorch with CUDA 11.8 support explicitly FIRST
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Install remaining requirements (will skip torch since already installed)
RUN pip install --no-cache-dir -r requirements.txt

# Copy FFmpeg from build stage
COPY --from=ffmpeg-build /ffmpeg_build/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-build /ffmpeg_build/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=ffmpeg-build /ffmpeg_build/lib/ /usr/local/lib/
ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# Copy application code
COPY py_captions_for_channels/ ./py_captions_for_channels/
COPY scripts/ ./scripts/
COPY whitelist.txt ./whitelist.txt

RUN chmod +x ./scripts/*.sh
RUN mkdir -p /app/data /app/logs
ENV PYTHONUNBUFFERED=1

EXPOSE 9000
EXPOSE 8000

# Default command
CMD ["python", "-u", "-m", "py_captions_for_channels"]
