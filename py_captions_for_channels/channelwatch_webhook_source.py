import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator
from aiohttp import web

LOG = logging.getLogger(__name__)


@dataclass
class PartialProcessingEvent:
    timestamp: datetime
    title: str
    start_time: datetime
    source: str = "channelwatch_webhook"


class ChannelWatchWebhookSource:
    """HTTP webhook receiver for ChannelWatch events.

    ChannelWatch sends HTTP POST requests to our webhook endpoint when
    recording events occur. This class runs a simple HTTP server and
    yields events as they are received.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9000):
        self.host = host
        self.port = port
        self._queue = asyncio.Queue()
        self._app = None
        self._runner = None

    async def _handle_webhook(self, request):
        """Handle incoming webhook POST request from ChannelWatch."""
        try:
            data = await request.json()
            LOG.info("Received webhook: %s", data)

            # Validate this is a recording_completed event
            if data.get("event") != "recording_completed":
                LOG.debug("Ignoring non recording_completed event")
                return web.Response(text="OK")

            # Validate required fields
            ts = data.get("timestamp")
            title = data.get("title")
            start = data.get("start_time")

            if not (ts and title and start):
                LOG.warning("Incomplete event received, skipping: %s", data)
                return web.Response(text="OK", status=400)

            try:
                timestamp = datetime.fromisoformat(ts)
                start_time = datetime.fromisoformat(start)
            except Exception as e:
                LOG.warning("Invalid timestamp format: %s", e)
                return web.Response(text="Invalid timestamp", status=400)

            # Queue the event for processing
            event = PartialProcessingEvent(
                timestamp=timestamp, title=title, start_time=start_time
            )
            await self._queue.put(event)

            return web.Response(text="OK")

        except json.JSONDecodeError:
            LOG.warning("Received non-JSON webhook payload")
            return web.Response(text="Invalid JSON", status=400)
        except Exception as e:
            LOG.error("Error handling webhook: %s", e)
            return web.Response(text="Internal error", status=500)

    async def _start_server(self):
        """Start the webhook HTTP server."""
        self._app = web.Application()
        self._app.router.add_post("/", self._handle_webhook)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        LOG.info("Webhook server listening on %s:%d", self.host, self.port)

    async def events(self) -> AsyncIterator[PartialProcessingEvent]:
        """Start webhook server and yield events as they arrive."""
        await self._start_server()

        try:
            while True:
                event = await self._queue.get()
                yield event
        finally:
            if self._runner:
                await self._runner.cleanup()
