import asyncio
import json
import random
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator

import websockets

LOG = logging.getLogger(__name__)


@dataclass
class PartialProcessingEvent:
    timestamp: datetime
    title: str
    start_time: datetime
    source: str = "channelwatch"


class ChannelWatchSource:
    """WebSocket event source for ChannelWatch.

    This implementation adds reconnection with exponential backoff and
    basic validation of incoming JSON messages. It yields
    `PartialProcessingEvent` objects for `recording_completed` events.
    """

    def __init__(self, url: str, base_delay: float = 1.0, max_delay: float = 30.0):
        self.url = url
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def events(self) -> AsyncIterator[PartialProcessingEvent]:
        attempt = 0
        while True:
            try:
                LOG.info("Connecting to ChannelWatch at %s", self.url)
                async with websockets.connect(self.url) as ws:
                    attempt = 0
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except json.JSONDecodeError:
                            LOG.debug("Received non-JSON message, ignoring")
                            continue

                        if data.get("event") != "recording_completed":
                            LOG.debug("Ignoring non recording_completed event")
                            continue

                        # Validate required fields
                        ts = data.get("timestamp")
                        title = data.get("title")
                        start = data.get("start_time")
                        if not (ts and title and start):
                            LOG.debug("Incomplete event received, skipping: %s", data)
                            continue

                        try:
                            timestamp = datetime.fromisoformat(ts)
                            start_time = datetime.fromisoformat(start)
                        except Exception:
                            LOG.debug(
                                "Invalid timestamp format, skipping event: %s", data
                            )
                            continue

                        yield PartialProcessingEvent(
                            timestamp=timestamp, title=title, start_time=start_time
                        )

            except Exception as exc:
                attempt += 1
                delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                # add jitter
                jitter = random.uniform(0, delay * 0.1)
                wait = delay + jitter
                LOG.warning(
                    (
                        "ChannelWatch connection failed (attempt %d): %s; "
                        "reconnecting in %.1fs"
                    ),
                    attempt,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
