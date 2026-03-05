"""Tests for config module — env helpers and configuration loading."""

import os
import pytest

from py_captions_for_channels.config import get_env_bool, get_env_int


class TestGetEnvBool:
    def test_true_values(self, monkeypatch):
        for val in ("true", "1", "yes", "on", "True", "YES", "ON"):
            monkeypatch.setenv("TEST_BOOL", val)
            assert get_env_bool("TEST_BOOL", False) is True

    def test_false_values(self, monkeypatch):
        for val in ("false", "0", "no", "off", "anything"):
            monkeypatch.setenv("TEST_BOOL", val)
            assert get_env_bool("TEST_BOOL", True) is False

    def test_unset_returns_default_true(self, monkeypatch):
        monkeypatch.delenv("TEST_BOOL_X", raising=False)
        assert get_env_bool("TEST_BOOL_X", True) is True

    def test_unset_returns_default_false(self, monkeypatch):
        monkeypatch.delenv("TEST_BOOL_Y", raising=False)
        assert get_env_bool("TEST_BOOL_Y", False) is False


class TestGetEnvInt:
    def test_valid_int(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "42")
        assert get_env_int("TEST_INT", 0) == 42

    def test_invalid_int_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "not_a_number")
        assert get_env_int("TEST_INT", 99) == 99

    def test_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("TEST_INT_X", raising=False)
        assert get_env_int("TEST_INT_X", 7) == 7

    def test_negative_int(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "-5")
        assert get_env_int("TEST_INT", 0) == -5

    def test_zero(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "0")
        assert get_env_int("TEST_INT", 10) == 0
