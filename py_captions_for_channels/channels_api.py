from datetime import datetime
from .config import USE_MOCK
import requests


class ChannelsAPI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def lookup_recording_path(self, title: str, start_time: datetime) -> str:
        if USE_MOCK:
            # Return a synthetic path for testing
            safe_title = title.replace(" ", "_")
            return f"/tmp/{safe_title}.mpg"

        # Real API call
        resp = requests.get(f"{self.base_url}/dvr/jobs")
        resp.raise_for_status()

        jobs = resp.json()

        for job in jobs:
            if job.get("Title") == title:
                return job.get("Path")

        raise RuntimeError(f"No matching recording found for {title}")
