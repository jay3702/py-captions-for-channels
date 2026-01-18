#!/usr/bin/env python3
"""
Demonstrate the three event source modes.

This shows how to switch between:
- Mock source (for fast testing)
- Webhook source (production - HTTP POST from ChannelWatch)
- WebSocket source (not currently compatible with ChannelWatch)

Usage:
    python scripts/demo_sources.py mock
    python scripts/demo_sources.py webhook
    python scripts/demo_sources.py websocket
"""

import asyncio
import sys
from pathlib import Path


def setup_path():
    """Add project root to sys.path."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def main():
    """Demonstrate different event sources."""
    setup_path()

    if len(sys.argv) < 2:
        print("Usage: python scripts/demo_sources.py [mock|webhook|websocket]")
        sys.exit(1)

    mode = sys.argv[1].lower()

    async def run_source():
        if mode == "mock":
            from py_captions_for_channels.mock_source import MockSource

            print("Running MOCK source - generates test events every 5 seconds")
            print("Press Ctrl+C to stop\n")
            source = MockSource(interval_seconds=5)

        elif mode == "webhook":
            from py_captions_for_channels.channelwatch_webhook_source import (
                ChannelWatchWebhookSource,
            )

            print("Running WEBHOOK source - listening on http://0.0.0.0:9000")
            print("Configure ChannelWatch: json://192.168.5.113:9000")
            print("Press Ctrl+C to stop\n")
            source = ChannelWatchWebhookSource(host="0.0.0.0", port=9000)

        elif mode == "websocket":
            from py_captions_for_channels.channelwatch_source import ChannelWatchSource

            print("Running WEBSOCKET source (NOT compatible with ChannelWatch)")
            print("This will attempt to connect to ws://192.168.3.150:8501/events")
            print("Press Ctrl+C to stop\n")
            source = ChannelWatchSource("ws://192.168.3.150:8501/events")

        else:
            print(f"Unknown mode: {mode}")
            sys.exit(1)

        # Print events as they arrive
        async for event in source.events():
            print(f"?? Event: {event.title}")
            print(f"   Time: {event.timestamp}")
            print()

    try:
        asyncio.run(run_source())
    except KeyboardInterrupt:
        print("\n\nStopped.")


if __name__ == "__main__":
    main()
