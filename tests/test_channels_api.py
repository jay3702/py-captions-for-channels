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
            # API v1/all returns recordings with lowercase fields (title, path)
            recordings = [
                {
                    "title": "Extra",
                    "path": "/recordings/Extra-2026-01-15.mpg",
                    "date_added": "2026-01-15T14:30:00Z",
                },
                {
                    "title": "KRON 4 News",
                    "path": "/recordings/KRON_4_News-2026-01-15.mpg",
                    "date_added": "2026-01-15T14:00:00Z",
                },
            ]
            mock_response.json.return_value = recordings
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            path = api.lookup_recording_path("Extra", datetime.now())

            assert path == "/recordings/Extra-2026-01-15.mpg"
            mock_get.assert_called_once_with(
                "http://localhost:8089/api/v1/all",
                params={"sort": "date_added", "order": "desc", "source": "recordings"},
                timeout=10,
            )


def test_channels_api_recording_not_found(mock_api_response):
    """Test that API raises error when recording not found."""
    with patch("py_captions_for_channels.channels_api.USE_MOCK", False):
        api = ChannelsAPI("http://localhost:8089")

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            with pytest.raises(RuntimeError, match="No matching recording found"):
                api.lookup_recording_path("NonExistent Show", datetime.now())


def test_channels_api_request_error():
    """Test that API handles request errors gracefully."""
    with patch("py_captions_for_channels.channels_api.USE_MOCK", False):
        api = ChannelsAPI("http://localhost:8089")

        with patch("requests.get") as mock_get:
            mock_get.side_effect = requests.RequestException("Connection failed")

            with pytest.raises(RuntimeError, match="Failed to query Channels DVR API"):
                api.lookup_recording_path("Test Show", datetime.now())


def test_channels_api_invalid_response():
    """Test that API handles invalid JSON responses."""
    with patch("py_captions_for_channels.channels_api.USE_MOCK", False):
        api = ChannelsAPI("http://localhost:8089")

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            with pytest.raises(RuntimeError, match="Invalid API response"):
                api.lookup_recording_path("Test Show", datetime.now())


def test_channels_api_get_recording_info_mock():
    """Test get_recording_info in mock mode."""
    with patch("py_captions_for_channels.channels_api.USE_MOCK", True):
        api = ChannelsAPI("http://localhost:8089")
        info = api.get_recording_info("12345")

        assert info is not None
        assert info["FileID"] == "12345"
        assert "Path" in info


def test_channels_api_get_recording_info_real():
    """Test get_recording_info with real API call."""
    with patch("py_captions_for_channels.channels_api.USE_MOCK", False):
        api = ChannelsAPI("http://localhost:8089")

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "FileID": "12345",
                "Title": "Test Recording",
                "Path": "/recordings/test.mpg",
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            info = api.get_recording_info("12345")

            assert info["FileID"] == "12345"
            assert info["Title"] == "Test Recording"
            mock_get.assert_called_once_with(
                "http://localhost:8089/dvr/files/12345",
                timeout=10,
            )


def test_channels_api_base_url_normalization():
    """Test that trailing slashes are removed from base URL."""
    api1 = ChannelsAPI("http://localhost:8089")
    api2 = ChannelsAPI("http://localhost:8089/")

    assert api1.base_url == api2.base_url
    assert api1.base_url == "http://localhost:8089"
