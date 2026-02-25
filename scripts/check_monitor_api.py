#!/usr/bin/env python3
"""Test the system monitor API endpoints."""

import requests
import time

BASE_URL = "http://localhost:8000"


def test_monitor_latest():
    """Test /api/monitor/latest endpoint."""
    print("Testing /api/monitor/latest...")
    response = requests.get(f"{BASE_URL}/api/monitor/latest")

    if response.status_code == 200:
        data = response.json()
        print(f"✓ Status: {response.status_code}")
        print(f"  GPU Provider: {data['gpu_provider']['name']}")

        if data["metrics"]:
            m = data["metrics"]
            print(f"  CPU: {m['cpu_percent']:.1f}%")
            print(
                f"  Disk R/W: {m['disk_read_mbps']:.2f} / {m['disk_write_mbps']:.2f} MB/s"
            )
            print(
                f"  Net RX/TX: {m['net_recv_mbps']:.2f} / {m['net_sent_mbps']:.2f} Mbps"
            )

        print(f"  Pipeline Active: {data['pipeline']['active']}")
        return True
    else:
        print(f"✗ Failed with status {response.status_code}")
        return False


def test_monitor_window():
    """Test /api/monitor/window endpoint."""
    print("\nTesting /api/monitor/window?seconds=30...")
    response = requests.get(f"{BASE_URL}/api/monitor/window?seconds=30")

    if response.status_code == 200:
        data = response.json()
        print(f"✓ Status: {response.status_code}")
        print(f"  Samples collected: {len(data['metrics'])}")
        print(f"  GPU Provider: {data['gpu_provider']['name']}")
        return True
    else:
        print(f"✗ Failed with status {response.status_code}")
        return False


if __name__ == "__main__":
    print("System Monitor API Test")
    print("=" * 50)
    print("\nMake sure the web server is running:")
    print("  uvicorn py_captions_for_channels.web_app:app --reload --port 8000")
    print("\nWaiting 3 seconds for you to start it...")
    time.sleep(3)

    try:
        success = True
        success = test_monitor_latest() and success
        success = test_monitor_window() and success

        if success:
            print("\n" + "=" * 50)
            print("✓ All API tests passed!")
        else:
            print("\n" + "=" * 50)
            print("✗ Some tests failed")
    except requests.exceptions.ConnectionError:
        print("\n✗ Could not connect to server. Is it running?")
    except Exception as e:
        print(f"\n✗ Error: {e}")
