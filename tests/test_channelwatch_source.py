import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from py_captions_for_channels.channelwatch_source import (
    ChannelWatchSource,
    PartialProcessingEvent,
)


@pytest.mark.asyncio
async def test_channelwatch_parses_valid_event():
    """Test that ChannelWatchSource correctly parses a valid event."""
    source = ChannelWatchSource("ws://localhost:8089", base_delay=0.1, max_delay=1.0)

    # Mock the websocket connection
    mock_ws = AsyncMock()
    mock_ws.__aiter__.return_value = [
        json.dumps(
            {
                "event": "recording_completed",
                "timestamp": "2026-01-15T10:00:00",
                "title": "Test Show",
                "start_time": "2026-01-15T09:00:00",
            }
        )
    ]

    with patch("websockets.connect", return_value=mock_ws):
        mock_ws.__aenter__.return_value = mock_ws
        mock_ws.__aexit__.return_value = None

        events_iter = source.events()
        event = await events_iter.__anext__()

        assert isinstance(event, PartialProcessingEvent)
        assert event.title == "Test Show"
        assert event.timestamp == datetime.fromisoformat("2026-01-15T10:00:00")
        assert event.start_time == datetime.fromisoformat("2026-01-15T09:00:00")
        assert event.source == "channelwatch"


@pytest.mark.asyncio
async def test_channelwatch_ignores_invalid_json():
    """Test that ChannelWatchSource ignores invalid JSON and continues."""
    source = ChannelWatchSource("ws://localhost:8089", base_delay=0.1, max_delay=1.0)

    mock_ws = AsyncMock()
    mock_ws.__aiter__.return_value = [
        "not valid json",
        json.dumps(
            {
                "event": "recording_completed",
                "timestamp": "2026-01-15T10:00:00",
                "title": "Valid Event",
                "start_time": "2026-01-15T09:00:00",
            }
        ),
    ]

    with patch("websockets.connect", return_value=mock_ws):
        mock_ws.__aenter__.return_value = mock_ws
        mock_ws.__aexit__.return_value = None

        events_iter = source.events()
        event = await events_iter.__anext__()

        assert event.title == "Valid Event"


@pytest.mark.asyncio
async def test_channelwatch_ignores_incomplete_event():
    """Test that ChannelWatchSource ignores events with missing fields."""
    source = ChannelWatchSource("ws://localhost:8089", base_delay=0.1, max_delay=1.0)

    mock_ws = AsyncMock()
    mock_ws.__aiter__.return_value = [
        json.dumps({"event": "recording_completed", "title": "Missing Fields"}),
        json.dumps(
            {
                "event": "recording_completed",
                "timestamp": "2026-01-15T10:00:00",
                "title": "Complete Event",
                "start_time": "2026-01-15T09:00:00",
            }
        ),
    ]

    with patch("websockets.connect", return_value=mock_ws):
        mock_ws.__aenter__.return_value = mock_ws
        mock_ws.__aexit__.return_value = None

        events_iter = source.events()
        event = await events_iter.__anext__()

        assert event.title == "Complete Event"


@pytest.mark.asyncio
async def test_channelwatch_ignores_non_recording_events():
    """Test that ChannelWatchSource ignores events that aren't recording_completed."""
    source = ChannelWatchSource("ws://localhost:8089", base_delay=0.1, max_delay=1.0)

    mock_ws = AsyncMock()
    mock_ws.__aiter__.return_value = [
        json.dumps({"event": "other_event", "data": "ignored"}),
        json.dumps(
            {
                "event": "recording_completed",
                "timestamp": "2026-01-15T10:00:00",
                "title": "Correct Event",
                "start_time": "2026-01-15T09:00:00",
            }
        ),
    ]

    with patch("websockets.connect", return_value=mock_ws):
        mock_ws.__aenter__.return_value = mock_ws
        mock_ws.__aexit__.return_value = None

        events_iter = source.events()
        event = await events_iter.__anext__()

        assert event.title == "Correct Event"
