
# syntax=docker/dockerfile:1

# --- Build stage: Compile FFmpeg with NVENC support ---
FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 AS ffmpeg-build

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

# Install nv-codec-headers and build FFmpeg in single layer to ensure pkg-config works
ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig
ARG FFMPEG_VERSION=6.1.1

RUN git clone https://github.com/FFmpeg/nv-codec-headers.git /tmp/nv-codec-headers && \
    cd /tmp/nv-codec-headers && \
    git checkout n11.1.5.3 && \
    make install && \
    ldconfig && \
    cd / && \
    rm -rf /tmp/nv-codec-headers && \
    git clone --branch n${FFMPEG_VERSION} --depth 1 https://github.com/FFmpeg/FFmpeg.git /ffmpeg && \
    cd /ffmpeg && \
    export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig && \
    echo "=== Debugging pkg-config ===" && \
    ls -la /usr/local/lib/pkgconfig/ffnvcodec.pc && \
    cat /usr/local/lib/pkgconfig/ffnvcodec.pc && \
    pkg-config --exists ffnvcodec && echo "pkg-config found ffnvcodec" && \
    pkg-config --modversion ffnvcodec && \
    echo "=== Running configure ===" && \
    ./configure \
    --prefix=/ffmpeg_build \
    --extra-cflags="-I/usr/local/include -I/usr/local/cuda/include" \
    --extra-ldflags="-L/usr/local/lib -L/usr/local/cuda/lib64" \
    --extra-libs="-lpthread -lm" \
    --bindir=/ffmpeg_build/bin \
    --enable-gpl \
    --enable-nonfree \
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
    --enable-cuda-nvcc \
    --enable-libnpp \
    --enable-nvenc \
    --enable-cuda \
    --disable-debug \
    --disable-doc \
    --disable-static \
    --enable-shared \
    && make -j$(nproc) && make install

# --- Runtime stage ---
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tzdata \
    libx264-163 \
    libx265-199 \
    libnuma1 \
    libvpx7 \
    libfdk-aac2 \
    libmp3lame0 \
    libopus0 \
    libass9 \
    libfreetype6 \
    libfontconfig1 \
    libfribidi0 \
    libxcb1 \
    libxcb-shm0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libssl3 \
    git \
    cmake \
    build-essential \
    libncurses5-dev \
    libdrm-dev \
    libudev-dev \
    && rm -rf /var/lib/apt/lists/*

# Build and install NVTOP
RUN git clone https://github.com/Syllo/nvtop.git /tmp/nvtop && \
    cd /tmp/nvtop && \
    git checkout 3.3.2 && \
    mkdir build && \
    cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make && \
    make install && \
    cd / && \
    rm -rf /tmp/nvtop

RUN ln -sf /usr/bin/python3 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt ./

# Install PyTorch with CUDA 11.8 support explicitly FIRST
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Copy FFmpeg from build stage
COPY --from=ffmpeg-build /ffmpeg_build/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-build /ffmpeg_build/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=ffmpeg-build /ffmpeg_build/lib/ /usr/local/lib/

# Update library cache so FFmpeg libraries are found
RUN ldconfig

# Install FFmpeg dev packages temporarily for av package compilation
RUN apt-get update && apt-get install -y \
    pkg-config \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    && rm -rf /var/lib/apt/lists/*

# Install remaining requirements (av will compile against FFmpeg)
RUN pip install --no-cache-dir -r requirements.txt

# Remove FFmpeg dev packages (no longer needed after av is compiled)
RUN apt-get remove -y \
    pkg-config \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    && apt-get autoremove -y

# Install Glances with GPU plugin support and orjson for API responses
RUN pip install --no-cache-dir 'glances[gpu]==4.0.5' orjson
ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# Copy application code
COPY py_captions_for_channels/ ./py_captions_for_channels/
COPY scripts/ ./scripts/
COPY whitelist.txt ./whitelist.txt

RUN chmod +x ./scripts/*.sh
RUN mkdir -p /app/data /app/logs

# Create startup script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Start Glances web server in background\n\
echo "Starting Glances web server on port 61208..."\n\
glances -w --disable-plugin quicklook,ports,irq,folders,raid &\n\
GLANCES_PID=$!\n\
echo "Glances started with PID $GLANCES_PID"\n\
\n\
# Wait a moment for Glances to start\n\
sleep 2\n\
\n\
# Start the main application\n\
echo "Starting py-captions-for-channels..."\n\
exec python -u -m py_captions_for_channels' > /app/start.sh && \
    chmod +x /app/start.sh

ENV PYTHONUNBUFFERED=1

EXPOSE 9000
EXPOSE 8000
EXPOSE 61208

# Default command
CMD ["/app/start.sh"]
