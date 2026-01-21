#!/usr/bin/env python3
"""
Test ChannelWatch webhook receiver.

This starts an HTTP server on port 9000 and waits for webhook notifications
from ChannelWatch.

Usage:
    python scripts/test_webhook.py

Configure in ChannelWatch:
    webhook://<SERVER_IP>:9000

Press Ctrl+C to stop.
"""

import asyncio
import logging
import sys
from pathlib import Path


def setup_path():
    """Add project root to sys.path."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def main():
    """Start webhook receiver and print events."""
    setup_path()

    from py_captions_for_channels.channelwatch_webhook_source import (
        ChannelWatchWebhookSource,
    )

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    async def test_webhook():
        """Start webhook server and print events."""
        print("Starting webhook server on http://0.0.0.0:9000")
        print("Configure in ChannelWatch: webhook://192.168.3.150:9000")
        print("Waiting for events... (Ctrl+C to stop)\n")

        source = ChannelWatchWebhookSource(host="0.0.0.0", port=9000)

        try:
            async for event in source.events():
                print("?? EVENT RECEIVED:")
                print("   Title: {}".format(event.title))
                print("   Timestamp: {}".format(event.timestamp))
                print("   Start Time: {}".format(event.start_time))
                print("   Source: {}".format(event.source))
                print()
        except KeyboardInterrupt:
            print("\n\nStopped by user.")

    try:
        asyncio.run(test_webhook())
    except KeyboardInterrupt:
        print("\n\nExiting...")


if __name__ == "__main__":
    main()
