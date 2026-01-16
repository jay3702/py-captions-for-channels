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

    # Select event source based on configuration
    if USE_MOCK:
        from .mock_source import MockSource

        source = MockSource(interval_seconds=5)
    elif USE_WEBHOOK:
        from .channelwatch_webhook_source import ChannelWatchWebhookSource

        source = ChannelWatchWebhookSource(host=WEBHOOK_HOST, port=WEBHOOK_PORT)
    else:
        # WebSocket source (not currently working with ChannelWatch)
        from .channelwatch_source import ChannelWatchSource

        source = ChannelWatchSource(CHANNELWATCH_URL)

    # Initialize processing components
    api = ChannelsAPI(CHANNELS_API_URL)
    parser = Parser()
    state = StateBackend(STATE_FILE)
    pipeline = Pipeline(CAPTION_COMMAND, dry_run=DRY_RUN)

    # Process events as they arrive
    async for partial in source.events():
        if not state.should_process(partial.timestamp):
            continue

        try:
            path = api.lookup_recording_path(partial.title, partial.start_time)
            event = parser.from_channelwatch(partial, path)

            pipeline.run(event)
            state.update(event.timestamp)
        except RuntimeError as e:
            LOG.error("Failed to process event '%s': %s", partial.title, e)
            # Continue processing other events instead of crashing
            continue
        except Exception as e:
            LOG.error(
                "Unexpected error processing '%s': %s", partial.title, e, exc_info=True
            )
            continue
