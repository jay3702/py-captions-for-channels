"""Tests for the watchdog: stuck-loop detection and restart-budget logic."""

from datetime import datetime, timedelta, timezone

import pytest

from py_captions_for_channels.watchdog import (
    ServiceWatchdog,
    _WatchdogState,
    assess_stuck_loops,
)

WATCHED = [("manual", "manual_process"), ("polling", "normal")]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now():
    return datetime.now(timezone.utc)


class TestAssessStuckLoops:
    def test_fresh_heartbeat_is_not_stuck(self):
        heartbeats = {"manual": {"age_seconds": 5.0}}
        result = assess_stuck_loops(
            heartbeats,
            [],
            {},
            heartbeat_stale_seconds=100,
            progress_fresh_seconds=60,
            watched_loops=WATCHED,
        )
        assert result.stuck is False
        assert result.loops[0].name == "manual"
        assert result.loops[0].stuck is False

    def test_missing_heartbeat_is_skipped_not_stuck(self):
        # e.g. polling loop isn't running in webhook mode
        heartbeats = {"manual": {"age_seconds": 5.0}}
        result = assess_stuck_loops(
            heartbeats,
            [],
            {},
            heartbeat_stale_seconds=100,
            progress_fresh_seconds=60,
            watched_loops=WATCHED,
        )
        names = [loop.name for loop in result.loops]
        assert "polling" not in names

    def test_stale_heartbeat_with_no_running_job_is_stuck(self):
        heartbeats = {"manual": {"age_seconds": 500.0}}
        result = assess_stuck_loops(
            heartbeats,
            [],
            {},
            heartbeat_stale_seconds=100,
            progress_fresh_seconds=60,
            watched_loops=WATCHED,
        )
        assert result.stuck is True
        assert result.stuck_loop_names == ["manual"]
        assert result.max_stuck_age_seconds == 500.0

    def test_stale_heartbeat_with_fresh_progress_is_busy_not_stuck(self):
        heartbeats = {"manual": {"age_seconds": 500.0}}
        running = [{"id": "job-1", "kind": "manual_process", "status": "running"}]
        progress = {
            "job-1": {"updated_at": _iso(_now() - timedelta(seconds=5))},
        }
        result = assess_stuck_loops(
            heartbeats,
            running,
            progress,
            heartbeat_stale_seconds=100,
            progress_fresh_seconds=60,
            watched_loops=WATCHED,
        )
        assert result.stuck is False

    def test_stale_heartbeat_with_stale_progress_is_stuck(self):
        heartbeats = {"manual": {"age_seconds": 500.0}}
        running = [{"id": "job-1", "kind": "manual_process", "status": "running"}]
        progress = {
            "job-1": {"updated_at": _iso(_now() - timedelta(seconds=1000))},
        }
        result = assess_stuck_loops(
            heartbeats,
            running,
            progress,
            heartbeat_stale_seconds=100,
            progress_fresh_seconds=60,
            watched_loops=WATCHED,
        )
        assert result.stuck is True

    def test_stale_heartbeat_with_no_matching_running_job_is_stuck(self):
        # A job is running, but for the *other* loop's kind — shouldn't count.
        heartbeats = {"manual": {"age_seconds": 500.0}}
        running = [{"id": "job-1", "kind": "normal", "status": "running"}]
        progress = {"job-1": {"updated_at": _iso(_now())}}
        result = assess_stuck_loops(
            heartbeats,
            running,
            progress,
            heartbeat_stale_seconds=100,
            progress_fresh_seconds=60,
            watched_loops=WATCHED,
        )
        assert result.stuck is True

    def test_multiple_stuck_loops_reports_max_age(self):
        heartbeats = {
            "manual": {"age_seconds": 500.0},
            "polling": {"age_seconds": 900.0},
        }
        result = assess_stuck_loops(
            heartbeats,
            [],
            {},
            heartbeat_stale_seconds=100,
            progress_fresh_seconds=60,
            watched_loops=WATCHED,
        )
        assert set(result.stuck_loop_names) == {"manual", "polling"}
        assert result.max_stuck_age_seconds == 900.0


class TestWatchdogState:
    def test_recent_restarts_prunes_old_entries(self, tmp_path):
        state = _WatchdogState(str(tmp_path / "watchdog_state.json"))
        old = _now() - timedelta(hours=48)
        recent = _now() - timedelta(hours=1)
        state.restarts = [_iso(old), _iso(recent)]
        kept = state.recent_restarts(24 * 3600)
        assert kept == [_iso(recent)]

    def test_record_restart_persists_across_instances(self, tmp_path):
        path = str(tmp_path / "watchdog_state.json")
        state = _WatchdogState(path)
        state.record_restart()

        reloaded = _WatchdogState(path)
        assert len(reloaded.restarts) == 1


class TestRestartBudget:
    @pytest.fixture
    def watchdog(self, tmp_path, monkeypatch):
        import py_captions_for_channels.config as config

        monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(config, "WATCHDOG_MAX_RESTARTS_PER_DAY", 2)
        monkeypatch.setattr(config, "WATCHDOG_MIN_RESTART_INTERVAL_SECONDS", 1800)
        return ServiceWatchdog()

    def test_budget_available_when_no_restarts(self, watchdog):
        assert watchdog._restart_budget_available() is True

    def test_budget_blocked_within_min_interval(self, watchdog):
        watchdog._state.record_restart()
        assert watchdog._restart_budget_available() is False

    def test_budget_blocked_after_daily_cap(self, watchdog, monkeypatch):
        import py_captions_for_channels.config as config

        monkeypatch.setattr(config, "WATCHDOG_MIN_RESTART_INTERVAL_SECONDS", 0)
        watchdog._state.restarts = [
            _iso(_now() - timedelta(minutes=10)),
            _iso(_now() - timedelta(minutes=5)),
        ]
        assert watchdog._restart_budget_available() is False

    def test_attempt_restart_exits_process_when_budget_available(
        self, watchdog, monkeypatch
    ):
        import py_captions_for_channels.watchdog as watchdog_module

        exit_calls = []
        monkeypatch.setattr(
            watchdog_module.os, "_exit", lambda code: exit_calls.append(code)
        )
        watchdog._attempt_restart(reason="test")
        assert exit_calls == [1]
        assert len(watchdog._state.restarts) == 1

    def test_attempt_restart_does_not_exit_when_budget_exhausted(
        self, watchdog, monkeypatch
    ):
        import py_captions_for_channels.watchdog as watchdog_module

        watchdog._state.record_restart()  # burns the min-interval budget

        exit_calls = []
        monkeypatch.setattr(
            watchdog_module.os, "_exit", lambda code: exit_calls.append(code)
        )
        watchdog._attempt_restart(reason="test")
        assert exit_calls == []
