import logging

from .logging_config import set_job_id
from .channels_api import ChannelsAPI
from .parser import Parser
from .state import StateBackend
from .pipeline import Pipeline
from .whitelist import Whitelist
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
    WHITELIST_FILE,
)

LOG = logging.getLogger(__name__)


async def process_reprocess_queue(state, pipeline, api, parser):
    """Check and process any reprocess requests in the queue."""
    queue = state.get_reprocess_queue()
    if queue:
        LOG.info("Processing reprocess queue: %d items", len(queue))
        for path in queue:
            # Set job ID for this reprocessing task
            job_id = f"[REPROCESS] {path.split('/')[-1]}"
            set_job_id(job_id)

            try:
                LOG.info("Reprocessing: %s", path)
                try:
                    # Create a minimal event from the path
                    # Use the filename as title for logging
                    filename = path.split("/")[-1]
                    event = Parser().from_channelwatch(
                        type(
                            "PartialEvent",
                            (),
                            {
                                "timestamp": __import__("datetime").datetime.now(),
                                "title": filename,
                                "start_time": __import__("datetime").datetime.now(),
                            },
                        )(),
                        path,
                    )
                    result = pipeline.run(event)
                    if result.success:
                        LOG.info("Reprocessing succeeded: %s", path)
                        pipeline._log_job_statistics(result, job_id)
                        state.clear_reprocess_request(path)
                    else:
                        LOG.error(
                            "Reprocessing failed: %s (exit code %d)",
                            path,
                            result.returncode,
                        )
                except Exception as e:
                    LOG.error(
                        "Error during reprocessing of %s: %s", path, e, exc_info=True
                    )
            finally:
                set_job_id(None)


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
    whitelist = Whitelist(WHITELIST_FILE)

    # Process reprocess queue on startup
    await process_reprocess_queue(state, pipeline, api, parser)

    # Process events as they arrive
    async for partial in source.events():
        if not state.should_process(partial.timestamp):
            continue

        # Check whitelist
        if not whitelist.is_allowed(partial.title, partial.start_time):
            continue

        # Set job ID for this processing task
        job_id = f"{partial.title} @ {partial.start_time.strftime('%H:%M:%S')}"
        set_job_id(job_id)

        try:
            path = api.lookup_recording_path(partial.title, partial.start_time)
            event = parser.from_channelwatch(partial, path)

            result = pipeline.run(event)
            if result.success:
                pipeline._log_job_statistics(result, job_id)
            state.update(event.timestamp)
            # Clear any reprocess request for this path after successful processing
            state.clear_reprocess_request(event.path)
        except RuntimeError as e:
            LOG.error("Failed to process event '%s': %s", partial.title, e)
        except Exception as e:
            LOG.error(
                "Unexpected error processing '%s': %s", partial.title, e, exc_info=True
            )
        finally:
            set_job_id(None)
