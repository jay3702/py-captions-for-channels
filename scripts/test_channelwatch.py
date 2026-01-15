#!/usr/bin/env python3
"""
Diagnostic script to test ChannelWatch WebSocket connection.

This script connects to ChannelWatch and prints all events it receives.
Use this to verify your ChannelWatch setup is working before running the full pipeline.

Usage:
    python scripts/test_channelwatch.py

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
    """Connect to ChannelWatch and print events."""
    setup_path()

    from py_captions_for_channels.channelwatch_source import ChannelWatchSource
    from py_captions_for_channels.config import CHANNELWATCH_URL

    # Configure logging to see connection status
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    async def test_connection():
        """Connect to ChannelWatch and print events."""
        print("Connecting to ChannelWatch at: {}".format(CHANNELWATCH_URL))
        print("Waiting for events... (Ctrl+C to stop)\n")

        source = ChannelWatchSource(CHANNELWATCH_URL)

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
        asyncio.run(test_connection())
    except KeyboardInterrupt:
        print("\n\nExiting...")


if __name__ == "__main__":
    main()
