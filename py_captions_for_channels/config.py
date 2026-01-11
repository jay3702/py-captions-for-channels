"""
Configuration settings for py-captions-for-channels.
"""

CHANNELWATCH_URL = "ws://localhost:8089/events"
CHANNELS_API_URL = "http://localhost:8089"

CAPTION_COMMAND = "/usr/local/bin/whisper --model medium {path}"

#STATE_FILE = "/var/lib/py-captions/state.json"
STATE_FILE = "/var/lib/py-captions/state.json"

LOG_PATH = "/share/CACHEDEV1_DATA/.qpkg/ChannelsDVR/channels-dvr.log"
FAKE_MODE = True