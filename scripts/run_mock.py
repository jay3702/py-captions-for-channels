#!/usr/bin/env python3
"""
Simple runner that exercises `MockSource` and prints a small number of events.
Usage:
    python scripts/run_mock.py [count] [interval_seconds]

Examples:
    python scripts/run_mock.py         # prints 5 events with default interval
    python scripts/run_mock.py 10 0.2  # prints 10 events with 0.2s interval
"""
import asyncio
import sys
from py_captions_for_channels.mock_source import MockSource


async def main(count: int = 5, interval: float | None = None):
    src = MockSource(interval_seconds=0.5 if interval is None else interval)
    seen = 0
    async for ev in src.events():
        print(
            (
                f"[{ev.timestamp.isoformat()}] {ev.title} "
                f"(start={ev.start_time.isoformat()}, source={ev.source})"
            )
        )
        seen += 1
        if seen >= count:
            break


if __name__ == "__main__":
    count = 5
    interval = None
    if len(sys.argv) >= 2:
        try:
            count = int(sys.argv[1])
        except Exception:
            pass
    if len(sys.argv) >= 3:
        try:
            interval = float(sys.argv[2])
        except Exception:
            interval = None

    asyncio.run(main(count, interval))
