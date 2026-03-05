"""Tests for database module — session management and initialization."""

from py_captions_for_channels.database import get_db, init_db


class TestGetDb:
    def test_yields_session(self):
        gen = get_db()
        db = next(gen)
        assert db is not None
        # Cleanup generator
        try:
            next(gen)
        except StopIteration:
            pass

    def test_session_is_functional(self):
        gen = get_db()
        db = next(gen)
        # Should be able to execute a simple query
        result = db.execute(__import__("sqlalchemy").text("SELECT 1")).scalar()
        assert result == 1
        try:
            next(gen)
        except StopIteration:
            pass


class TestInitDb:
    def test_creates_tables(self):
        # init_db is called by conftest fixture, tables should exist
        from py_captions_for_channels import database as db_module
        from sqlalchemy import inspect

        inspector = inspect(db_module.engine)
        tables = inspector.get_table_names()
        assert "executions" in tables
        assert "settings" in tables
        assert "manual_queue" in tables
        assert "heartbeats" in tables
        assert "progress" in tables
        assert "quarantine_items" in tables
        assert "polling_cache" in tables

    def test_idempotent(self):
        # Calling init_db multiple times should not raise
        init_db()
        init_db()
