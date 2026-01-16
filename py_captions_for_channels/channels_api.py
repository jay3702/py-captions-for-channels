import logging
from datetime import datetime
from typing import Optional
import requests

from .config import USE_MOCK

LOG = logging.getLogger(__name__)


class ChannelsAPI:
    """Client for Channels DVR HTTP API.

    Provides methods to query recording information and file paths.
    """

    def __init__(self, base_url: str, timeout: int = 10):
        """Initialize API client.

        Args:
            base_url: Base URL of Channels DVR (e.g., http://192.168.3.150:8089)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def lookup_recording_path(self, title: str, start_time: datetime) -> str:
        """Look up the file path for a recording.

        Args:
            title: Program title
            start_time: Recording start time

        Returns:
            Full file path to the recording

        Raises:
            RuntimeError: If recording not found or API error
        """
        if USE_MOCK:
            # Return a synthetic path for testing
            safe_title = title.replace(" ", "_")
            mock_path = f"/tmp/{safe_title}.mpg"
            LOG.info("[MOCK] Returning mock path: %s", mock_path)
            return mock_path

        LOG.info("Looking up recording: %s (start: %s)", title, start_time)

        try:
            # Query DVR API for recordings
            resp = requests.get(
                f"{self.base_url}/dvr/jobs",
                timeout=self.timeout,
            )
            resp.raise_for_status()

            jobs = resp.json()
            LOG.debug("Retrieved %d recording jobs from API", len(jobs))

            # Find matching recording by title
            # Note: We could also match by start_time for more accuracy
            for job in jobs:
                job_title = job.get("Name") or job.get("Title", "")
                job_path = job.get("Path")

                if job_title == title and job_path:
                    LOG.info("Found recording: %s -> %s", title, job_path)
                    return job_path

            # No match found
            LOG.warning("No recording found for: %s", title)
            raise RuntimeError(f"No matching recording found for '{title}'")

        except requests.RequestException as e:
            LOG.error("API request failed: %s", e)
            raise RuntimeError(f"Failed to query Channels DVR API: {e}")
        except (KeyError, ValueError) as e:
            LOG.error("Failed to parse API response: %s", e)
            raise RuntimeError(f"Invalid API response: {e}")

    def get_recording_info(self, file_id: str) -> Optional[dict]:
        """Get detailed information about a recording.

        Args:
            file_id: Recording file ID

        Returns:
            Dictionary with recording details, or None if not found
        """
        if USE_MOCK:
            LOG.info("[MOCK] Would fetch recording info for: %s", file_id)
            return {
                "FileID": file_id,
                "Title": "Mock Recording",
                "Path": f"/tmp/mock_{file_id}.mpg",
            }

        try:
            resp = requests.get(
                f"{self.base_url}/dvr/files/{file_id}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()

        except requests.RequestException as e:
            LOG.error("Failed to get recording info for %s: %s", file_id, e)
            return None
