import pytest
from datetime import datetime
from unittest.mock import patch, Mock
import requests

from py_captions_for_channels.channels_api import ChannelsAPI


@pytest.fixture
def mock_api_response():
    """Mock API response with sample recording data."""
    return [
        {
            "Name": "Extra",
            "Title": "Extra",
            "Path": "/recordings/Extra-2026-01-15.mpg",
            "StartTime": "2026-01-15T14:30:00Z",
        },
        {
            "Name": "KRON 4 News",
            "Title": "KRON 4 News",
            "Path": "/recordings/KRON_4_News-2026-01-15.mpg",
            "StartTime": "2026-01-15T14:00:00Z",
        },
    ]


def test_channels_api_mock_mode():
    """Test that mock mode returns synthetic paths."""
    with patch("py_captions_for_channels.channels_api.USE_MOCK", True):
        api = ChannelsAPI("http://localhost:8089")
        path = api.lookup_recording_path("Test Show", datetime.now())

        assert path == "/tmp/Test_Show.mpg"


def test_channels_api_finds_recording(mock_api_response):
    """Test that API correctly finds and returns recording path."""
    with patch("py_captions_for_channels.channels_api.USE_MOCK", False):
        api = ChannelsAPI("http://localhost:8089")

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            path = api.lookup_recording_path("Extra", datetime.now())

            assert path == "/recordings/Extra-2026-01-15.mpg"
