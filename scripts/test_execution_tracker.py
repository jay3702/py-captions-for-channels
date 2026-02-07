#!/usr/bin/env python3
"""Test script for execution tracker database migration."""

import os
import sys
import tempfile
from pathlib import Path

# Set up temp database for testing BEFORE importing database module
temp_dir = tempfile.mkdtemp()
os.environ["DB_PATH"] = str(Path(temp_dir) / "test.db")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from py_captions_for_channels.database import init_db  # noqa: E402
from py_captions_for_channels.execution_tracker import (  # noqa: E402
    ExecutionTracker,
    build_manual_process_job_id,
)


def test_execution_tracker():
    """Test execution tracker with database backend."""
    print("=" * 60)
    print("Testing Execution Tracker Database Migration")
    print("=" * 60)

    # Initialize database
    print("\n1. Initializing database...")
    init_db()
    print("✓ Database initialized")

    # Create tracker instance
    print("\n2. Creating execution tracker...")
    tracker = ExecutionTracker()
    print("✓ Execution tracker created")

    # Test start_execution
    print("\n3. Testing start_execution...")
    job_id1 = "test_job_001"
    exec_id1 = tracker.start_execution(
        job_id=job_id1,
        title="Test Recording 1",
        path="/recordings/test1.mpg",
        status="running",
        kind="normal",
    )
    print(f"   Created execution: {exec_id1}")

    job_id2 = build_manual_process_job_id("/recordings/test2.mpg")
    exec_id2 = tracker.start_execution(
        job_id=job_id2,
        title="Test Recording 2",
        path="/recordings/test2.mpg",
        status="pending",
        kind="manual_process",
    )
    print(f"   Created manual execution: {exec_id2}")
    print("✓ start_execution working")

    # Test get_execution
    print("\n4. Testing get_execution...")
    exec_data = tracker.get_execution(exec_id1)
    assert exec_data is not None, "Execution should exist"
    assert exec_data["title"] == "Test Recording 1"
    assert exec_data["status"] == "running"
    print(f"   Retrieved: {exec_data['title']} (status: {exec_data['status']})")
    print("✓ get_execution working")

    # Test update_status
    print("\n5. Testing update_status...")
    tracker.update_status(exec_id1, "completed")
    updated = tracker.get_execution(exec_id1)
    assert updated["status"] == "completed"
    print(f"   Status updated: running -> {updated['status']}")
    print("✓ update_status working")

    # Test complete_execution
    print("\n6. Testing complete_execution...")
    tracker.complete_execution(
        exec_id1, success=True, elapsed_seconds=120.5, error=None
    )
    completed = tracker.get_execution(exec_id1)
    assert completed["success"] is True
    assert completed["elapsed_seconds"] == 120.5
    print(
        f"   Completed: success={completed['success']}, "
        f"elapsed={completed['elapsed_seconds']}s"
    )
    print("✓ complete_execution working")

    # Test get_executions
    print("\n7. Testing get_executions...")
    all_execs = tracker.get_executions(limit=10)
    print(f"   Found {len(all_execs)} execution(s)")
    for i, exec in enumerate(all_execs[:3], 1):
        print(f"     {i}. {exec['title']} - {exec['status']}")
    assert len(all_execs) >= 2, "Should have at least 2 executions"
    print("✓ get_executions working")

    # Test request_cancel
    print("\n8. Testing request_cancel...")
    ok = tracker.request_cancel(exec_id2)
    assert ok is True, "Cancel should succeed for existing execution"
    canceled = tracker.get_execution(exec_id2)
    assert canceled["cancel_requested"] is True
    print(f"   Cancel requested: {canceled['cancel_requested']}")
    print("✓ request_cancel working")

    # Test is_cancel_requested
    print("\n9. Testing is_cancel_requested...")
    is_canceled = tracker.is_cancel_requested(exec_id2)
    assert is_canceled is True
    print(f"   Cancel check: {is_canceled}")
    print("✓ is_cancel_requested working")

    # Test remove_execution
    print("\n10. Testing remove_execution...")
    ok = tracker.remove_execution(exec_id2)
    assert ok is True, "Remove should succeed"
    removed = tracker.get_execution(exec_id2)
    assert removed is None, "Execution should be removed"
    print("   Execution removed successfully")
    print("✓ remove_execution working")

    # Test reprocessing (duplicate job_id)
    print("\n11. Testing reprocessing (duplicate job_id)...")
    # Create another execution with same job_id
    exec_id3 = tracker.start_execution(
        job_id=job_id1,  # Same as exec_id1
        title="Test Recording 1 Retry",
        path="/recordings/test1.mpg",
        status="running",
        kind="normal",
    )
    assert exec_id3 != exec_id1, "Should create new ID for reprocessing"
    assert "::" in exec_id3, "New ID should have timestamp suffix"
    print(f"   Original: {exec_id1}")
    print(f"   Retry: {exec_id3}")
    print("✓ Reprocessing creates unique ID")

    print("\n" + "=" * 60)
    print("All execution tracker tests passed! ✓")
    print("=" * 60)


if __name__ == "__main__":
    test_execution_tracker()
