from .channels_api import ChannelsAPI
from .parser import Parser
from .state import StateBackend
from .pipeline import Pipeline
from .config import (
    CHANNELWATCH_URL,
    CHANNELS_API_URL,
    CAPTION_COMMAND,
    STATE_FILE,
    USE_MOCK,
    USE_WEBHOOK,
    WEBHOOK_HOST,
    WEBHOOK_PORT,
    DRY_RUN,
)


async def main():
"""Main watcher loop - receives events and processes recordings."""
import logging
import sys

LOG = logging.getLogger(__name__)
LOG.info("Initializing py-captions-for-channels...")
LOG.info(
    "USE_MOCK=%s, USE_WEBHOOK=%s, DRY_RUN=%s", USE_MOCK, USE_WEBHOOK, DRY_RUN
)
sys.stdout.flush()

# Select event source based on configuration
if USE_MOCK:
    from .mock_source import MockSource
    LOG.info("Using MockSource")
    source = MockSource(interval_seconds=5)
elif USE_WEBHOOK:
    from .channelwatch_webhook_source import ChannelWatchWebhookSource
    LOG.info("Using ChannelWatchWebhookSource on %s:%d", WEBHOOK_HOST, WEBHOOK_PORT)
    source = ChannelWatchWebhookSource(host=WEBHOOK_HOST, port=WEBHOOK_PORT)
else:
    # WebSocket source (not currently working with ChannelWatch)
    from .channelwatch_source import ChannelWatchSource
    LOG.info("Using ChannelWatchSource")
    source = ChannelWatchSource(CHANNELWATCH_URL)

# Initialize processing components
api = ChannelsAPI(CHANNELS_API_URL)
parser = Parser()
state = StateBackend(STATE_FILE)
pipeline = Pipeline(CAPTION_COMMAND, dry_run=DRY_RUN)
    
LOG.info("All components initialized, starting event loop...")
sys.stdout.flush()

# Process events as they arrive
async for partial in source.events():
    LOG.info("Received event: %s", partial.title)
        
    if not state.should_process(partial.timestamp):
        LOG.info("Skipping already processed event")
        continue

    path = api.lookup_recording_path(partial.title, partial.start_time)
    event = parser.from_channelwatch(partial, path)

    pipeline.run(event)
    state.update(event.timestamp)
