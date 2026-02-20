#!/usr/bin/env python3
"""
Sync .env file with .env.example template.

This script:
1. Reads your current .env values
2. Uses .env.example as the template
3. Creates a new .env with correct structure
4. Backs up your old .env to .env.backup
"""

import os
import re
from pathlib import Path
from datetime import datetime


def parse_env_file(filepath):
    """Parse env file into dict of key -> value."""
    values = {}
    if not filepath.exists():
        return values

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip comments, empty lines, and section headers
            if not line or line.startswith("#") or "=" not in line:
                continue

            # Handle both commented and uncommented settings
            setting_line = line.lstrip("#").strip()
            if "=" in setting_line:
                key, value = setting_line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # Only store if key looks like a setting (uppercase with underscores)
                if key and key.replace("_", "").isupper():
                    values[key] = value

    return values


def main():
    repo_root = Path(__file__).parent.parent
    env_path = repo_root / ".env"
    env_example_path = repo_root / ".env.example"

    if not env_example_path.exists():
        print(f"Error: .env.example not found at {env_example_path}")
        return 1

    # Read current .env values
    print("Reading current .env values...")
    current_values = parse_env_file(env_path) if env_path.exists() else {}
    print(f"Found {len(current_values)} settings in current .env")

    # Backup current .env if it exists
    if env_path.exists():
        backup_path = (
            repo_root / f'.env.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        )
        env_path.rename(backup_path)
        print(f"Backed up current .env to {backup_path.name}")

    # Read .env.example and create new .env
    print(f"Creating new .env from {env_example_path.name}...")
    with open(env_example_path, "r", encoding="utf-8") as f_in:
        with open(env_path, "w", encoding="utf-8") as f_out:
            for line in f_in:
                line_stripped = line.strip()

                # Copy comments and empty lines as-is
                if (
                    not line_stripped
                    or line_stripped.startswith("#")
                    or "=" not in line_stripped
                ):
                    f_out.write(line)
                    continue

                # Parse setting line
                is_commented = line_stripped.startswith("#")
                setting_line = line_stripped.lstrip("#").strip()

                if "=" in setting_line:
                    key, template_value = setting_line.split("=", 1)
                    key = key.strip()

                    # Skip non-setting lines (like description lines with =)
                    if not key or not key.replace("_", "").isupper():
                        f_out.write(line)
                        continue

                    # Use current value if it exists, otherwise use template value
                    if key in current_values:
                        value = current_values[key]
                        # Write uncommented with actual value
                        f_out.write(f"{key}={value}\n")
                        print(f"  ✓ {key}={value}")
                    else:
                        # New setting - use template value (keep commented if it was)
                        if is_commented:
                            f_out.write(f"# {key}={template_value.strip()}\n")
                            print(
                                f"  + {key}={template_value.strip()} (new, commented)"
                            )
                        else:
                            f_out.write(f"{key}={template_value.strip()}\n")
                            print(f"  + {key}={template_value.strip()} (new)")
                else:
                    f_out.write(line)

    print(f"\n✅ New .env file created at {env_path}")
    print("\nNew settings added:")
    print("  - WHISPER_DEVICE=auto (GPU/CPU selection)")
    print("  - ORPHAN_CLEANUP_ENABLED=false")
    print("  - ORPHAN_CLEANUP_INTERVAL_HOURS=24")
    print("  - ORPHAN_CLEANUP_IDLE_THRESHOLD_MINUTES=15")

    # Check for removed duplicate settings
    removed = []
    for key in current_values:
        # Check if this key appears in .env.example
        with open(env_example_path, "r") as f:
            example_content = f.read()
            if (
                f"\n{key}=" not in example_content
                and f"\n# {key}=" not in example_content
            ):
                removed.append(key)

    if removed:
        print("\nRemoved obsolete settings:")
        for key in removed:
            print(f"  - {key} (not in template)")

    print("\n⚠️  Please restart the application for changes to take effect.")
    return 0


if __name__ == "__main__":
    exit(main())
