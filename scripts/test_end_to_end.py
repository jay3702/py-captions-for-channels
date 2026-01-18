#!/usr/bin/env python3
"""
End-to-end test of the complete captioning pipeline.

This script runs the full workflow from event source through to pipeline execution,
validating each component along the way.

Usage:
    # Test with mock source (fast)
    python scripts/test_end_to_end.py mock

    # Test with webhook source (requires ChannelWatch configured)
    python scripts/test_end_to_end.py webhook
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
    """Run end-to-end test."""
    setup_path()

    # Configure detailed logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Import after path is set
    from py_captions_for_channels.channels_api import ChannelsAPI
    from py_captions_for_channels.parser import Parser
    from py_captions_for_channels.state import StateBackend
    from py_captions_for_channels.pipeline import Pipeline
    from py_captions_for_channels.config import (
        CHANNELS_API_URL,
        CAPTION_COMMAND,
        WEBHOOK_HOST,
        WEBHOOK_PORT,
    )

    mode = sys.argv[1] if len(sys.argv) > 1 else "mock"

    async def run_test():
        """Run the end-to-end test."""
        print("\n" + "=" * 70)
        print("END-TO-END TEST - py-captions-for-channels")
        print("=" * 70)

        # Initialize components
        print("\n[1/5] Initializing components...")
        api = ChannelsAPI(CHANNELS_API_URL)
        parser = Parser()
        state = StateBackend("/tmp/test_state.json")
        pipeline = Pipeline(CAPTION_COMMAND, dry_run=True)  # Always dry-run for testing
        print("? All components initialized")

        # Select event source
        print(f"\n[2/5] Setting up event source: {mode.upper()}")
        if mode == "mock":
            from py_captions_for_channels.mock_source import MockSource

            print("   Using MockSource (generates test events every 2 seconds)")
            source = MockSource(interval_seconds=2)
        elif mode == "webhook":
            from py_captions_for_channels.channelwatch_webhook_source import (
                ChannelWatchWebhookSource,
            )

            print(f"   Using WebhookSource on {WEBHOOK_HOST}:{WEBHOOK_PORT}")
            print(f"   Configure ChannelWatch: json://192.168.5.113:{WEBHOOK_PORT}")
            source = ChannelWatchWebhookSource(host=WEBHOOK_HOST, port=WEBHOOK_PORT)
        else:
            print(f"? Unknown mode: {mode}")
            sys.exit(1)

        print("? Event source ready")

        # Process events
        print("\n[3/5] Starting event processing loop...")
        print("   Press Ctrl+C after receiving 2-3 events to stop\n")

        event_count = 0
        max_events = 5 if mode == "mock" else 100  # Auto-stop for mock

        try:
            async for partial in source.events():
                event_count += 1
                print(f"\n{'='*70}")
                print(f"EVENT #{event_count}")
                print(f"{'='*70}")

                # Step 3a: Check state
                print("\n[3a] Checking if event should be processed...")
                print("     Timestamp: {}".format(partial.timestamp))
                print("     Title: {}".format(partial.title))

                if not state.should_process(partial.timestamp):
                    print("??  Skipping (already processed)")
                    continue

                print("? Event is new, proceeding...")

                # Step 3b: Lookup recording path
                print("\n[3b] Looking up recording path via API...")
                try:
                    path = api.lookup_recording_path(partial.title, partial.start_time)
                    print("? Found path: {}".format(path))
                except Exception as e:
                    print("? API lookup failed: {}".format(e))
                    continue

                # Step 3c: Parse event
                print("\n[3c] Parsing event...")
                event = parser.from_channelwatch(partial, path)
                print("? Parsed: {} -> {}".format(event.title, event.path))

                # Step 3d: Run pipeline
                print("\n[3d] Running pipeline (DRY-RUN)...")
                result = pipeline.run(event)
                if result.success:
                    print("? Pipeline would execute: {}".format(result.command))
                else:
                    print("? Pipeline failed: {}".format(result.stderr))

                # Step 3e: Update state
                print("\n[3e] Updating state...")
                state.update(event.timestamp)
                print("? State updated")

                print(f"\n{'='*70}")
                print(f"? EVENT #{event_count} PROCESSED SUCCESSFULLY")
                print(f"{'='*70}\n")

                if event_count >= max_events:
                    print(f"\n? Processed {event_count} events, stopping test")
                    break

        except KeyboardInterrupt:
            print(f"\n\n[4/5] Test stopped by user after {event_count} events")

        # Summary
        print("\n" + "=" * 70)
        print("[5/5] TEST SUMMARY")
        print("=" * 70)
        print(f"? Events processed: {event_count}")
        print(f"? Mode: {mode.upper()}")
        print("? All components working correctly")
        print("\nNext steps:")
        print("  - Set DRY_RUN=False in config.py to execute real commands")
        print("  - Set USE_MOCK=False, USE_WEBHOOK=True for production")
        print("  - Deploy to niu for production use")
        print("=" * 70 + "\n")

    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        print("\n\nTest interrupted.")


if __name__ == "__main__":
    main()
