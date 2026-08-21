
# syntax=docker/dockerfile:1

# --- Build stage: Compile FFmpeg with NVENC support ---
FROM nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04 AS ffmpeg-build

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
    libva-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install nv-codec-headers and build FFmpeg in single layer to ensure pkg-config works
ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig
ARG FFMPEG_VERSION=6.1.1
# Bump FFMPEG_CACHE_BUST to force a full ffmpeg recompile (invalidates GHA layer cache)
ARG FFMPEG_CACHE_BUST=2026-08-21-vaapi

RUN echo "FFmpeg build: version=${FFMPEG_VERSION}, bust=${FFMPEG_CACHE_BUST}" && \
    git clone https://github.com/FFmpeg/nv-codec-headers.git /tmp/nv-codec-headers && \
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
    --enable-vaapi \
    --disable-debug \
    --disable-doc \
    --disable-static \
    --enable-shared \
    && make -j$(nproc) && make install

# --- Build stage: Compile whisper.cpp's Parakeet CLI, CPU-only ---
# Separate lightweight (non-CUDA) stage since this build is deliberately
# CPU-only for now — see py_captions_for_channels/parakeet_transcribe.py for
# why (the GPU/Vulkan backend crashed reliably in testing). GGML_NATIVE=OFF
# targets a portable AVX2/SSE4.2/BMI2/FMA baseline instead of -march=native,
# since the machine that builds this image is never the machine that runs
# it — that baseline covers any x86_64 CPU from roughly 2013 onward,
# including low-power targets like an Intel N100/N95.
FROM ubuntu:22.04 AS parakeet-build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    && rm -rf /var/lib/apt/lists/*

# Bump PARAKEET_CACHE_BUST to force a rebuild (invalidates GHA layer cache)
ARG PARAKEET_CACHE_BUST=2026-08-14

RUN git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git /whisper.cpp && \
    cd /whisper.cpp && \
    cmake -B build -DGGML_NATIVE=OFF && \
    cmake --build build -j$(nproc) --target parakeet-cli

# --- Runtime stage ---
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

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
    libgomp1 \
    libva2 \
    libva-drm2 \
    intel-media-va-driver \
    vainfo \
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

# Install PyTorch with CUDA 12.1 support (compatible with CUDA 12.2 runtime and driver 535)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu121

# Copy FFmpeg from build stage
COPY --from=ffmpeg-build /ffmpeg_build/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-build /ffmpeg_build/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=ffmpeg-build /ffmpeg_build/lib/ /usr/local/lib/

# Copy Parakeet CLI (CPU-only) and its shared libs from build stage.
# Path matches PARAKEET_CLI_PATH in py_captions_for_channels/parakeet_transcribe.py.
COPY --from=parakeet-build /whisper.cpp/build/bin/parakeet-cli /usr/local/bin/parakeet-cli
COPY --from=parakeet-build /whisper.cpp/build/bin/libparakeet.so* /usr/local/lib/
COPY --from=parakeet-build /whisper.cpp/build/bin/libggml*.so* /usr/local/lib/

# Update library cache so FFmpeg/Parakeet libraries are found
RUN ldconfig

# Install remaining requirements (modern versions have pre-built wheels)
RUN pip install --no-cache-dir -r requirements.txt

# Install Glances with GPU plugin support and orjson for API responses
RUN pip install --no-cache-dir 'glances[gpu]==4.0.5' orjson
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib/wsl/lib:$LD_LIBRARY_PATH

# Copy application code
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
COPY py_captions_for_channels/ ./py_captions_for_channels/
COPY scripts/ ./scripts/
COPY whitelist_example.txt ./whitelist.txt
COPY .env.example ./.env.example

RUN chmod +x ./scripts/*.sh
RUN mkdir -p /app/data /app/logs

# Copy startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV PYTHONUNBUFFERED=1

EXPOSE 9000
EXPOSE 8000
EXPOSE 61208

# Default command
CMD ["/app/start.sh"]
