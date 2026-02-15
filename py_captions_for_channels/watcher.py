import asyncio
from .logging.structured_logger import get_logger
from datetime import datetime, timezone
from functools import partial
from dataclasses import dataclass
from typing import Optional

import shutil
import os
import subprocess
import signal

from .logging_config import set_job_id
from .channels_api import ChannelsAPI
from .parser import Parser
from .state import StateBackend
from .pipeline import Pipeline
from .whitelist import Whitelist
from .health_check import run_health_checks
from .execution_tracker import get_tracker, build_manual_process_job_id
from .database import get_db, init_db
from .services.heartbeat_service import HeartbeatService
from .services.settings_service import SettingsService
from .shutdown_control import get_shutdown_controller
from .config import (
    CHANNELWATCH_URL,
    CHANNELS_API_URL,
    CAPTION_COMMAND,
    STATE_FILE,
    USE_MOCK,
    USE_WEBHOOK,
    USE_POLLING,
    WEBHOOK_HOST,
    WEBHOOK_PORT,
    POLL_INTERVAL_SECONDS,
    POLL_LIMIT,
    POLL_MAX_AGE_HOURS,
    POLL_MAX_QUEUE_SIZE,
    DRY_RUN,
    WHITELIST_FILE,
    STALE_EXECUTION_SECONDS,
    LOG_VERBOSITY_FILE,
    MANUAL_PROCESS_POLL_SECONDS,
)
from .logging_config import set_verbosity, get_verbosity
import json
from pathlib import Path

LOG = get_logger("watcher")

# Queue for pending polling detections
# (allows polling to continue while processing serially)
_polling_queue = asyncio.Queue()


