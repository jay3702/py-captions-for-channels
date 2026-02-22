"""Channels DVR polling source for automatic caption processing.

This source polls the Channels DVR API at regular intervals to discover
completed recordings that need captions. It uses smart timing to poll more
frequently near expected recording completion times.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Optional
import requests

from .channels_api import ChannelsAPI
from .config import LOCAL_TEST_DIR
from .execution_tracker import get_tracker
from .database import get_db
from .services.polling_cache_service import PollingCacheService
from .services.heartbeat_service import HeartbeatService
from .services.settings_service import SettingsService
from .whitelist import Whitelist

LOG = logging.getLogger(__name__)


@dataclass
class PartialProcessingEvent:
    timestamp: datetime
    title: str
    start_time: datetime
    source: str = "channels_polling"
    path: Optional[str] = None  # File path if known (polling source provides this)
    exec_id: Optional[str] = None  # Existing execution ID, if resuming


class ChannelsPollingSource:
    """Poll Channels DVR API for completed recordings that need captions.

    Features:
    - Smart timing: polls more frequently near hour/:30 marks when
      recordings typically end
    - Uses API limit parameter to fetch only recent recordings
    - Client-side filtering for completed but unprocessed
      recordings
    - Calculates next expected completion from created_at + duration
    - State file prevents duplicate processing
    """

    def __init__(
        self,
        api_url: str,
        poll_interval_seconds: int = 120,
        limit: int = 150,
        timeout: int = 10,
        max_age_hours: int = 24,
        max_queue_size: int = 5,
    ):
        """Initialize polling source.

        Args:
            api_url: Base URL of Channels DVR (e.g., http://192.168.3.150:8089)
            poll_interval_seconds: Base polling interval (default 2 minutes)
            limit: Maximum number of recent recordings to fetch per poll
            timeout: HTTP request timeout in seconds
            max_age_hours: Maximum age of recordings to consider (default 24 hours)
            max_queue_size: Maximum pending/running executions before pausing
                           queue growth (default 5)
        """
        self.api_url = api_url.rstrip("/")
        self.base_interval = poll_interval_seconds
        self.limit = limit
        self.timeout = timeout
        self.max_age_hours = max_age_hours
        self.max_queue_size = max_queue_size
        self._api = ChannelsAPI(api_url, timeout=timeout)
        self._use_local_mock = LOCAL_TEST_DIR is not None
        # Migration: Load old in-memory cache on first run
        self._migrated = False
        # Initialize empty whitelist (will be loaded from database on each check)
        self._whitelist = Whitelist(content="")

    def _reload_whitelist(self):
        """Reload whitelist from database to pick up changes immediately."""
        db = next(get_db())
        try:
            settings_service = SettingsService(db)
            whitelist_content = settings_service.get("whitelist", "")
            self._whitelist = Whitelist(content=whitelist_content)
        finally:
            db.close()

    def _get_smart_interval(self) -> int:
        """Calculate smart polling interval based on current time.

        Polls more frequently (60-120 seconds) near hour and half-hour marks
        when recordings typically end, less frequently (300 seconds) otherwise.

        Returns:
            Seconds until next poll
        """
        now = datetime.now(timezone.utc)
        minutes = now.minute

        # Near hour or half-hour (within 5 minutes after)
        if minutes <= 5 or (25 <= minutes <= 35) or minutes >= 55:
            # Poll every 1-2 minutes during high-activity windows
            return 60
        else:
            # Poll every 5 minutes during quiet periods
            return 300

    def _calculate_next_completion(self, recordings: list) -> Optional[datetime]:
        """Calculate when the next recording is expected to complete.

        Args:
            recordings: List of recording dicts from API

        Returns:
            Datetime of next expected completion, or None if none found
        """
        now = datetime.now(timezone.utc)
        next_completion = None

        for rec in recordings:
            if rec.get("completed"):
                continue  # Already completed

            created_at = rec.get("created_at", 0)
            duration = rec.get("duration", 0)

            if not created_at or not duration:
                continue

            # Calculate expected completion: start + duration + 5min
            # buffer for processing
            start_time = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
            expected_end = (
                start_time + timedelta(seconds=duration) + timedelta(minutes=5)
            )

            # Only consider future completions
            if expected_end > now:
                if next_completion is None or expected_end < next_completion:
                    next_completion = expected_end

        return next_completion

    async def events(self) -> AsyncIterator[PartialProcessingEvent]:
        """Yield events for completed recordings that need processing.

        Polls the Channels DVR API periodically, filtering for recordings
        that are completed but not yet processed for captions.
        """
        LOG.info(
            "Starting Channels DVR polling source: %s (interval: %ds, limit: %d)",
            self.api_url,
            self.base_interval,
            self.limit,
        )

        # Get database session for polling cache
        db = next(get_db())
        cache_service = PollingCacheService(db)
        heartbeat_service = HeartbeatService(db)

        # Cleanup old cache entries on startup (keep last 24 hours)
        cleaned = cache_service.cleanup_old(max_age_hours=24)
        if cleaned > 0:
            LOG.info("Cleaned %d old polling cache entries on startup", cleaned)

        while True:
            try:
                # Track recordings yielded in THIS poll cycle only
                # (cleared at start of each iteration)
                seen_this_cycle = set()

                def _resolve_start_time(exec_data: dict) -> datetime:
                    started_at = exec_data.get("started_at")
                    if started_at:
                        if isinstance(started_at, str):
                            try:
                                started_at = datetime.fromisoformat(started_at)
                            except ValueError:
                                started_at = None
                        if started_at:
                            if started_at.tzinfo is None:
                                started_at = started_at.replace(tzinfo=timezone.utc)
                            return started_at

                    job_id = exec_data.get("id", "")
                    if " @ " in job_id:
                        try:
                            _, timestamp_str = job_id.rsplit(" @ ", 1)
                            return datetime.strptime(
                                timestamp_str, "%Y-%m-%d %H:%M:%S"
                            ).replace(tzinfo=timezone.utc)
                        except (ValueError, AttributeError):
                            pass

                    return datetime.now(timezone.utc)

                # Promote discovered executions to pending to maintain queue depth
                # Strategy: Keep exactly 1 pending job so next job can start immediately
                try:
                    tracker = get_tracker()
                    all_executions = tracker.get_executions(limit=1000)

                    # Count pending jobs (not running, just waiting)
                    # Exclude manual_process jobs (handled by separate loop)
                    pending_execs = [
                        e
                        for e in all_executions
                        if e.get("status") == "pending"
                        and e.get("kind") != "manual_process"
                    ]
                    pending_count = len(pending_execs)

                    running_count = sum(
                        1
                        for e in all_executions
                        if e.get("status") == "running"
                        and e.get("kind") != "manual_process"
                    )

                    # If we have a pending job and nothing running, enqueue it
                    if pending_execs and running_count == 0:
                        pending_execs.sort(key=lambda x: x.get("started_at", ""))
                        exec = pending_execs[0]
                        exec_id = exec.get("id")
                        if not exec_id:
                            LOG.warning(
                                "Pending execution missing id: %s",
                                exec.get("title", "Unknown"),
                            )
                        else:
                            start_time = _resolve_start_time(exec)
                            yield PartialProcessingEvent(
                                timestamp=start_time,
                                title=exec.get("title", "Unknown"),
                                start_time=start_time,
                                path=exec.get("path"),
                                exec_id=exec_id,
                            )
                            LOG.info(
                                "Resuming pending execution: %s",
                                exec.get("title", "Unknown"),
                            )
                        # Only resume one pending job per cycle
                        continue

                    # Only promote if we have NO pending jobs (bootstrap case)
                    # Normal flow: job starts → promotes next discovered → pending
                    if pending_count == 0:
                        # Get discovered executions (oldest first by started_at)
                        # Exclude manual_process jobs (handled by separate loop)
                        discovered = [
                            e
                            for e in all_executions
                            if e.get("status") == "discovered"
                            and e.get("kind") != "manual_process"
                        ]

                        if discovered:
                            discovered.sort(key=lambda x: x.get("started_at", ""))
                            exec = discovered[0]

                            tracker.update_status(exec["id"], "pending")
                            LOG.info(
                                "Promoted discovered → pending (bootstrap): %s",
                                exec.get("title", "Unknown"),
                            )

                            # Yield the promoted execution for processing
                            exec_id = exec.get("id")
                            if not exec_id:
                                LOG.warning(
                                    "Promoted execution missing id: %s",
                                    exec.get("title", "Unknown"),
                                )
                            else:
                                start_time = _resolve_start_time(exec)
                                yield PartialProcessingEvent(
                                    timestamp=start_time,
                                    title=exec.get("title", "Unknown"),
                                    start_time=start_time,
                                    path=exec.get("path"),
                                    exec_id=exec_id,
                                )
                except Exception as e:
                    LOG.warning("Error promoting discovered executions: %s", e)

                # Update heartbeat in database
                try:
                    heartbeat_service.beat("polling", "alive")
                    LOG.info("Updated polling heartbeat")
                except Exception as e:
                    LOG.warning("Failed to update polling heartbeat: %s", e)

                # Use local mock scanner if LOCAL_TEST_DIR is set
                if self._use_local_mock:
                    LOG.debug("[MOCK] Scanning local test directory for recordings")
                    recordings = self._api._scan_local_recordings()
                else:
                    # Fetch recent recordings from API
                    resp = requests.get(
                        f"{self.api_url}/api/v1/all",
                        params={
                            "sort": "date_updated",
                            "order": "desc",
                            "limit": self.limit,
                        },
                        timeout=self.timeout,
                    )
                    resp.raise_for_status()
                    recordings = resp.json()

                LOG.debug("Polled API: %d recordings retrieved", len(recordings))

                # Filter for completed recordings (completed=true, processed may vary)
                # Note: API doesn't support server-side filtering for these fields
                completed_recordings = [
                    r for r in recordings if r.get("completed", False)
                ]

                LOG.debug(
                    "Found %d completed recordings (out of %d total)",
                    len(completed_recordings),
                    len(recordings),
                )

                # Track statistics for summary logging
                checked_count = 0
                skipped_cache_count = 0
                skipped_processed_count = 0
                skipped_old_count = 0
                yielded_count = 0

                # Yield events for new completed recordings
                for rec in completed_recordings:
                    rec_id = rec.get("id") or rec.get("FileID")

                    if not rec_id:
                        LOG.warning("Recording missing ID: %s", rec.get("title"))
                        continue

                    # Count as checked
                    checked_count += 1

                    # Skip if already yielded in this poll cycle
                    if rec_id in seen_this_cycle:
                        continue

                    # Mark as seen for this cycle
                    seen_this_cycle.add(rec_id)

                    # Extract details
                    title = rec.get("title", "Unknown")
                    created_at = rec.get("created_at", 0)
                    start_time = (
                        datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
                        if created_at
                        else datetime.now(timezone.utc)
                    )
                    now = datetime.now(timezone.utc)

                    # Skip older recordings beyond max_age_hours
                    # (disabled for local testing)
                    if self.max_age_hours is not None and not self._use_local_mock:
                        cutoff = now - timedelta(hours=self.max_age_hours)
                        if start_time < cutoff:
                            LOG.debug(
                                "Skipping older recording (>%dh): '%s' (created: %s)",
                                self.max_age_hours,
                                title,
                                start_time.strftime("%Y-%m-%d %H:%M:%S"),
                            )
                            skipped_old_count += 1
                            continue

                    # Queue management: check current active execution count
                    # before yielding new recordings
                    queue_full = False
                    try:
                        tracker = get_tracker()
                        all_executions = tracker.get_executions(limit=1000)
                        active_count = sum(
                            1
                            for e in all_executions
                            if e.get("status") in ("pending", "running")
                        )
                        if active_count >= self.max_queue_size:
                            queue_full = True
                            LOG.debug(
                                "Queue full (%d/%d active executions), "
                                "will create discovered entries for remaining",
                                active_count,
                                self.max_queue_size,
                            )
                    except Exception as e:
                        LOG.warning("Error checking queue size: %s", e)

                    # Check if we've already yielded this recording
                    # (using persistent database cache)
                    LOG.debug(
                        "Checking cache for rec_id=%s",
                        rec_id,
                    )
                    if cache_service.has_yielded(rec_id):
                        # Already processed, skip
                        LOG.debug(
                            "Skipping previously yielded recording: '%s'",
                            title,
                        )
                        skipped_cache_count += 1
                        continue

                    path = rec.get("path")  # Get file path from API

                    # Check if this recording has already been processed
                    # (execution tracker persists across restarts)
                    if path:
                        try:
                            tracker = get_tracker()
                            all_executions = tracker.get_executions(limit=1000)
                            existing_by_path = next(
                                (e for e in all_executions if e.get("path") == path),
                                None,
                            )
                            if existing_by_path:
                                status = existing_by_path.get("status")
                                # Skip if already processed/running/pending/discovered
                                if status in (
                                    "completed",
                                    "running",
                                    "pending",
                                    "discovered",
                                ):
                                    LOG.debug(
                                        "Skipping already tracked recording: '%s' "
                                        "(status: %s)",
                                        title,
                                        status,
                                    )
                                    skipped_processed_count += 1
                                    continue
                                # If failed or cancelled, allow retry (fall through)
                        except Exception as e:
                            LOG.warning("Error checking execution tracker: %s", e)

                    # Reload whitelist from database to pick up changes immediately
                    self._reload_whitelist()

                    # Check whitelist before creating discovered execution
                    if not self._whitelist.is_allowed(title, start_time):
                        LOG.debug(
                            "Skipping non-whitelisted recording: '%s' @ %s",
                            title,
                            start_time.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                        # Mark as yielded so we don't check it again
                        cache_service.add_yielded(rec_id)
                        skipped_processed_count += 1
                        continue

                    # If queue is full, create a "discovered" execution
                    # for backlog visibility
                    if queue_full:
                        try:
                            tracker = get_tracker()
                            job_id = (
                                f"{title} @ {start_time.strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                            tracker.start_execution(
                                job_id=job_id,
                                title=title,
                                path=path,
                                status="discovered",  # Mark as discovered, not pending
                                kind="polling",
                            )
                            LOG.info(
                                "Discovered recording (queue full): '%s' (created: %s)",
                                title,
                                start_time.strftime("%Y-%m-%d %H:%M:%S"),
                            )
                            # Mark as yielded so we don't re-discover it every poll
                            cache_service.add_yielded(rec_id)
                        except Exception as e:
                            LOG.warning("Error creating discovered execution: %s", e)
                        continue  # Don't yield, just record as discovered

                    LOG.info(
                        "New completed recording: '%s' (created: %s, path: %s)",
                        title,
                        start_time.strftime("%Y-%m-%d %H:%M:%S"),
                        path or "Unknown",
                    )

                    # Mark as yielded in database to prevent duplicates
                    cache_service.add_yielded(rec_id, now)
                    LOG.debug(
                        "Added rec_id=%s to database cache",
                        rec_id,
                    )

                    yielded_count += 1

                    yield PartialProcessingEvent(
                        timestamp=now,
                        title=title,
                        start_time=start_time,
                        path=path,
                    )

                # Log polling summary
                LOG.info(
                    "Poll complete: checked %d recordings, skipped %d (cache), "
                    "%d (already processed), yielded %d new",
                    checked_count,
                    skipped_cache_count,
                    skipped_processed_count,
                    yielded_count,
                )

                # Calculate smart wait time
                smart_interval = self._get_smart_interval()
                next_completion = self._calculate_next_completion(recordings)

                if next_completion:
                    seconds_until = (
                        next_completion - datetime.now(timezone.utc)
                    ).total_seconds()
                    # Wait until next completion, but cap at smart_interval
                    if 0 < seconds_until < smart_interval:
                        wait_time = int(seconds_until)
                        LOG.debug(
                            "Next completion expected in %ds, polling then",
                            wait_time,
                        )
                    else:
                        wait_time = smart_interval
                        LOG.debug(
                            "Next completion in %ds, using smart interval: %ds",
                            int(seconds_until) if seconds_until > 0 else 0,
                            wait_time,
                        )
                else:
                    wait_time = smart_interval
                    LOG.debug(
                        "No pending recordings, using smart interval: %ds", wait_time
                    )

                await asyncio.sleep(wait_time)

            except requests.RequestException as e:
                LOG.error("API polling failed: %s (retrying in 60s)", e)
                try:
                    db.rollback()
                except Exception:
                    pass
                await asyncio.sleep(60)

            except Exception as e:
                LOG.error(
                    "Unexpected error in polling loop: %s (retrying in 60s)",
                    e,
                    exc_info=True,
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                await asyncio.sleep(60)
