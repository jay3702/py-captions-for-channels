"""Tests for JobNumberManager — incrementing counters with midnight reset."""

from datetime import date

import pytest

from py_captions_for_channels.job_number_manager import JobNumberManager


class TestJobNumberManager:
    def test_get_next_increments(self):
        mgr = JobNumberManager()
        assert mgr.get_next() == 1
        assert mgr.get_next() == 2
        assert mgr.get_next() == 3

    def test_get_current_no_increment(self):
        mgr = JobNumberManager()
        assert mgr.get_current() == 0  # No jobs yet
        mgr.get_next()
        assert mgr.get_current() == 1  # Still 1

    def test_reset_on_new_day(self):
        mgr = JobNumberManager()
        mgr.get_next()
        mgr.get_next()
        assert mgr.get_current() == 2

        # Directly manipulate _current_date to simulate a day change
        from datetime import timedelta as td

        mgr._current_date = date.today() - td(days=1)
        assert mgr.get_next() == 1  # Reset!

    def test_timezone_aware(self):
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo("America/Los_Angeles")
        except (ImportError, KeyError):
            pytest.skip("tzdata not available")
        mgr = JobNumberManager(server_tz=tz)
        assert mgr.get_next() == 1

    def test_utc_fallback(self):
        mgr = JobNumberManager(server_tz=None)
        assert mgr.get_next() == 1
