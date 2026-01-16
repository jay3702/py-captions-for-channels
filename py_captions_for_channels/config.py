"""
Configuration settings for py-captions-for-channels.
"""

# ChannelWatch WebSocket endpoint (port 8501, not 8089)
CHANNELWATCH_URL = "ws://192.168.3.150:8501/events"

# Channels DVR API endpoint
CHANNELS_API_URL = "http://192.168.3.150:8089"

# Caption command to run (whisper or other captioning tool)
CAPTION_COMMAND = "/usr/local/bin/whisper --model medium {path}"

# State file for tracking last processed timestamp
STATE_FILE = "/var/lib/py-captions/state.json"

# Channels DVR log path (for log-based source, if implemented)
LOG_PATH = "/share/CACHEDEV1_DATA/.qpkg/ChannelsDVR/channels-dvr.log"

# Event source configuration
USE_MOCK = False  # Use real API lookups
USE_WEBHOOK = False  # Use webhook receiver (HTTP POST from ChannelWatch)

# Webhook configuration (when USE_WEBHOOK=True)
WEBHOOK_HOST = "0.0.0.0"  # Listen on all interfaces
WEBHOOK_PORT = 9000  # Port for ChannelWatch webhook notifications

# Pipeline configuration
DRY_RUN = True  # If True, print commands instead of executing them
