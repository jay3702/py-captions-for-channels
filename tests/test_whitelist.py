"""Tests for whitelist functionality including regex support."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from py_captions_for_channels.whitelist import Whitelist, WhitelistRule


def test_simple_substring_match():
    """Test basic substring matching (backward compatibility)."""
    rule = WhitelistRule("News")
    assert rule.matches("CNN News Central")
    assert rule.matches("News at 6")
    assert rule.matches("evening news")
    assert not rule.matches("Documentary")


def test_regex_pattern_match():
    """Test regex pattern matching."""
    # Pattern with anchors
    rule = WhitelistRule("^CNN News")
    assert rule.matches("CNN News Central")
    assert rule.matches("CNN News Night")
    assert not rule.matches("ABC News")
    assert not rule.matches("The CNN News")


def test_regex_with_alternation():
    """Test regex with alternation (OR)."""
    rule = WhitelistRule("News.*(Central|Night)")
    assert rule.matches("CNN News Central")
    assert rule.matches("CNN NewsNight With Abby Phillip")
    assert rule.matches("News Something Central")
    assert not rule.matches("News Hour")
    assert not rule.matches("News Morning")


def test_regex_case_insensitive():
    """Test that regex patterns are case-insensitive."""
    rule = WhitelistRule("^cnn news")
    assert rule.matches("CNN News Central")
    assert rule.matches("cnn news central")
    assert rule.matches("Cnn News Central")


def test_substring_case_insensitive():
    """Test that substring matches are case-insensitive."""
    rule = WhitelistRule("news")
    assert rule.matches("NEWS")
    assert rule.matches("News")
    assert rule.matches("news")


def test_regex_with_special_chars():
    """Test regex with various special characters."""
    # Dot matches any character
    rule = WhitelistRule("News.*Central")
    assert rule.matches("News Central")
    assert rule.matches("News XYZ Central")

    # Plus (one or more)
    rule = WhitelistRule("News+")
    assert rule.matches("News")
    assert rule.matches("Newsss")

    # Question mark (optional)
    rule = WhitelistRule("News?")
    assert rule.matches("New")
    assert rule.matches("News")


def test_invalid_regex_falls_back_to_substring():
    """Test that invalid regex patterns fall back to substring matching."""
    # Unmatched bracket - invalid regex
    rule = WhitelistRule("News[")
    assert not rule.is_regex  # Should fall back to substring
    assert rule.matches("News[")
    assert rule.matches("The News[ Show")


def test_complex_rule_with_substring():
    """Test time-based rule with substring matching."""
    rule = WhitelistRule("Dateline;Friday;11.1;21:00")
    friday = datetime(2026, 1, 16, 21, 0)  # Friday, Jan 16, 2026 at 21:00

    assert rule.matches("Dateline NBC", friday)
    assert not rule.matches("20/20", friday)


def test_complex_rule_with_regex():
    """Test time-based rule with regex pattern."""
    rule = WhitelistRule("^Dateline.*;Friday;11.1;21:00")
    friday = datetime(2026, 1, 16, 21, 0)  # Friday, Jan 16, 2026 at 21:00

    assert rule.matches("Dateline NBC", friday)
    assert rule.matches("Dateline Special", friday)
    assert not rule.matches(
        "The Dateline Show", friday
    )  # Doesn't start with "Dateline"


def test_whitelist_file_with_mixed_patterns():
    """Test whitelist file with both substring and regex patterns."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("# Test whitelist\n")
        f.write("News\n")  # Substring
        f.write("^CNN News\n")  # Regex
        f.write(".*Central$\n")  # Regex
        f.write("# Comment\n")
        f.write("\n")
        f.write("Documentary\n")  # Substring
        temp_path = f.name

    try:
        whitelist = Whitelist(temp_path)
        assert whitelist.enabled
        assert len(whitelist.rules) == 4

        # Test substring match
        assert whitelist.is_allowed("ABC News")  # Matches "News" rule
        assert whitelist.is_allowed("Documentary Film")  # Matches "Documentary" rule

        # Test regex match
        assert whitelist.is_allowed("CNN News Night")  # Matches "^CNN News" rule
        assert whitelist.is_allowed("News Central")  # Matches ".*Central$" rule

        # ABC NewsNight matches "News" rule (substring), so it IS allowed
        assert whitelist.is_allowed("ABC NewsNight")

        # Something that doesn't match any rule
        assert not whitelist.is_allowed("The Weather Channel")

    finally:
        Path(temp_path).unlink()


def test_whitelist_disabled_allows_all():
    """Test that disabled whitelist allows all recordings."""
    whitelist = Whitelist()  # No file
    assert not whitelist.enabled
    assert whitelist.is_allowed("Any Show")
    assert whitelist.is_allowed("Another Show")


def test_whitelist_regex_operators_detection():
    """Test that regex operators are properly detected."""
    # These should be detected as regex
    assert WhitelistRule("^News").is_regex
    assert WhitelistRule("News$").is_regex
    assert WhitelistRule("News.*Central").is_regex
    assert WhitelistRule("News+").is_regex
    assert WhitelistRule("News?").is_regex
    assert WhitelistRule("News|Central").is_regex
    assert WhitelistRule("News[123]").is_regex
    assert WhitelistRule("News{2,}").is_regex
    assert WhitelistRule(r"News\s+Central").is_regex

    # These should NOT be detected as regex (substring match)
    assert not WhitelistRule("News").is_regex
    assert not WhitelistRule("CNN News Central").is_regex
    assert not WhitelistRule("20/20").is_regex


def test_whitelist_partial_match():
    """Test that substring matching works for partial matches."""
    rule = WhitelistRule("Central")
    assert rule.matches("CNN News Central")
    assert rule.matches("Central Park")
    assert rule.matches("The Central Show")
    assert not rule.matches("CNN News")
