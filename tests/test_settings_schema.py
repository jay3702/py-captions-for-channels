"""Tests for the settings schema and the .env parsing/grouping it drives.

This area had a real regression while being built: an ALL-CAPS header
heuristic in the parser misclassified commented numeric settings like
"# NVENC_CQ=23" as section headers and silently dropped them. These tests
pin down that behavior plus the schema's internal consistency.
"""

from pathlib import Path

import pytest

from py_captions_for_channels.settings_schema import (
    GROUPS,
    HIDDEN_KEYS,
    SETTINGS_SCHEMA,
)
from py_captions_for_channels.web_app import (
    _is_section_header_comment,
    _parse_env_file,
    load_env_settings,
)


class TestSettingsSchemaConsistency:
    def test_every_schema_entry_has_a_valid_group(self):
        valid_groups = {key for key, _ in GROUPS}
        for setting_key, spec in SETTINGS_SCHEMA.items():
            assert (
                spec.group in valid_groups
            ), f"{setting_key} references unknown group {spec.group!r}"

    def test_every_schema_entry_has_a_valid_tier(self):
        for setting_key, spec in SETTINGS_SCHEMA.items():
            assert spec.tier in ("basic", "advanced"), setting_key

    def test_select_fields_declare_options(self):
        for setting_key, spec in SETTINGS_SCHEMA.items():
            if spec.type == "select":
                assert spec.options, f"{setting_key} is a select with no options"

    def test_hidden_keys_and_schema_do_not_overlap(self):
        overlap = HIDDEN_KEYS & set(SETTINGS_SCHEMA.keys())
        assert not overlap, f"keys both hidden and scheduled: {overlap}"

    def test_group_keys_are_unique(self):
        keys = [key for key, _ in GROUPS]
        assert len(keys) == len(set(keys))


class TestSectionHeaderHeuristic:
    def test_all_caps_title_is_a_header(self):
        assert _is_section_header_comment("CHANNELS DVR CONFIGURATION")

    def test_punctuation_divider_is_a_header(self):
        assert _is_section_header_comment("----------------------------")

    def test_mixed_case_sentence_is_not_a_header(self):
        assert not _is_section_header_comment(
            "How often the watchdog checks for a stuck loop, in seconds."
        )

    def test_empty_string_is_not_a_header(self):
        assert not _is_section_header_comment("")


class TestParseEnvFile:
    def _write(self, tmp_path, content: str) -> Path:
        path = tmp_path / ".env.test"
        path.write_text(content, encoding="utf-8")
        return path

    def test_commented_numeric_setting_is_not_dropped(self, tmp_path):
        # This is the exact shape that triggered the regression: a numeric
        # commented setting immediately following a "Default: N" comment.
        content = (
            "# ==============================================================\n"
            "# WATCHDOG CONFIGURATION\n"
            "# ==============================================================\n"
            "\n"
            "# How often the watchdog checks for a stuck loop, in seconds.\n"
            "# Default: 60\n"
            "# WATCHDOG_CHECK_INTERVAL_SECONDS=60\n"
        )
        parsed = _parse_env_file(self._write(tmp_path, content))
        assert "WATCHDOG_CHECK_INTERVAL_SECONDS" in parsed
        assert parsed["WATCHDOG_CHECK_INTERVAL_SECONDS"]["value"] == "60"
        assert parsed["WATCHDOG_CHECK_INTERVAL_SECONDS"]["optional"] is True

    def test_active_numeric_setting_is_parsed(self, tmp_path):
        content = "NVENC_CQ=23\n"
        parsed = _parse_env_file(self._write(tmp_path, content))
        assert parsed["NVENC_CQ"]["value"] == "23"
        assert parsed["NVENC_CQ"]["optional"] is False

    def test_commented_all_caps_value_setting_is_not_dropped(self, tmp_path):
        # The exact real-world regression: "NVENC_CQ=23" as a whole string
        # has no lowercase letters, so it must never reach the header check.
        content = "# NVENC_CQ=23\n"
        parsed = _parse_env_file(self._write(tmp_path, content))
        assert "NVENC_CQ" in parsed
        assert parsed["NVENC_CQ"]["value"] == "23"

    def test_inline_trailing_comment_is_stripped_from_value(self, tmp_path):
        content = "# LIBRARY_HOST_PATH=/tank/AllMedia          # host path exposed\n"
        parsed = _parse_env_file(self._write(tmp_path, content))
        assert parsed["LIBRARY_HOST_PATH"]["value"] == "/tank/AllMedia"

    def test_default_extracted_from_preceding_description(self, tmp_path):
        content = (
            "# Base polling interval in seconds\n"
            "# Default: 120\n"
            "POLL_INTERVAL_SECONDS=120\n"
        )
        parsed = _parse_env_file(self._write(tmp_path, content))
        assert parsed["POLL_INTERVAL_SECONDS"]["default"] == "120"

    def test_section_header_does_not_pollute_next_description(self, tmp_path):
        content = (
            "# ==============================================================\n"
            "# CAPTION PIPELINE CONFIGURATION\n"
            "# ==============================================================\n"
            "\n"
            "# Keep original recording as backup\n"
            "KEEP_ORIGINAL=true\n"
        )
        parsed = _parse_env_file(self._write(tmp_path, content))
        assert (
            "CAPTION PIPELINE CONFIGURATION"
            not in parsed["KEEP_ORIGINAL"]["description"]
        )


class TestLoadEnvSettingsAgainstRealTemplate:
    """Smoke-tests load_env_settings() against the repo's real .env.example,
    so a schema/parser mismatch (a key silently falling through the cracks)
    is caught in CI rather than discovered in the UI."""

    @pytest.fixture(autouse=True)
    def _isolate_env_file(self, tmp_path, monkeypatch):
        # Point get_env_file_path() at an empty scratch file so this test
        # only ever reflects .env.example (the template), never this
        # machine's real, potentially sensitive .env.
        import py_captions_for_channels.web_app as web_app

        empty_env = tmp_path / ".env"
        empty_env.write_text("", encoding="utf-8")
        monkeypatch.setattr(web_app, "get_env_file_path", lambda: empty_env)

    def test_every_schema_key_present_in_env_example_is_loaded(self):
        env_example = Path(__file__).resolve().parents[1] / ".env.example"
        template = _parse_env_file(env_example)

        result = load_env_settings()
        assert "error" not in result

        loaded_keys = {
            key for items in result.values() for key in items if isinstance(items, dict)
        }
        for key in template:
            if key in HIDDEN_KEYS or key not in SETTINGS_SCHEMA:
                continue
            assert key in loaded_keys, (
                f"{key} is in .env.example + schema but missing from "
                "load_env_settings()"
            )

    def test_no_group_is_left_empty_dict_by_mistake(self):
        result = load_env_settings()
        for group_key, _ in GROUPS:
            assert group_key in result
