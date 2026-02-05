import logging
from datetime import datetime
from typing import Optional
import requests
from pathlib import Path

from .config import USE_MOCK, LOCAL_TEST_DIR

LOG = logging.getLogger(__name__)


class ChannelsAPI:
    """Client for Channels DVR HTTP API.

    Provides methods to query recording information and file paths.
    """

    def __init__(self, base_url: str, timeout: int = 10):
        """Initialize API client.

        Args:
            base_url: Base URL of Channels DVR (e.g., http://<CHANNELS_DVR_SERVER>:8089)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._use_local_mock = LOCAL_TEST_DIR is not None

    def _scan_local_recordings(self):
        """Scan LOCAL_TEST_DIR for .mpg files and return in Channels API format.

        Returns:
            List of recording dicts matching Channels API /api/v1/all format
        """
        if not LOCAL_TEST_DIR:
            return []

        recordings = []
        test_dir = Path(LOCAL_TEST_DIR)

        if not test_dir.exists():
            LOG.warning("LOCAL_TEST_DIR does not exist: %s", LOCAL_TEST_DIR)
            return []

        # Find all .mpg files recursively
        for mpg_file in test_dir.rglob("*.mpg"):
            # Skip backup files
            if ".orig" in mpg_file.name or ".tmp" in mpg_file.name:
                continue

            # Get relative path and check if in tmp staging directory
            relative_path = mpg_file.relative_to(test_dir)
            if "tmp" in relative_path.parts:
                continue

            # Get file stats
            stat = mpg_file.stat()
            created_timestamp = int(stat.st_mtime * 1000)  # milliseconds

            # Extract title from path
            # e.g., "TV/CNN News Central/CNN News Central 2026-02-04-1100.mpg"
            parts = relative_path.parts

            # Title is usually the parent directory name or extracted from filename
            if len(parts) >= 2:
                title = parts[-2]  # Parent directory (e.g., "CNN News Central")
            else:
                title = mpg_file.stem

            # Generate a mock ID from the file path
            file_id = f"mock-{mpg_file.stem}"

            recordings.append(
                {
                    "id": file_id,
                    "FileID": file_id,
                    "title": title,
                    "path": str(mpg_file),
                    "created_at": created_timestamp,
                    "completed": True,  # All files in test dir are considered completed
                    "duration": 3600000,  # Mock 1 hour duration (milliseconds)
                }
            )

        LOG.info("[MOCK] Found %d recordings in %s", len(recordings), LOCAL_TEST_DIR)
        return recordings

    def lookup_recording_path(self, title: str, start_time: datetime) -> str:
        """Look up the file path for a recording.

        Query /api/v1/all endpoint sorted by date_added to find recent recordings.
        Uses fuzzy matching against the most recent recordings.

        Args:
            title: Program title from webhook
            start_time: Recording start time (approximate)

        Returns:
            Full file path to the recording

        Raises:
            RuntimeError: If recording not found or API error
        """
        # Use local filesystem scanner when LOCAL_TEST_DIR is set
        if self._use_local_mock:
            LOG.info("[MOCK] Looking up recording from local test dir: %s", title)
            recordings = self._scan_local_recordings()

            # Try exact match first
            for rec in recordings:
                if rec.get("title") == title:
                    LOG.info("[MOCK] Exact match found: %s -> %s", title, rec["path"])
                    return rec["path"]

            # Try case-insensitive match
            title_lower = title.lower()
            for rec in recordings:
                if rec.get("title", "").lower() == title_lower:
                    LOG.info(
                        "[MOCK] Case-insensitive match: %s -> %s", title, rec["path"]
                    )
                    return rec["path"]

            # No match found
            available_titles = [r.get("title", "") for r in recordings]
            raise RuntimeError(
                f"[MOCK] Recording not found: {title}. Available: {available_titles}"
            )

        if USE_MOCK:
            # Return a synthetic path for testing (old mock mode)
            safe_title = title.replace(" ", "_")
            mock_path = f"/tmp/{safe_title}.mpg"
            LOG.info("[MOCK] Returning mock path: %s", mock_path)
            return mock_path

        LOG.info("Looking up recording: %s (start: %s)", title, start_time)

        try:
            # Query recent recordings sorted by date_added (most recent first)
            resp = requests.get(
                f"{self.base_url}/api/v1/all",
                params={"sort": "date_added", "order": "desc", "source": "recordings"},
                timeout=self.timeout,
            )
            resp.raise_for_status()

            recordings = resp.json()
            LOG.debug("Retrieved %d recordings from API", len(recordings))

            # Only check the most recent recordings (last hour or so)
            # Webhook arrives right after completion, so match should be in top results
            recent_count = min(20, len(recordings))
            recent_recordings = recordings[:recent_count]

            # Log available recent titles for debugging
            recent_titles = [r.get("title", "") for r in recent_recordings[:5]]
            LOG.info("Recent recordings: %s", recent_titles)

            # Try exact match first
            for recording in recent_recordings:
                rec_title = recording.get("title", "")
                rec_path = recording.get("path")

                if rec_title == title and rec_path:
                    LOG.info("Exact match found: %s -> %s", title, rec_path)
                    return rec_path

            # Try partial/fuzzy match on recent recordings
            title_lower = title.lower()
            for recording in recent_recordings:
                rec_title = recording.get("title", "")
                rec_path = recording.get("path")

                # Case-insensitive partial match
                if rec_path and rec_title.lower() == title_lower:
                    LOG.info(
                        "Case-insensitive match found: %s -> %s", rec_title, rec_path
                    )
                    return rec_path

                # Contains match (for titles with extra info)
                if rec_path and (
                    title_lower in rec_title.lower() or rec_title.lower() in title_lower
                ):
                    LOG.info("Partial match found: %s -> %s", rec_title, rec_path)
                    return rec_path

            # No match found in recent recordings
            LOG.warning(
                "No recording found for: %s (checked %d recent recordings)",
                title,
                recent_count,
            )
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
