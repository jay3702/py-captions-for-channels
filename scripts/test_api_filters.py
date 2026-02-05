#!/usr/bin/env python3
"""Test Channels DVR API filtering capabilities.

Experiment with various query parameters to see what's supported.
"""

import os
import sys
import requests
from datetime import datetime, timedelta

# Add parent directory to path to import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from py_captions_for_channels.config import CHANNELS_API_URL  # noqa: E402


def test_params(params, description):
    """Test API call with specific parameters."""
    print(f"\n{'='*60}")
    print(f"Test: {description}")
    print(f"Params: {params}")
    print(f"{'='*60}")

    try:
        resp = requests.get(
            f"{CHANNELS_API_URL}/api/v1/all",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()

        data = resp.json()
        print(f"[OK] Success! Returned {len(data)} recordings")

        if data:
            # Show first recording details
            first = data[0]
            print("\nFirst recording:")
            print(f"  Title: {first.get('title')}")
            created_ts = first.get("created_at", 0) / 1000
            print(f"  Created: {datetime.fromtimestamp(created_ts)}")
            print(f"  Completed: {first.get('completed')}")
            print(f"  Processed: {first.get('processed')}")

            # If we got fewer results than baseline, show what we filtered out
            return len(data)

        return 0

    except Exception as e:
        print(f"[FAIL] Failed: {e}")
        return None


def main():
    """Run API filter experiments."""
    print("Channels DVR API Filter Experiments")
    print(f"Testing against: {CHANNELS_API_URL}")

    # Baseline - no filters
    baseline = test_params({}, "Baseline (no filters)")

    # Known working parameters
    test_params(
        {"sort": "date_added", "order": "desc", "source": "recordings"},
        "Sort by date_added descending (known working)",
    )

    # Try time-based filters
    one_hour_ago = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
    test_params({"since": one_hour_ago}, "Filter by 'since' timestamp (last hour)")

    test_params({"after": one_hour_ago}, "Filter by 'after' timestamp (last hour)")

    test_params(
        {"created_after": one_hour_ago},
        "Filter by 'created_after' timestamp (last hour)",
    )

    test_params(
        {"min_time": one_hour_ago}, "Filter by 'min_time' timestamp (last hour)"
    )

    # Try limit/count parameters
    test_params({"limit": 5}, "Limit results to 5 recordings")

    test_params({"count": 5}, "Count parameter = 5")

    test_params({"max": 5}, "Max parameter = 5")

    # Try status filters
    test_params({"completed": "true"}, "Filter by completed=true")

    test_params({"processed": "false"}, "Filter by processed=false")

    test_params(
        {"completed": "true", "processed": "false"},
        "Filter by completed=true AND processed=false",
    )

    # Try combining filters
    test_params(
        {"sort": "created_at", "order": "desc", "completed": "true", "limit": 10},
        "Combination: recent, completed, limit 10",
    )

    print(f"\n{'='*60}")
    print("Experiment Complete!")
    print(f"Baseline returned {baseline} total recordings")
    print("Check which parameters actually filtered the results above.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
