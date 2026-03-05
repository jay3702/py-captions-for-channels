"""Tests for SettingsService — typed get/set, bulk, delete, defaults."""

import pytest

from py_captions_for_channels.database import get_db
from py_captions_for_channels.services.settings_service import SettingsService


@pytest.fixture
def service():
    db = next(get_db())
    yield SettingsService(db)
    db.close()


class TestGetSet:
    def test_string_roundtrip(self, service):
        service.set("name", "hello")
        assert service.get("name") == "hello"

    def test_bool_roundtrip(self, service):
        service.set("flag", True)
        assert service.get("flag") is True
        service.set("flag", False)
        assert service.get("flag") is False

    def test_int_roundtrip(self, service):
        service.set("count", 42)
        assert service.get("count") == 42

    def test_float_roundtrip(self, service):
        service.set("ratio", 3.14)
        assert service.get("ratio") == pytest.approx(3.14)

    def test_json_dict_roundtrip(self, service):
        data = {"key": "value", "nested": [1, 2, 3]}
        service.set("data", data)
        assert service.get("data") == data

    def test_json_list_roundtrip(self, service):
        data = [1, "two", 3.0]
        service.set("items", data)
        assert service.get("items") == data

    def test_default_when_missing(self, service):
        assert service.get("missing") is None
        assert service.get("missing", "fallback") == "fallback"

    def test_update_existing(self, service):
        service.set("x", 1)
        service.set("x", 2)
        assert service.get("x") == 2


class TestGetAll:
    def test_empty(self, service):
        assert service.get_all() == {}

    def test_multiple(self, service):
        service.set("a", 1)
        service.set("b", "two")
        result = service.get_all()
        assert result == {"a": 1, "b": "two"}


class TestSetMany:
    def test_batch_set(self, service):
        service.set_many({"x": 10, "y": True, "z": "hello"})
        assert service.get("x") == 10
        assert service.get("y") is True
        assert service.get("z") == "hello"


class TestDelete:
    def test_delete_existing(self, service):
        service.set("doomed", "bye")
        assert service.delete("doomed") is True
        assert service.get("doomed") is None

    def test_delete_nonexistent(self, service):
        assert service.delete("nope") is False


class TestInitializeDefaults:
    def test_sets_missing_keys_only(self, service):
        service.set("existing", "original")
        service.initialize_defaults({"existing": "overwrite", "new_key": 42})
        assert service.get("existing") == "original"  # NOT overwritten
        assert service.get("new_key") == 42
