FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (if needed for whisper or other tools)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY py_captions_for_channels/ ./py_captions_for_channels/
COPY scripts/ ./scripts/

# Create directories for state and logs
RUN mkdir -p /app/data /app/logs

# Set Python to run in unbuffered mode (better for logs)
ENV PYTHONUNBUFFERED=1

# Expose webhook port
EXPOSE 9000

# Run the watcher
CMD ["python", "-u", "-m", "py_captions_for_channels"]
