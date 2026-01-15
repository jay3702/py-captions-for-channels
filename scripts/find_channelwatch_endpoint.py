#!/usr/bin/env python3
"""
Test different ChannelWatch WebSocket endpoint paths.

This helps identify the correct WebSocket URL.
"""
import asyncio
import sys
from pathlib import Path

import websockets


def setup_path():
    """Add project root to sys.path."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


async def test_endpoint(url):
    """Test a WebSocket endpoint."""
    try:
        print(f"Testing: {url} ... ", end="", flush=True)
        async with asyncio.timeout(3):
            async with websockets.connect(url) as ws:
                print("? CONNECTED!")
                # Try to receive one message
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    print(f"   Received: {msg[:100]}...")
                except asyncio.TimeoutError:
                    print("   (Connected but no immediate messages)")
                return True
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"? HTTP {e.status_code}")
    except asyncio.TimeoutError:
        print("? Timeout")
    except Exception as e:
        print(f"? {type(e).__name__}: {e}")
    return False


async def main():
    """Test common WebSocket endpoint paths."""
    setup_path()

    base = "192.168.3.150:8501"

    # Common WebSocket paths
    paths = [
        "/events",
        "/ws",
        "/websocket",
        "/api/events",
        "/api/ws",
        "/stream",
        "",  # root path
    ]

    print(f"Testing ChannelWatch WebSocket endpoints at {base}\n")

    for path in paths:
        url = f"ws://{base}{path}"
        if await test_endpoint(url):
            print(f"\n? SUCCESS! Use this URL: {url}\n")
            return

    print("\n? None of the common paths worked.")
    print("\nNext steps:")
    print("1. Check http://192.168.3.150:8501 in browser for API documentation")
    print("2. Check ChannelWatch settings for WebSocket configuration")
    print("3. Verify ChannelWatch is configured to send WebSocket events")


if __name__ == "__main__":
    asyncio.run(main())
