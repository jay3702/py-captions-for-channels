import asyncio
import websockets
import json
from dataclasses import dataclass
from datetime import datetime

@dataclass
class PartialProcessingEvent:
    timestamp: datetime
    title: str
    start_time: datetime
    source: str = "channelwatch"

class ChannelWatchSource:
    """
    WebSocket event source for ChannelWatch.
    Produces PartialProcessingEvent objects.
    """

    def __init__(self, url: str):
        self.url = url

    async def events(self):
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    async for msg in ws:
                        data = json.loads(msg)
                        if data.get("event") == "recording_completed":
                            yield PartialProcessingEvent(
                                timestamp=datetime.fromisoformat(data["timestamp"]),
                                title=data["title"],
                                start_time=datetime.fromisoformat(data["start_time"])
                            )
            except Exception:
                await asyncio.sleep(2)
