from dataclasses import dataclass
from datetime import datetime

@dataclass
class ProcessingEvent:
    timestamp: datetime
    path: str
    title: str
    source: str

class Parser:
    """
    Normalizes raw events (log lines or JSON) into ProcessingEvent objects.
    """

    def from_channelwatch(self, partial_event, path: str) -> ProcessingEvent:
        return ProcessingEvent(
            timestamp=partial_event.timestamp,
            path=path,
            title=partial_event.title,
            source="channelwatch+api"
        )