def promote_next_discovered_to_pending():
    """
    Promote the next discovered execution to pending to maintain queue depth.
    Returns PartialProcessingEvent if promoted, None otherwise.

    Strategy: Maintain exactly 1 pending job so next job can start immediately
    when current job completes. Only promotes if no pending jobs exist.
    """
    tracker = get_tracker()
    all_executions = tracker.get_executions(limit=1000)

    # Count pending jobs (not running, just waiting)
    pending_count = sum(1 for e in all_executions if e.get("status") == "pending")

    # Only promote if we have NO pending jobs (keep exactly 1 pending queued)
    if pending_count > 0:
        return None

    # Get oldest discovered execution (by started_at)
    discovered = [e for e in all_executions if e.get("status") == "discovered"]
    if not discovered:
        return None

    discovered.sort(key=lambda x: x.get("started_at", ""))
    next_exec = discovered[0]

    # Promote to pending
    tracker.update_status(next_exec["id"], "pending")
    LOG.info(
        "Auto-promoted discovered → pending: %s",
        next_exec.get("title", "Unknown"),
    )

    # Create PartialProcessingEvent from execution data
    # Prefer stored started_at, fallback to job_id parsing
    from .channels_polling_source import PartialProcessingEvent

    exec_id = next_exec.get("id", "")
    start_time = None

    started_at = next_exec.get("started_at")
    if started_at:
        if isinstance(started_at, str):
            try:
                started_at = datetime.fromisoformat(started_at)
            except ValueError:
                started_at = None
        if started_at:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            start_time = started_at

    if start_time is None:
        job_id = exec_id or ""
        if " @ " in job_id:
            try:
                _, timestamp_str = job_id.rsplit(" @ ", 1)
                start_time = datetime.strptime(
                    timestamp_str, "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError) as e:
                LOG.warning(
                    "Failed to parse start_time from job_id '%s': %s", job_id, e
                )
                start_time = datetime.now(timezone.utc)
        else:
            start_time = datetime.now(timezone.utc)

    return PartialProcessingEvent(
        timestamp=start_time,
        title=next_exec.get("title", "Unknown"),
        start_time=start_time,
        path=next_exec.get("path"),
        exec_id=exec_id or None,
    )


async def process_manual_process_queue(state, pipeline, api, parser):
    """Check and process any manual process requests in the queue."""
    state._load()
    queue = state.get_manual_process_queue()
    if queue:
        LOG.info("Processing manual process queue: %d items", len(queue))
        tracker = get_tracker()

        # Create pending executions for all queued items that don't have one
        for path in queue:
            job_id = build_manual_process_job_id(path)
            existing = tracker.get_execution(job_id)

            # Check if there's already an active execution for this path
            # (including retries with timestamped IDs)
            all_execs = tracker.get_executions(limit=1000)
            path_has_active_exec = any(
                e.get("path") == path
                and e.get("status") in ("pending", "running", "discovered", "canceling")
                for e in all_execs
            )

            # Create pending execution only if:
            # 1. No execution exists for the base job_id, OR
            # 2. Previous execution is terminal AND no active retries exist
            should_create = False
            if not existing:
                should_create = True
            elif existing.get("status") in (
                "completed",
                "failed",
                "cancelled",
                "dry_run",
            ):
                if not path_has_active_exec:
                    should_create = True

            if should_create:
                filename = path.split("/")[-1]
                title = f"Manual: {filename}"
                tracker.start_execution(
                    job_id,
                    title,
                    path,
                    datetime.now(timezone.utc).isoformat(),
                    status="pending",
                    kind="manual_process",
                )
                LOG.debug("Created pending execution for queued item: %s", path)

        # Process items in queue
        for path in queue:
            _maybe_update_log_verbosity()

            # Check queue capacity before processing
            # Count currently running OR canceling executions
            all_execs = tracker.get_executions(limit=100)
            running_count = sum(
                1 for e in all_execs if e.get("status") in ("running", "canceling")
            )

            if running_count >= POLL_MAX_QUEUE_SIZE:
                LOG.info(
                    "Queue full (%d/%d running), deferring manual process: %s",
                    running_count,
                    POLL_MAX_QUEUE_SIZE,
                    path,
                )
                break  # Stop processing, will retry on next poll

            # Set job ID for this manual processing task
            job_id = build_manual_process_job_id(path)
            set_job_id(job_id)
            exec_id = None

            try:
                # Skip items that already failed (don't retry automatically)
                existing = tracker.get_execution(job_id)
                if existing and existing.get("status") == "failed":
                    LOG.info(
                        "Skipping failed item (use manual queue to retry): %s", path
                    )
                    continue

                LOG.info("Manual processing: %s", path)
                mpg_path = path
                orig_path = path + ".orig"
                srt_path = path.rsplit(".", 1)[0] + ".srt"

                # 1. If .orig exists, restore it
                if os.path.exists(orig_path):
                    LOG.info(
                        "Restoring original from .orig: %s -> %s",
                        orig_path,
                        mpg_path,
                    )
                    shutil.copy2(orig_path, mpg_path)
                # If .orig does not exist, proceed with current .mpg (no subtitle check)

                # 2. Remove existing .srt to force reprocessing
                if os.path.exists(srt_path):
                    LOG.info("Removing existing SRT for reprocessing: %s", srt_path)
                    os.remove(srt_path)

                # Create a minimal event from the path with settings
                filename = path.split("/")[-1]
                title = f"Manual: {filename}"

                # Load per-item settings for this manual process request
                item_settings = state.get_manual_process_settings(path)

                event = Parser().from_channelwatch(
                    type(
                        "PartialEvent",
                        (),
                        {
                            "timestamp": datetime.now(timezone.utc),
                            "title": filename,
                            "start_time": datetime.now(timezone.utc),
                        },
                    )(),
                    path,
                )

                # Load global settings for model,
                # but use per-item settings for skip/verbosity
                from .web_app import load_settings

                global_settings = load_settings()

                # Add settings to event for pipeline
                event.whisper_model = global_settings.get("whisper_model", "medium")
                event.log_verbosity = item_settings.get("log_verbosity", "NORMAL")
                event.skip_caption_generation = item_settings.get(
                    "skip_caption_generation", False
                )
                event.srt_path = None  # Let pipeline compute default

                # Start tracking execution
                existing = tracker.get_execution(job_id)
                if existing and existing.get("status") in ("running", "canceling"):
                    LOG.info("Manual process already running: %s", path)
                    continue

                # Update existing pending execution to running, or create new one
                if existing and existing.get("status") == "pending":
                    exec_id = job_id
                    tracker.update_execution(
                        job_id, status="running", started_at=event.timestamp.isoformat()
                    )
                    LOG.debug("Updated pending execution to running: %s", path)

                    # When job starts, promote next discovered → pending
                    promoted_event = promote_next_discovered_to_pending()
                    if promoted_event:
                        await _polling_queue.put(promoted_event)
                else:
                    exec_id = tracker.start_execution(
                        job_id,
                        title,
                        path,
                        event.timestamp.isoformat(),
                        status="running",
                        kind="manual_process",
                    )

                # Update job_id to the actual execution ID
                # (may have timestamp for reprocessing)
                set_job_id(exec_id)

                # Run pipeline in executor to not block event loop
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    partial(
                        pipeline.run,
                        event,
                        job_id_override=exec_id,
                        cancel_check=lambda: tracker.is_cancel_requested(exec_id),
                    ),
                )

                # Add pipeline output to execution logs
                if result.stdout:
                    for line in result.stdout.strip().split("\n"):
                        if line.strip():
                            tracker.add_log(exec_id, f"[stdout] {line}")
                if result.stderr:
                    for line in result.stderr.strip().split("\n"):
                        if line.strip():
                            tracker.add_log(exec_id, f"[stderr] {line}")

                # Complete execution tracking
                # For dry-run executions, mark as "dry_run" status
                # instead of "completed"
                if hasattr(result, "is_dry_run") and result.is_dry_run:
                    tracker.update_execution(
                        exec_id,
                        status="dry_run",
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        elapsed_seconds=result.elapsed_seconds,
                    )
                    LOG.info("Dry-run execution completed: %s", path)
                else:
                    tracker.complete_execution(
                        exec_id,
                        success=result.success,
                        elapsed_seconds=result.elapsed_seconds,
                        error=(
                            None
                            if result.success
                            else (
                                "Canceled"
                                if result.returncode == -2
                                else f"Exit code {result.returncode}"
                            )
                        ),
                    )

                if result.success:
                    LOG.info("Manual processing succeeded: %s", path)
                    pipeline._log_job_statistics(result, exec_id, LOG)
                    state.clear_manual_process_request(path)
                else:
                    LOG.error(
                        "Manual processing failed: %s (exit code %d)",
                        path,
                        result.returncode,
                    )
                    # Log stderr output for debugging
                    if result.stderr:
                        LOG.error("stderr output: %s", result.stderr.strip())
                    if result.stdout:
                        LOG.info("stdout output: %s", result.stdout.strip())
                    state.clear_manual_process_request(path)
                    LOG.warning(
                        "Removed failed manual process request after retry: %s",
                        path,
                    )

            except Exception as e:
                LOG.error(
                    "Error during manual processing of %s: %s", path, e, exc_info=True
                )
                if exec_id:
                    tracker.complete_execution(
                        job_id, success=False, elapsed_seconds=0, error=str(e)
                    )
                state.clear_manual_process_request(path)
                LOG.warning(
                    "Removed failed manual process request after retry: %s",
                    path,
                )
            finally:
                set_job_id(None)


