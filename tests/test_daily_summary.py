"""Tests for the daily summary module."""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from py_captions_for_channels.daily_summary import (
    generate_daily_summary,
    _format_duration,
)


def test_format_duration_seconds():
    assert _format_duration(45) == "45s"


def test_format_duration_minutes():
    assert _format_duration(125) == "2m 5s"


def test_format_duration_hours():
    assert _format_duration(3725) == "1h 2m"


def _make_execution(
    title="Test Show",
    success=True,
    elapsed=120.0,
    status="completed",
    error_message=None,
    started_at=None,
):
    """Create a mock Execution object."""
    ex = MagicMock()
    ex.title = title
    ex.success = success
    ex.elapsed_seconds = elapsed
    ex.status = status
    ex.error_message = error_message
    ex.started_at = started_at or datetime.now(timezone.utc)
    return ex


def test_generate_daily_summary_no_executions():
    """Returns None when there are no executions for the day."""
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = []

    def mock_get_db():
        yield mock_db

    with patch("py_captions_for_channels.daily_summary.get_db", mock_get_db):
        result = generate_daily_summary(datetime.now(timezone.utc))
    assert result is None


def test_generate_daily_summary_with_data():
    """Generates a summary with success/failure counts."""
    now = datetime.now(timezone.utc)
    execs = [
        _make_execution("Show A", success=True, elapsed=100.0, started_at=now),
        _make_execution("Show B", success=True, elapsed=200.0, started_at=now),
        _make_execution(
            "Show C",
            success=False,
            elapsed=50.0,
            status="failed",
            error_message="exit code 1",
            started_at=now,
        ),
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = execs

    def mock_get_db():
        yield mock_db

    with patch("py_captions_for_channels.daily_summary.get_db", mock_get_db):
        result = generate_daily_summary(now)

    assert result is not None
    assert "Total jobs: 3" in result
    assert "Successes:  2" in result
    assert "Failures:   1" in result
    assert "Show C" in result
    assert "Avg time:" in result


def test_generate_daily_summary_with_recovery():
    """Shows recovered count when crash recoveries occurred."""
    now = datetime.now(timezone.utc)
    execs = [
        _make_execution("Show A", success=True, elapsed=200.0, started_at=now),
        _make_execution(
            "Show B",
            success=True,
            elapsed=220.0,
            error_message="Recovered from SIGSEGV",
            started_at=now,
        ),
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = execs

    def mock_get_db():
        yield mock_db

    with patch("py_captions_for_channels.daily_summary.get_db", mock_get_db):
        result = generate_daily_summary(now)

    assert "Recovered:  1" in result
    assert "Successes:  2" in result
