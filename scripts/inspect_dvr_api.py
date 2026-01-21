#!/usr/bin/env python3
"""
Inspect Channels DVR API responses to verify field names and data structure.

This helps us understand what the API returns and fix the lookup logic.
"""

import requests
import json

DVR_URL = "http://<CHANNELS_DVR_SERVER>:8089"


def inspect_api():
    """Fetch and display DVR API data."""
    print("=" * 70)
    print("CHANNELS DVR API INSPECTOR")
    print("=" * 70)

    print("\n[1] Fetching recording jobs from: {}/dvr/jobs".format(DVR_URL))

    try:
        resp = requests.get("{}/dvr/jobs".format(DVR_URL), timeout=10)
        resp.raise_for_status()
        jobs = resp.json()

        print("? Success! Found {} recording jobs\n".format(len(jobs)))

        if len(jobs) == 0:
            print("??  No recordings found. Try recording something first.")
            return

        # Show first few jobs
        print("=" * 70)
        print("SAMPLE RECORDINGS FROM /dvr/jobs (showing first 3):")
        print("=" * 70)

        for i, job in enumerate(jobs[:3]):
            print("\n[Recording #{}]".format(i + 1))
            print(json.dumps(job, indent=2))
            print("-" * 70)

        # Test the two-step lookup
        if jobs:
            first_job = jobs[0]
            file_id = first_job.get("FileID")
            job_name = first_job.get("Name", "Unknown")

            if file_id:
                print("\n" + "=" * 70)
                print("[2] Testing file details for: {}".format(job_name))
                print("    GET /dvr/files/{}".format(file_id))
                print("=" * 70)

                try:
                    resp = requests.get(
                        "{}/dvr/files/{}".format(DVR_URL, file_id), timeout=10
                    )
                    resp.raise_for_status()
                    file_data = resp.json()

                    print("\n? File details retrieved!")
                    print(json.dumps(file_data, indent=2))

                    # Highlight the path
                    path = file_data.get("Path")
                    print("\n" + "=" * 70)
                    print("FILE PATH FOUND:")
                    print("=" * 70)
                    print("Path: {}".format(path))

                except Exception as e:
                    print("? Failed to get file details: {}".format(e))

    except Exception as e:
        print("? Error: {}".format(e))


if __name__ == "__main__":
    inspect_api()
