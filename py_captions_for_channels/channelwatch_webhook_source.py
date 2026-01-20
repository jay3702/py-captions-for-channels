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
        """Handle incoming webhook POST request from ChannelWatch via Apprise."""
        try:
            data = await request.json()

            # Log summary without attachments to avoid base64 clutter
            title = data.get("title", "")
            message = data.get("message", "")
            msg_preview = message[:100] if message else ""
            LOG.info("Received webhook: title='%s' message='%s...'", title, msg_preview)
            LOG.debug("Full webhook payload: %s", data)

            # Parse Apprise notification format
            # title = data.get("title", "")  # Already extracted above
            # message = data.get("message", "")  # Already extracted above

            # Check if this is a recording event
            if "Recording Event" not in title:
                LOG.debug("Ignoring non-recording event: %s", title)
                return web.Response(text="OK")

            # Parse the message to extract event details
            # Message format from ChannelWatch/Apprise:
            # ?? CHANNEL-NAME
            # Channel: X.X
            # Status: ?? Stopped (or ?? Started)
            # Program: PROGRAM NAME
            # Description...
            # -----------------------
            # Duration: X minute
            program_title = None
            status = None

            for line in message.split("\n"):
                if line.startswith("Program:"):
                    program_title = line.replace("Program:", "").strip()
                elif line.startswith("Status:"):
                    status = line.replace("Status:", "").strip()

            if not program_title:
                LOG.warning("Could not parse program title from message")
                return web.Response(text="OK")

            if not status:
                LOG.warning("Could not parse status from message")
                return web.Response(text="Invalid payload: missing status", status=400)

            # Only process completed recording events
            # ChannelWatch sends either "Stopped" or "Completed" status
            if "Stopped" not in status and "Completed" not in status:
                LOG.debug("Ignoring non-completed event: %s", status)
                return web.Response(text="OK")

            # Create event with current timestamp
            # Note: Apprise doesn't provide the original event timestamp,
            # so we use the current time
            timestamp = datetime.now()
            start_time = timestamp  # We don't have the actual start time

            event = PartialProcessingEvent(
                timestamp=timestamp, title=program_title, start_time=start_time
            )
            await self._queue.put(event)

            LOG.info("Queued recording completed event: %s", program_title)
            return web.Response(text="OK")

        except json.JSONDecodeError:
            LOG.warning("Received non-JSON webhook payload")
            return web.Response(text="Invalid JSON", status=400)
        except Exception as e:
            LOG.error("Error handling webhook: %s", e)
            return web.Response(text="Internal error", status=500)

    async def _start_server(self):
        """Start the webhook HTTP server."""
        # Increase max request size to handle large base64 image attachments
        # Default is 2MB, we'll allow up to 10MB
        self._app = web.Application(client_max_size=10 * 1024 * 1024)
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
