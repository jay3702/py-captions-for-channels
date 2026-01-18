#!/usr/bin/env python3
"""
Utility to reprocess recordings or mark them for reprocessing.

Usage:
    python reprocess_recordings.py --list
    python reprocess_recordings.py --reprocess /path/to/recording.mpg
    python reprocess_recordings.py --reprocess-all
    python reprocess_recordings.py --clear-all
"""

import sys
import argparse
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from py_captions_for_channels.state import StateBackend  # noqa: E402
from py_captions_for_channels.config import (  # noqa: E402
    STATE_FILE,
    CAPTION_COMMAND,
    DRY_RUN,
)
from py_captions_for_channels.pipeline import Pipeline  # noqa: E402
from py_captions_for_channels.parser import ProcessingEvent  # noqa: E402


def list_reprocess_queue():
    """Display list of recordings pending reprocessing."""
    state = StateBackend(STATE_FILE)
    queue = state.get_reprocess_queue()

    if not queue:
        print("✓ Reprocess queue is empty")
        return 0

    print(f"Reprocess queue ({len(queue)} items):")
    for i, path in enumerate(queue, 1):
        print(f"  {i}. {path}")

    return 0


def reprocess_file(file_path):
    """Mark a single file for reprocessing."""
    # Verify file exists
    if not os.path.exists(file_path):
        print(f"✗ File not found: {file_path}")
        return 1

    state = StateBackend(STATE_FILE)
    state.mark_for_reprocess(file_path)
    print(f"✓ Marked for reprocessing: {file_path}")

    # Optionally execute immediately
    response = input("Execute reprocessing now? (y/n): ").strip().lower()
    if response == "y":
        return execute_reprocess_queue()
    return 0


def reprocess_all_by_glob(pattern):
    """Mark all files matching a glob pattern for reprocessing."""
    from glob import glob

    files = glob(pattern, recursive=True)
    if not files:
        print(f"✗ No files found matching: {pattern}")
        return 1

    state = StateBackend(STATE_FILE)
    for file_path in files:
        state.mark_for_reprocess(file_path)
        print(f"✓ Marked for reprocessing: {file_path}")

    print(f"\n✓ Marked {len(files)} files for reprocessing")

    response = input("Execute reprocessing now? (y/n): ").strip().lower()
    if response == "y":
        return execute_reprocess_queue()
    return 0


def execute_reprocess_queue():
    """Execute all items in the reprocess queue."""
    state = StateBackend(STATE_FILE)
    queue = state.get_reprocess_queue()

    if not queue:
        print("✓ Reprocess queue is empty")
        return 0

    pipeline = Pipeline(CAPTION_COMMAND, dry_run=DRY_RUN)
    print(f"\nProcessing {len(queue)} items...")

    succeeded = 0
    failed = 0

    for path in queue:
        print(f"\n  Processing: {path}")
        try:
            # Create a minimal event
            event = ProcessingEvent(
                timestamp=datetime.now(),
                path=path,
                title=os.path.basename(path),
                source="reprocess-cli",
            )

            result = pipeline.run(event)
            if result.success:
                print("    ✓ Success")
                state.clear_reprocess_request(path)
                succeeded += 1
            else:
                print(f"    ✗ Failed (exit code {result.returncode})")
                if result.stderr:
                    print(f"    Error: {result.stderr[:200]}")
                failed += 1
        except Exception as e:
            print(f"    ✗ Exception: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {succeeded} succeeded, {failed} failed")
    print(f"{'='*60}")

    return 0 if failed == 0 else 1


def clear_reprocess_queue():
    """Clear all items from the reprocess queue."""
    state = StateBackend(STATE_FILE)
    queue = state.get_reprocess_queue()

    if not queue:
        print("✓ Reprocess queue is already empty")
        return 0

    response = (
        input(f"Clear {len(queue)} items from reprocess queue? (y/n): ").strip().lower()
    )
    if response != "y":
        print("Cancelled")
        return 0

    # Clear by recreating state with empty queue
    state.reprocess_paths.clear()
    state._persist_state(state.last_ts, state.reprocess_paths)
    print(f"✓ Cleared {len(queue)} items from reprocess queue")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Reprocess recordings with updated caption pipeline"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List recordings pending reprocessing",
    )
    parser.add_argument(
        "--reprocess",
        metavar="PATH",
        help="Mark a single recording for reprocessing",
    )
    parser.add_argument(
        "--reprocess-glob",
        metavar="PATTERN",
        help="Mark all recordings matching glob pattern for reprocessing",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute reprocess queue now",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear all items from reprocess queue",
    )

    args = parser.parse_args()

    if args.list:
        return list_reprocess_queue()
    elif args.reprocess:
        return reprocess_file(args.reprocess)
    elif args.reprocess_glob:
        return reprocess_all_by_glob(args.reprocess_glob)
    elif args.execute:
        return execute_reprocess_queue()
    elif args.clear:
        return clear_reprocess_queue()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