def _maybe_update_log_verbosity() -> None:
    """Update log verbosity based on shared config file if present."""
    try:
        path = Path(LOG_VERBOSITY_FILE)
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        desired = str(data.get("verbosity", "")).upper()
        if desired and desired != get_verbosity():
            set_verbosity(desired)
            LOG.info("Log verbosity updated to %s", desired)
    except Exception as e:
        LOG.warning("Failed to update log verbosity: %s", e)


def cleanup_orphaned_processes():
    """Kill any existing whisper/caption processes from previous runs."""
    try:
        # Find all python processes running embed_captions or whisper
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        killed_count = 0
        for line in result.stdout.splitlines():
            if "embed_captions" in line or "/whisper " in line or "whisper/" in line:
                # Skip the grep process itself and this script
                if "ps aux" in line or "cleanup_orphaned" in line:
                    continue

                # Extract PID (second column)
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1])
                        LOG.info(
                            "Killing orphaned process (PID %d): %s",
                            pid,
                            " ".join(parts[10:15]),
                        )
                        os.kill(pid, signal.SIGTERM)
                        killed_count += 1
                    except (ValueError, ProcessLookupError, PermissionError) as e:
                        LOG.debug("Failed to kill PID %s: %s", parts[1], e)

        if killed_count > 0:
            LOG.info("Killed %d orphaned process(es)", killed_count)
        else:
            LOG.info("No orphaned processes found during startup cleanup")
    except Exception as e:
        LOG.warning("Failed to cleanup orphaned processes: %s", e)


