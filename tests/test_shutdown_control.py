"""Tests for ShutdownController — immediate/graceful shutdown state."""

import asyncio

from py_captions_for_channels.shutdown_control import ShutdownController


class TestShutdownController:
    def test_initial_state(self):
        sc = ShutdownController()
        assert sc.is_shutdown_requested() is False
        assert sc.is_graceful_shutdown() is False
        assert sc.is_immediate_shutdown() is False

    def test_immediate_shutdown(self):
        sc = ShutdownController()
        sc.request_immediate_shutdown(initiated_by="test")
        assert sc.is_shutdown_requested() is True
        assert sc.is_immediate_shutdown() is True
        assert sc.is_graceful_shutdown() is False

    def test_graceful_shutdown(self):
        sc = ShutdownController()
        sc.request_graceful_shutdown(initiated_by="test")
        assert sc.is_shutdown_requested() is True
        assert sc.is_graceful_shutdown() is True
        assert sc.is_immediate_shutdown() is False

    def test_duplicate_request_ignored(self):
        sc = ShutdownController()
        sc.request_graceful_shutdown(initiated_by="first")
        sc.request_immediate_shutdown(initiated_by="second")
        # First request wins
        assert sc.is_graceful_shutdown() is True

    def test_get_state_no_shutdown(self):
        sc = ShutdownController()
        state = sc.get_state()
        assert state["shutdown_requested"] is False
        assert state["shutdown_graceful"] is False
        assert state["shutdown_requested_at"] is None
        assert state["shutdown_initiated_by"] is None

    def test_get_state_after_shutdown(self):
        sc = ShutdownController()
        sc.request_immediate_shutdown(initiated_by="api")
        state = sc.get_state()
        assert state["shutdown_requested"] is True
        assert state["shutdown_graceful"] is False
        assert state["shutdown_initiated_by"] == "api"
        assert state["shutdown_requested_at"] is not None

    def test_wait_for_shutdown_event_is_set(self):
        sc = ShutdownController()
        sc.request_graceful_shutdown("test")

        # The event should already be set, so wait returns immediately
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.wait_for(sc.wait_for_shutdown(), timeout=1))
        finally:
            loop.close()
