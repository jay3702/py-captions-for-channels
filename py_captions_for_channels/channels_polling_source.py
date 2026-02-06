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

LOG = logging.getLogger(__name__)


@dataclass
class PartialProcessingEvent:
    timestamp: datetime
    title: str
    start_time: datetime
    source: str = "channels_polling"
    path: Optional[str] = None  # File path if known (polling source provides this)


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
        limit: int = 50,
        timeout: int = 10,
        max_age_hours: int = 2,
    ):
        """Initialize polling source.

        Args:
            api_url: Base URL of Channels DVR (e.g., http://192.168.3.150:8089)
            poll_interval_seconds: Base polling interval (default 2 minutes)
            limit: Maximum number of recent recordings to fetch per poll
            timeout: HTTP request timeout in seconds
        """
        self.api_url = api_url.rstrip("/")
        self.base_interval = poll_interval_seconds
        self.limit = limit
        self.timeout = timeout
        self.max_age_hours = max_age_hours
        self._api = ChannelsAPI(api_url, timeout=timeout)
        self._use_local_mock = LOCAL_TEST_DIR is not None

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

        while True:
            try:
                # Track recordings yielded in THIS poll cycle only
                # (cleared at start of each iteration)
                seen_this_cycle = set()

                # Update heartbeat file for UI
                try:
                    from pathlib import Path

                    heartbeat_file = Path.cwd() / "data" / "heartbeat_polling.txt"
                    heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
                    heartbeat_file.write_text(datetime.now(timezone.utc).isoformat())
                except Exception:
                    pass  # Don't fail on heartbeat

                # Use local mock scanner if LOCAL_TEST_DIR is set
                if self._use_local_mock:
                    LOG.debug("[MOCK] Scanning local test directory for recordings")
                    recordings = self._api._scan_local_recordings()
                else:
                    # Fetch recent recordings from API
                    resp = requests.get(
                        f"{self.api_url}/api/v1/all",
                        params={
                            "sort": "created_at",
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

                # Yield events for new completed recordings
                for rec in completed_recordings:
                    rec_id = rec.get("id") or rec.get("FileID")

                    if not rec_id:
                        LOG.warning("Recording missing ID: %s", rec.get("title"))
                        continue

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
                            LOG.info(
                                "Skipping older recording (>%dh): '%s' (created: %s)",
                                self.max_age_hours,
                                title,
                                start_time.strftime("%Y-%m-%d %H:%M:%S"),
                            )
                            continue
                    path = rec.get("path")  # Get file path from API

                    # Check if there's already an execution for this path
                    # Skip if pending/running/recently completed to avoid duplicates
                    if path:
                        try:
                            tracker = get_tracker()
                            all_execs = tracker.get_executions(limit=100)
                            existing = next(
                                (e for e in all_execs if e.get("path") == path), None
                            )
                            if existing:
                                status = existing.get("status")
                                # Skip if pending, running, or canceling
                                if status in ("pending", "running", "canceling"):
                                    LOG.debug(
                                        "Skipping recording with %s execution: '%s'",
                                        status,
                                        title,
                                    )
                                    continue
                                # Skip if recently completed (within 5 minutes)
                                if status == "completed":
                                    completed_at = existing.get("completed_at")
                                    if completed_at:
                                        try:
                                            comp_dt = datetime.fromisoformat(
                                                completed_at
                                            )
                                            if comp_dt.tzinfo is None:
                                                comp_dt = comp_dt.replace(
                                                    tzinfo=timezone.utc
                                                )
                                            age = (now - comp_dt).total_seconds() / 60.0
                                            if age < 5:  # Completed within 5 min
                                                LOG.debug(
                                                    "Skipping recently completed "
                                                    "recording: '%s' (%.1f min ago)",
                                                    title,
                                                    age,
                                                )
                                                continue
                                        except Exception:
                                            pass  # If parsing fails, proceed
                        except Exception as e:
                            LOG.debug("Error checking execution tracker: %s", e)
                            # Continue anyway - better to process twice than skip

                    LOG.info(
                        "New completed recording: '%s' (created: %s, path: %s)",
                        title,
                        start_time.strftime("%Y-%m-%d %H:%M:%S"),
                        path or "Unknown",
                    )

                    yield PartialProcessingEvent(
                        timestamp=now,
                        title=title,
                        start_time=start_time,
                        path=path,
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
                await asyncio.sleep(60)

            except Exception as e:
                LOG.error(
                    "Unexpected error in polling loop: %s (retrying in 60s)",
                    e,
                    exc_info=True,
                )
                await asyncio.sleep(60)
