#!/usr/bin/env python3
"""Test script for database setup and settings migration."""

import os
import sys
import tempfile
from pathlib import Path

# Set up temp database for testing BEFORE importing database module
temp_dir = tempfile.mkdtemp()
os.environ["DB_PATH"] = str(Path(temp_dir) / "test.db")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from py_captions_for_channels.database import init_db, get_db  # noqa: E402
from py_captions_for_channels.services.settings_service import (  # noqa: E402
    SettingsService,
)


def test_database_setup():
    """Test database initialization and basic operations."""
    print("=" * 60)
    print("Testing Database Setup")
    print("=" * 60)

    # Initialize database
    print("\n1. Initializing database...")
    init_db()
    print("✓ Database initialized")

    # Test settings service
    print("\n2. Testing settings service...")
    db = next(get_db())
    try:
        settings_service = SettingsService(db)

        # Set some test values
        print("   Setting test values...")
        settings_service.set("dry_run", False)
        settings_service.set("keep_original", True)
        settings_service.set("whisper_model", "medium")
        settings_service.set("log_verbosity", "NORMAL")
        print("✓ Test values set")

        # Read them back
        print("\n3. Reading values back...")
        dry_run = settings_service.get("dry_run")
        keep_original = settings_service.get("keep_original")
        whisper_model = settings_service.get("whisper_model")
        log_verbosity = settings_service.get("log_verbosity")

        print(f"   dry_run: {dry_run} (type: {type(dry_run).__name__})")
        print(
            f"   keep_original: {keep_original} (type: {type(keep_original).__name__})"
        )
        print(
            f"   whisper_model: {whisper_model} (type: {type(whisper_model).__name__})"
        )
        print(
            f"   log_verbosity: {log_verbosity} (type: {type(log_verbosity).__name__})"
        )

        # Verify types
        assert isinstance(dry_run, bool), "dry_run should be bool"
        assert isinstance(keep_original, bool), "keep_original should be bool"
        assert isinstance(whisper_model, str), "whisper_model should be str"
        assert isinstance(log_verbosity, str), "log_verbosity should be str"
        print("✓ Type conversion working correctly")

        # Test get_all
        print("\n4. Testing get_all()...")
        all_settings = settings_service.get_all()
        print(f"   Found {len(all_settings)} settings:")
        for key, value in all_settings.items():
            print(f"     {key}: {value} ({type(value).__name__})")
        print("✓ get_all() working")

        # Test update
        print("\n5. Testing update...")
        settings_service.set("dry_run", True)
        updated = settings_service.get("dry_run")
        assert updated is True, "dry_run should be True after update"
        print(f"   Updated dry_run: {updated}")
        print("✓ Update working")

        # Test delete
        print("\n6. Testing delete...")
        settings_service.set("test_key", "test_value")
        assert settings_service.get("test_key") == "test_value"
        settings_service.delete("test_key")
        assert settings_service.get("test_key") is None
        print("✓ Delete working")

        print("\n" + "=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    test_database_setup()
