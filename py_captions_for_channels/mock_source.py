import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class PartialProcessingEvent:
    timestamp: datetime
    title: str
    start_time: datetime
    source: str = "mock"


class MockSource:
    """
    Emits synthetic recording-completed events for testing.
    """

    def __init__(self, interval_seconds: int = 5):
        self.interval = interval_seconds

    async def events(self):
        counter = 1
        while True:
            now = datetime.now()
            yield PartialProcessingEvent(
                timestamp=now,
                title=f"Test Recording {counter}",
                start_time=now - timedelta(hours=1),
            )
            counter += 1
            await asyncio.sleep(self.interval)
