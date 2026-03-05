"""Tests for ChannelsPollingSource — smart interval, partial processing event."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from py_captions_for_channels.channels_polling_source import (
    ChannelsPollingSource,
    PartialProcessingEvent,
)


class TestPartialProcessingEvent:
    def test_defaults(self):
        evt = PartialProcessingEvent(
            timestamp=datetime.now(timezone.utc),
            title="Test Show",
            start_time=datetime.now(timezone.utc),
        )
        assert evt.source == "channels_polling"
        assert evt.path is None
        assert evt.exec_id is None

    def test_with_path(self):
        evt = PartialProcessingEvent(
            timestamp=datetime.now(timezone.utc),
            title="News",
            start_time=datetime.now(timezone.utc),
            path="/rec/news.mpg",
            exec_id="e-123",
        )
        assert evt.path == "/rec/news.mpg"
        assert evt.exec_id == "e-123"


class TestGetSmartInterval:
    def _make_source(self):
        # Use a dummy URL; we won't hit the network
        return ChannelsPollingSource(api_url="http://localhost:8089")

    def _patch_now(self, minute):
        """Return a real datetime with the given minute for mocking."""
        return datetime(2025, 6, 1, 10, minute, 0, tzinfo=timezone.utc)

    def test_near_hour(self):
        src = self._make_source()
        with patch(
            "py_captions_for_channels.channels_polling_source.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = self._patch_now(2)
            interval = src._get_smart_interval()
        assert interval == 60

    def test_near_half_hour(self):
        src = self._make_source()
        with patch(
            "py_captions_for_channels.channels_polling_source.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = self._patch_now(30)
            interval = src._get_smart_interval()
        assert interval == 60

    def test_quiet_period(self):
        src = self._make_source()
        with patch(
            "py_captions_for_channels.channels_polling_source.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = self._patch_now(15)
            interval = src._get_smart_interval()
        assert interval == 300

    def test_near_end_of_hour(self):
        src = self._make_source()
        with patch(
            "py_captions_for_channels.channels_polling_source.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = self._patch_now(57)
            interval = src._get_smart_interval()
        assert interval == 60


class TestCalculateNextCompletion:
    def _make_source(self):
        return ChannelsPollingSource(api_url="http://localhost:8089")

    def test_no_recordings(self):
        src = self._make_source()
        assert src._calculate_next_completion([]) is None

    def test_completed_recording_skipped(self):
        src = self._make_source()
        rec = {"completed": True, "created_at": 0, "duration": 3600}
        assert src._calculate_next_completion([rec]) is None

    def test_future_completion_returned(self):
        src = self._make_source()
        now = datetime.now(timezone.utc)
        # Recording started 10 minutes ago, duration 1 hour → completes in ~50 min
        created_ms = int((now - timedelta(minutes=10)).timestamp() * 1000)
        rec = {"completed": False, "created_at": created_ms, "duration": 3600}
        result = src._calculate_next_completion([rec])
        assert result is not None
        assert result > now
