import logging

from .logging_config import set_job_id
from .channels_api import ChannelsAPI
from .parser import Parser
from .state import StateBackend
from .pipeline import Pipeline
from .whitelist import Whitelist
from .health_check import run_health_checks
from .execution_tracker import get_tracker
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
    STALE_EXECUTION_SECONDS,
)

LOG = logging.getLogger(__name__)


async def process_reprocess_queue(state, pipeline, api, parser):
    """Check and process any reprocess requests in the queue."""
    queue = state.get_reprocess_queue()
    if queue:
        LOG.info("Processing reprocess queue: %d items", len(queue))
        tracker = get_tracker()
        for path in queue:
            # Set job ID for this reprocessing task
            job_id = f"[REPROCESS] {path.split('/')[-1]}"
            set_job_id(job_id)
            exec_id = None

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

                    # Start tracking execution
                    exec_id = tracker.start_execution(
                        job_id, filename, path, event.timestamp.isoformat()
                    )

                    result = pipeline.run(event)

                    # Add pipeline output to execution logs
                    if result.stdout:
                        for line in result.stdout.strip().split("\n"):
                            if line.strip():
                                tracker.add_log(job_id, f"[stdout] {line}")
                    if result.stderr:
                        for line in result.stderr.strip().split("\n"):
                            if line.strip():
                                tracker.add_log(job_id, f"[stderr] {line}")

                    # Complete execution tracking
                    tracker.complete_execution(
                        job_id,
                        success=result.success,
                        elapsed_seconds=result.elapsed_seconds,
                        error=(
                            None if result.success else f"Exit code {result.returncode}"
                        ),
                    )

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
                    if exec_id:
                        tracker.complete_execution(
                            job_id, success=False, elapsed_seconds=0, error=str(e)
                        )
            finally:
                set_job_id(None)


async def main():
    """Main watcher loop - receives events and processes recordings."""

    LOG.info("=" * 80)
    LOG.info("Py Captions for Channels - Starting up")
    LOG.info("=" * 80)

    # Initialize API first (needed for health checks)
    api = ChannelsAPI(CHANNELS_API_URL)

    # Run health checks BEFORE creating event source or other components
    if not await run_health_checks(api):
        LOG.error("Health checks failed. Aborting startup.")
        return

    LOG.info("=" * 80)
    LOG.info("All health checks passed! Starting event loop...")

    # Check for interrupted executions from previous run
    tracker = get_tracker()

    stale_count = tracker.mark_stale_executions(timeout_seconds=STALE_EXECUTION_SECONDS)
    if stale_count > 0:
        LOG.warning("Marked %d stale/interrupted executions as failed", stale_count)

        # Optionally queue interrupted executions for reprocessing
        # (only if they haven't been retried already)
        interrupted_paths = tracker.get_interrupted_paths()
        if interrupted_paths:
            LOG.info(
                "Found %d interrupted executions. "
                "Consider manual reprocessing if needed.",
                len(interrupted_paths),
            )
            # Note: We don't auto-queue to avoid infinite retry loops
            # User can manually trigger reprocessing via web UI or state file

    LOG.info("=" * 80)

    # Now select and initialize event source (may start background services)
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

    # Initialize remaining processing components
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

        tracker = get_tracker()
        exec_id = None

        try:
            path = api.lookup_recording_path(partial.title, partial.start_time)
            event = parser.from_channelwatch(partial, path)

            # Start tracking execution
            exec_id = tracker.start_execution(
                job_id, partial.title, event.path, event.timestamp.isoformat()
            )

            result = pipeline.run(event)

            # Add pipeline output to execution logs
            if result.stdout:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        tracker.add_log(job_id, f"[stdout] {line}")
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    if line.strip():
                        tracker.add_log(job_id, f"[stderr] {line}")

            # Complete execution tracking
            tracker.complete_execution(
                job_id,
                success=result.success,
                elapsed_seconds=result.elapsed_seconds,
                error=None if result.success else f"Exit code {result.returncode}",
            )

            if result.success:
                pipeline._log_job_statistics(result, job_id)
            state.update(event.timestamp)
            # Clear any reprocess request for this path after successful processing
            state.clear_reprocess_request(event.path)
        except RuntimeError as e:
            LOG.error("Failed to process event '%s': %s", partial.title, e)
            if exec_id:
                tracker.complete_execution(
                    job_id, success=False, elapsed_seconds=0, error=str(e)
                )
        except Exception as e:
            LOG.error(
                "Unexpected error processing '%s': %s", partial.title, e, exc_info=True
            )
            if exec_id:
                tracker.complete_execution(
                    job_id, success=False, elapsed_seconds=0, error=str(e)
                )
        finally:
            set_job_id(None)
