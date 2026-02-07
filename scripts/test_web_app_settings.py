#!/usr/bin/env python3
"""Test web_app settings integration with database."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from py_captions_for_channels.database import init_db, get_db  # noqa: E402
from py_captions_for_channels.web_app import (  # noqa: E402
    load_settings,
    save_settings,
)


def test_web_app_settings():
    """Test web_app load_settings and save_settings functions."""
    print("=" * 60)
    print("Testing Web App Settings Integration")
    print("=" * 60)

    # Initialize database
    print("\n1. Initializing database...")
    init_db()
    print("✓ Database initialized")

    # Test load_settings (should migrate from JSON/env on first run)
    print("\n2. Testing load_settings()...")
    db = next(get_db())
    try:
        settings = load_settings(db)
        print(f"   Loaded {len(settings)} settings:")
        for key, value in settings.items():
            if key == "whitelist":
                print(f"     {key}: <{len(value)} chars>")
            else:
                print(f"     {key}: {value} ({type(value).__name__})")
        print("✓ load_settings() working")

        # Test save_settings
        print("\n3. Testing save_settings()...")
        settings["dry_run"] = True
        settings["whisper_model"] = "large"
        save_settings(settings, db)
        print("✓ save_settings() working")

        # Verify changes persisted
        print("\n4. Verifying persistence...")
        reloaded = load_settings(db)
        assert reloaded["dry_run"] is True, "dry_run should be True"
        assert reloaded["whisper_model"] == "large", "whisper_model should be 'large'"
        print(f"   dry_run: {reloaded['dry_run']}")
        print(f"   whisper_model: {reloaded['whisper_model']}")
        print("✓ Changes persisted correctly")

        print("\n" + "=" * 60)
        print("Web app integration tests passed! ✓")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    test_web_app_settings()