async def main():
    """Main watcher loop - receives events and processes recordings."""

    LOG.info("=" * 80)
    LOG.info("Py Captions for Channels - Starting up")
    LOG.info("=" * 80)

    # Initialize database tables
    init_db()
    LOG.info("Database initialized")

    # Kill any orphaned processes from previous runs
    cleanup_orphaned_processes()

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

    # On container startup, reset any running/pending/interrupted jobs
    # back to discovered so promotion logic can control the single pending slot.
    all_execs = tracker.get_executions(limit=1000)
    running_execs = [e for e in all_execs if e.get("status") == "running"]
    pending_execs = [e for e in all_execs if e.get("status") == "pending"]
    interrupted_execs = [
        e
        for e in all_execs
        if e.get("status") == "completed"
        and e.get("success") is False
        and e.get("error", "").startswith("Execution interrupted by container restart")
    ]

    reset_count = 0
    for exec_data in running_execs + pending_execs + interrupted_execs:
        job_id = exec_data.get("id")
        if not job_id:
            continue
        tracker.update_execution(
            job_id,
            status="discovered",
            completed_at=None,
            success=None,
            error=None,
            elapsed_seconds=None,
        )
        reset_count += 1

    if reset_count:
        LOG.warning("Reset %d execution(s) to discovered after startup", reset_count)

    # Also check for stale executions (long-running beyond timeout)
    stale_count = tracker.mark_stale_executions(timeout_seconds=STALE_EXECUTION_SECONDS)
    if stale_count > 0:
        LOG.warning("Marked %d stale/interrupted executions as failed", stale_count)

        # Optionally queue interrupted executions for manual processing
        # (only if they haven't been retried already)
        interrupted_paths = tracker.get_interrupted_paths()
        if interrupted_paths:
            LOG.info(
                "Found %d interrupted executions. "
                "Consider manual processing if needed.",
                len(interrupted_paths),
            )
            # Note: We don't auto-queue to avoid infinite retry loops
            # User can manually trigger processing via web UI or state file

    # No explicit retry queueing here; recovered jobs stay discovered

    # Re-queue orphaned discovered/pending executions from previous run
    # These were interrupted and need to be processed
    all_executions = tracker.get_executions(limit=1000)
    orphaned_executions = [
        e for e in all_executions if e.get("status") in ("pending", "discovered")
    ]

    # Sort orphaned executions by started_at (oldest first) to maintain FIFO queue order
    orphaned_executions.sort(
        key=lambda e: e.get("started_at") or datetime.min.replace(tzinfo=timezone.utc)
    )

    if orphaned_executions:
        LOG.info(
            "Found %d orphaned execution(s) from previous run, "
            "will re-queue for processing",
            len(orphaned_executions),
        )

        # Load whitelist for filtering
        whitelist = Whitelist(WHITELIST_FILE)

        @dataclass
        class PartialProcessingEvent:
            timestamp: datetime
            title: str
            start_time: datetime
            source: str = "restart_recovery"
            path: Optional[str] = None
            exec_id: Optional[str] = None

        requeued_count = 0
        skipped_whitelist_count = 0
        first_discovered_promoted = False  # Track if we've promoted first discovered

        for execution in orphaned_executions:
            try:
                # Parse job_id format: "Title @ YYYY-MM-DD HH:MM:SS"
                job_id = execution["id"]
                if " @ " in job_id:
                    title, timestamp_str = job_id.rsplit(" @ ", 1)
                    start_time = datetime.strptime(
                        timestamp_str, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                else:
                    title = execution.get("title", "Unknown")
                    start_time = execution.get("started_at") or datetime.now(
                        timezone.utc
                    )

                # Check whitelist before re-queuing
                if not whitelist.is_allowed(title, start_time):
                    skipped_whitelist_count += 1
                    LOG.info(
                        "Skipped orphaned execution (not whitelisted): %s @ %s",
                        title,
                        start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    # Mark as failed instead of leaving it pending
                    if execution.get("status") in ("pending", "discovered"):
                        elapsed = 0.0
                        if execution.get("started_at"):
                            started_dt = execution.get("started_at")
                            if isinstance(started_dt, str):
                                started_dt = datetime.fromisoformat(started_dt)
                            if started_dt.tzinfo is None:
                                started_dt = started_dt.replace(tzinfo=timezone.utc)
                            elapsed = (
                                datetime.now(timezone.utc) - started_dt
                            ).total_seconds()
                        tracker.complete_execution(
                            job_id=job_id,
                            success=False,
                            elapsed_seconds=elapsed,
                            error="Not whitelisted for automatic processing",
                        )
                    continue

                # Promote ONLY the first discovered → pending (keep others discovered)
                # This maintains visibility in UI and creates proper chaining
                if (
                    execution.get("status") == "discovered"
                    and not first_discovered_promoted
                ):
                    tracker.update_status(execution["id"], "pending")
                    first_discovered_promoted = True
                    LOG.info(
                        "Promoted first orphaned discovered → pending: %s",
                        execution.get("title", "Unknown"),
                    )
                elif execution.get("status") == "discovered":
                    LOG.debug(
                        "Keeping as discovered (will be promoted later): %s",
                        execution.get("title", "Unknown"),
                    )

                event = PartialProcessingEvent(
                    title=title,
                    start_time=start_time,
                    timestamp=start_time,
                    path=execution.get("path"),
                    exec_id=job_id,
                )

                # Add to queue for processing
                # (will be picked up by polling processor)
                asyncio.create_task(_polling_queue.put(event))
                requeued_count += 1
                LOG.info(
                    "Re-queued orphaned execution: %s",
                    execution.get("title", "Unknown"),
                )
            except Exception as e:
                LOG.warning(
                    "Error re-queuing orphaned execution %s: %s",
                    execution.get("id", "unknown"),
                    e,
                )

        if requeued_count > 0 or skipped_whitelist_count > 0:
            LOG.info(
                "Startup recovery complete: %d re-queued, %d skipped (not whitelisted)",
                requeued_count,
                skipped_whitelist_count,
            )

    LOG.info("=" * 80)

    def _normalize_discovery_mode(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        mode_value = value.strip().lower()
        if mode_value in ("mock", "polling", "webhook"):
            return mode_value
        return None

    def _read_discovery_mode_setting() -> Optional[str]:
        mode = None
        db_gen = get_db()
        try:
            db = next(db_gen)
            settings_service = SettingsService(db)
            mode = settings_service.get("discovery_mode")
        except Exception as e:
            LOG.warning("Failed to read discovery_mode setting: %s", e)
        finally:
            try:
                next(db_gen)
            except Exception:
                pass
        return _normalize_discovery_mode(mode)

    def _resolve_discovery_mode() -> str:
        """Resolve discovery mode from settings or env defaults."""
        mode = _read_discovery_mode_setting()

        if mode:
            return mode

        if USE_MOCK:
            return "mock"
        if USE_POLLING:
            return "polling"
        if USE_WEBHOOK:
            return "webhook"
        return "websocket"

    discovery_mode = _resolve_discovery_mode()
    LOG.info("Discovery mode: %s", discovery_mode)

    async def _watch_discovery_mode():
        shutdown_controller = get_shutdown_controller()
        while True:
            if shutdown_controller.is_shutdown_requested():
                break
            await asyncio.sleep(5)
            new_mode = _read_discovery_mode_setting()
            if new_mode and new_mode != discovery_mode:
                LOG.warning(
                    "Discovery mode changed (%s -> %s); restarting watcher",
                    discovery_mode,
                    new_mode,
                )
                shutdown_controller.request_graceful_shutdown(
                    initiated_by="discovery_mode_change"
                )
                break

    _ = asyncio.ensure_future(_watch_discovery_mode())

    # Now select and initialize event source (may start background services)
    if discovery_mode == "mock":
        from .mock_source import MockSource

        source = MockSource(interval_seconds=5)
    elif discovery_mode == "polling":
        from .channels_polling_source import ChannelsPollingSource

        source = ChannelsPollingSource(
            api_url=CHANNELS_API_URL,
            poll_interval_seconds=POLL_INTERVAL_SECONDS,
            limit=POLL_LIMIT,
            max_age_hours=POLL_MAX_AGE_HOURS,
            max_queue_size=POLL_MAX_QUEUE_SIZE,
        )
    elif discovery_mode == "webhook":
        from .channelwatch_webhook_source import ChannelWatchWebhookSource

        source = ChannelWatchWebhookSource(host=WEBHOOK_HOST, port=WEBHOOK_PORT)
    else:
        # WebSocket source (not currently working with ChannelWatch)
        from .channelwatch_source import ChannelWatchSource

        source = ChannelWatchSource(CHANNELWATCH_URL)

    # Initialize remaining processing components
    parser = Parser()
    state = StateBackend(STATE_FILE)

    # Auto-detect caption command if not explicitly set
    caption_cmd = CAPTION_COMMAND
    if not caption_cmd or caption_cmd == 'echo "Would process: {path}"':
        # Auto-detect based on TRANSCODE_FOR_FIRETV setting
        import sys
        from .config import get_env_bool

        if get_env_bool("TRANSCODE_FOR_FIRETV", False):
            caption_cmd = (
                f"{sys.executable} -m py_captions_for_channels.embed_captions "
                "--input {path}"
            )
            print("Auto-detected: embed_captions (TRANSCODE_FOR_FIRETV=true)")
        else:
            caption_cmd = (
                "whisper --model medium --output_format srt --output_dir "
                '"$(dirname {path})" {path}'
            )
            print("Auto-detected: whisper (TRANSCODE_FOR_FIRETV=false)")

    pipeline = Pipeline(caption_cmd, dry_run=DRY_RUN)
    whitelist = Whitelist(WHITELIST_FILE)

    # Clean up stale manual process executions from previous runs
    # Only clear 'running' items (interrupted by restart)
    # Keep 'pending' items (safe to retry) and 'failed' items
    # (don't retry automatically)
    tracker = get_tracker()
    all_executions = tracker.get_executions()
    stale_count = 0
    for exec_data in all_executions:
        if (
            exec_data.get("kind") == "manual_process"
            and exec_data.get("status") == "running"
        ):
            job_id = exec_data.get("id")
            LOG.warning(
                "Clearing stale manual process execution (was running): %s", job_id
            )
            tracker.complete_execution(
                job_id, success=False, elapsed_seconds=0, error="Interrupted by restart"
            )
            stale_count += 1
    if stale_count > 0:
        LOG.info("Cleared %d stale manual process executions", stale_count)

    # Background loop for manual process queue
    async def _manual_process_loop():
        LOG.info(
            "Starting manual process background loop (interval: %ds)",
            MANUAL_PROCESS_POLL_SECONDS,
        )
        # Get database session for heartbeat
        db = next(get_db())
        heartbeat_service = HeartbeatService(db)
        shutdown_controller = get_shutdown_controller()

        try:
            while True:
                # Check for shutdown request
                if shutdown_controller.is_shutdown_requested():
                    LOG.info("Shutdown requested, stopping manual process loop")
                    break

                await asyncio.sleep(MANUAL_PROCESS_POLL_SECONDS)
                LOG.debug("Manual process loop checking queue...")
                # Update heartbeat in database
                try:
                    heartbeat_service.beat("manual", "alive")
                    LOG.debug("Updated manual heartbeat")
                except Exception as e:
                    LOG.warning("Failed to update manual heartbeat: %s", e)
                try:
                    await process_manual_process_queue(state, pipeline, api, parser)
                except Exception as e:
                    LOG.error("Error processing manual queue: %s", e, exc_info=True)
        except asyncio.CancelledError:
            LOG.info("Manual process loop cancelled")
        except Exception as e:
            LOG.error("Fatal error in manual process loop: %s", e, exc_info=True)

    # Use ensure_future to guarantee the task is scheduled
    manual_process_task = asyncio.ensure_future(_manual_process_loop())
    LOG.info("Manual process background task started")
    # Give the event loop a chance to schedule the task
    await asyncio.sleep(0)

    # Background loop to process polling queue serially
    async def _polling_processor_loop():
        LOG.info("Starting polling processor background loop")
        shutdown_controller = get_shutdown_controller()
        try:
            while True:
                # Check for immediate shutdown (emergency stop)
                if shutdown_controller.is_immediate_shutdown():
                    LOG.warning("Immediate shutdown requested, stopping processor loop")
                    break

                # Get next item from queue (blocks until available)
                event_partial = await _polling_queue.get()

                try:
                    # Check for graceful shutdown (finish current job only)
                    if shutdown_controller.is_graceful_shutdown():
                        LOG.info(
                            "Graceful shutdown requested, skipping new job: %s",
                            event_partial.title,
                        )
                        # Put the event back on the queue for next restart
                        # (it will be orphaned and picked up on next startup)
                        _polling_queue.task_done()
                        continue

                    _maybe_update_log_verbosity()

                    # Set job ID for this processing task
                    # Include date to avoid daily collisions
                    # start_time might be datetime or string depending on source
                    start_time_str = event_partial.start_time
                    if isinstance(start_time_str, datetime):
                        start_time_str = start_time_str.strftime("%Y-%m-%d %H:%M:%S")
                    job_id = f"{event_partial.title} @ {start_time_str}"
                    set_job_id(job_id)

                    tracker = get_tracker()
                    exec_id = None

                    try:
                        # Use path from event if provided (polling source),
                        # otherwise lookup
                        if hasattr(event_partial, "path") and event_partial.path:
                            path = event_partial.path
                            LOG.debug("Using path from event: %s", path)
                        else:
                            path = api.lookup_recording_path(
                                event_partial.title, event_partial.start_time
                            )
                        event = parser.from_channelwatch(event_partial, path)

                        # Use exec_id from event if provided (from startup recovery),
                        # otherwise use the job_id (created when added to queue)
                        exec_id = (
                            event_partial.exec_id
                            if hasattr(event_partial, "exec_id")
                            and event_partial.exec_id
                            else job_id
                        )

                        # Update to running when we actually start processing
                        tracker.update_status(exec_id, "running")

                        # When job starts, promote next discovered → pending
                        promoted_event = promote_next_discovered_to_pending()
                        if promoted_event:
                            await _polling_queue.put(promoted_event)

                        # Run pipeline in executor to not block event loop
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            None,
                            partial(
                                pipeline.run,
                                event,
                                job_id_override=exec_id,
                                cancel_check=lambda: tracker.is_cancel_requested(
                                    exec_id
                                ),
                            ),
                        )

                        # Add pipeline output to execution logs
                        if result.stdout:
                            for line in result.stdout.strip().split("\n"):
                                if line.strip():
                                    tracker.add_log(exec_id, f"[stdout] {line}")
                        if result.stderr:
                            for line in result.stderr.strip().split("\n"):
                                if line.strip():
                                    tracker.add_log(exec_id, f"[stderr] {line}")

                        # Complete execution tracking
                        # For dry-run executions, mark as "dry_run"
                        # status instead of "completed"
                        if hasattr(result, "is_dry_run") and result.is_dry_run:
                            tracker.update_execution(
                                exec_id,
                                status="dry_run",
                                completed_at=datetime.now(timezone.utc).isoformat(),
                                elapsed_seconds=result.elapsed_seconds,
                            )
                            LOG.info("Dry-run execution completed: %s", event.path)
                        else:
                            tracker.complete_execution(
                                exec_id,
                                success=result.success,
                                elapsed_seconds=result.elapsed_seconds,
                                error=(
                                    None
                                    if result.success
                                    else (
                                        "Canceled"
                                        if result.returncode == -2
                                        else (f"Exit code " f"{result.returncode}")
                                    )
                                ),
                            )

                        if result.success:
                            pipeline._log_job_statistics(result, exec_id, LOG)
                        else:
                            # Log stderr output for failed jobs
                            if result.stderr:
                                LOG.error("stderr output: %s", result.stderr.strip())
                            if result.stdout:
                                LOG.info("stdout output: %s", result.stdout.strip())

                        # Only update state if not a dry-run
                        if not (hasattr(result, "is_dry_run") and result.is_dry_run):
                            state.update(event.timestamp)

                        # Clear any manual process request for this path
                        # after successful processing
                        state.clear_manual_process_request(event.path)

                    except RuntimeError as e:
                        LOG.error(
                            "Failed to process event '%s': %s", event_partial.title, e
                        )
                        if exec_id:
                            tracker.complete_execution(
                                exec_id, success=False, elapsed_seconds=0, error=str(e)
                            )

                    except Exception as e:
                        LOG.error(
                            "Unexpected error processing '%s': %s",
                            event_partial.title,
                            e,
                            exc_info=True,
                        )
                        if exec_id:
                            tracker.complete_execution(
                                exec_id, success=False, elapsed_seconds=0, error=str(e)
                            )
                    finally:
                        set_job_id(None)

                finally:
                    # Mark task as done in queue
                    _polling_queue.task_done()

        except asyncio.CancelledError:
            LOG.info("Polling processor loop cancelled")
        except Exception as e:
            LOG.error("Fatal error in polling processor loop: %s", e, exc_info=True)

    # Start the polling processor task
    _ = asyncio.ensure_future(_polling_processor_loop())
    LOG.info("Polling processor background task started")
    await asyncio.sleep(0)

    # Track last manual queue check
    last_manual_check = datetime.now()

    # Get shutdown controller for main loop
    shutdown_controller = get_shutdown_controller()

    # Process events as they arrive - add to queue for serial processing
    async for event_partial in source.events():
        # Check for shutdown request (both graceful and immediate)
        if shutdown_controller.is_shutdown_requested():
            LOG.warning(
                "Shutdown requested (%s), stopping event processing",
                (
                    "graceful"
                    if shutdown_controller.is_graceful_shutdown()
                    else "immediate"
                ),
            )
            break

        # Also check manual queue periodically (every 5 seconds)
        now = datetime.now()
        if (now - last_manual_check).total_seconds() > 5:
            # Non-blocking check of manual queue
            asyncio.create_task(
                process_manual_process_queue(state, pipeline, api, parser)
            )
            last_manual_check = now

        _maybe_update_log_verbosity()

        # start_time might be datetime or string depending on source
        start_time_str = event_partial.start_time
        if isinstance(start_time_str, datetime):
            start_time_str = start_time_str.strftime("%Y-%m-%d %H:%M:%S")
        job_id = f"{event_partial.title} @ {start_time_str}"

        tracker = get_tracker()
        existing_by_id = tracker.get_execution(job_id)
        bypass_state_check = False
        if existing_by_id and existing_by_id.get("status") in (
            "pending",
            "discovered",
        ):
            bypass_state_check = True

        if not bypass_state_check and not state.should_process(event_partial.timestamp):
            continue

        # Check whitelist
        if not whitelist.is_allowed(event_partial.title, event_partial.start_time):
            continue

        # Use path from event if provided (polling source), otherwise lookup
        if hasattr(event_partial, "path") and event_partial.path:
            path = event_partial.path
        else:
            path = api.lookup_recording_path(
                event_partial.title, event_partial.start_time
            )

        # Check if this exact recording (by path) has been processed
        # Handles job_id format changes and multiple recordings, same title
        all_executions = tracker.get_executions(limit=1000)
        existing_by_path = next(
            (e for e in all_executions if e.get("path") == path), None
        )
        existing_by_id = tracker.get_execution(job_id)

        # Determine if we should create a new execution
        should_create = False
        reason = ""

        if existing_by_path:
            if (
                existing_by_path.get("status") == "completed"
                and existing_by_path.get("success") is True
            ):
                LOG.debug(
                    "Skipping - recording already completed: %s (path: %s)",
                    event_partial.title,
                    path,
                )
                should_create = False
            elif existing_by_path.get("status") == "failed":
                should_create = True
                reason = "Reprocessing failed recording"
            elif existing_by_path.get("status") in ("pending", "running"):
                LOG.debug(
                    "Skipping - execution already %s: %s",
                    existing_by_path.get("status"),
                    event_partial.title,
                )
                should_create = False
        elif existing_by_id:
            # Job ID exists but path differs - different recording, same title/time
            if existing_by_id.get("status") in ("pending", "running"):
                LOG.debug(
                    "Skipping - execution already %s: %s",
                    existing_by_id.get("status"),
                    event_partial.title,
                )
                should_create = False
            else:
                # Completed or failed with different path - likely new recording
                should_create = True
                reason = "New recording"
        else:
            # No existing execution found
            should_create = True
            reason = "New recording"

        if should_create:
            _ = tracker.start_execution(
                job_id,
                event_partial.title,
                path,
                event_partial.timestamp.isoformat(),
                status="discovered",
            )
            LOG.info("Added to processing queue: %s (%s)", event_partial.title, reason)

        # Add to queue for processing (non-blocking)
        await _polling_queue.put(event_partial)

    # Event loop ended - cleanup and exit
    LOG.info("=" * 80)
    if shutdown_controller.is_shutdown_requested():
        shutdown_type = (
            "graceful" if shutdown_controller.is_graceful_shutdown() else "immediate"
        )
        LOG.warning("Shutdown requested (%s) - exiting application", shutdown_type)

        # For graceful shutdown, wait for current job to complete
        if shutdown_controller.is_graceful_shutdown():
            tracker = get_tracker()
            all_executions = tracker.get_executions(limit=1000)
            running = [e for e in all_executions if e.get("status") == "running"]
            if running:
                LOG.info(
                    "Waiting for current job to complete: %s",
                    running[0].get("title", "Unknown"),
                )
                # Wait for job to finish (check every 2 seconds)
                while running:
                    await asyncio.sleep(2)
                    all_executions = tracker.get_executions(limit=1000)
                    running = [
                        e for e in all_executions if e.get("status") == "running"
                    ]
                LOG.info("Current job completed, proceeding with shutdown")
    else:
        LOG.info("Event loop ended normally")

    manual_process_task.cancel()
