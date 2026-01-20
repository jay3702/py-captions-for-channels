"""Whitelist filtering for recording processing.

Supports both simple show name matching and complex time/channel-based rules.
Show name matching supports both substring and regex patterns.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Pattern

LOG = logging.getLogger(__name__)


class WhitelistRule:
    """A single whitelist rule."""

    # Regex operators that indicate a pattern should be treated as regex
    REGEX_OPERATORS = r"[.*+?^${}()\[\]\\|]"

    def __init__(self, line: str):
        """Parse a whitelist rule from a line.

        Format:
            Simple: "Show Name" (substring match)
            Regex: "News.*Central" (regex pattern)
            Complex: "Show Name;DayOfWeek;Channel;Time"

        Examples:
            "News" - matches any recording containing "News"
            "^CNN News" - regex: matches titles starting with "CNN News"
            "News.*Central" - regex: matches "News" followed by "Central"
            "Dateline;Friday;11.1,113;21:00" - Dateline on Friday at 21:00
        """
        parts = line.strip().split(";")
        self.show_name = parts[0].strip()
        self.day_of_week = parts[1].strip() if len(parts) > 1 else None
        self.channels = (
            [c.strip() for c in parts[2].split(",")] if len(parts) > 2 else None
        )
        self.time = parts[3].strip() if len(parts) > 3 else None

        # Determine if show_name is regex or substring
        self.pattern: Optional[Pattern] = None
        self.is_regex = bool(re.search(self.REGEX_OPERATORS, self.show_name))

        if self.is_regex:
            LOG.debug("Whitelist rule '%s' detected as regex", self.show_name)
            try:
                # Compile as regex (case-insensitive)
                self.pattern = re.compile(self.show_name, re.IGNORECASE)
                LOG.debug("Whitelist rule '%s' using regex pattern", self.show_name)
            except re.error as e:
                LOG.warning(
                    "Invalid regex pattern '%s': %s. Treating as substring.",
                    self.show_name,
                    e,
                )
                self.is_regex = False
                self.pattern = None

    def matches(self, title: str, recording_time: Optional[datetime] = None) -> bool:
        """Check if a recording matches this whitelist rule.

        Args:
            title: Recording title
            recording_time: When the recording was made (optional)

        Returns:
            True if the recording matches this rule
        """
        # Check title match (regex or substring, case-insensitive)
        if self.is_regex and self.pattern:
            # Use compiled regex pattern
            if not self.pattern.search(title):
                return False
        else:
            # Use substring match (case-insensitive)
            if self.show_name.lower() not in title.lower():
                return False

        # If simple rule (no time constraints), we have a match
        if self.day_of_week is None:
            return True

        # Complex rule - check day/time constraints
        if recording_time is None:
            # Can't validate time constraints without timestamp
            LOG.warning("Complex whitelist rule requires timestamp: %s", self.show_name)
            return True  # Allow it anyway

        # Check day of week
        if self.day_of_week:
            day_name = recording_time.strftime("%A")
            if day_name != self.day_of_week:
                return False

        # Check time (if specified)
        if self.time:
            # Format: "21:00" (HH:MM)
            rule_hour, rule_min = map(int, self.time.split(":"))
            if recording_time.hour != rule_hour or recording_time.minute != rule_min:
                return False

        return True


class Whitelist:
    """Manages whitelist rules for recording filtering."""

    def __init__(self, whitelist_file: Optional[str] = None):
        """Initialize whitelist from file.

        Args:
            whitelist_file: Path to whitelist file (one rule per line)
        """
        self.rules: List[WhitelistRule] = []
        self.enabled = False

        if whitelist_file and Path(whitelist_file).exists():
            self.load(whitelist_file)

    def load(self, filepath: str):
        """Load whitelist rules from file."""
        path = Path(filepath)
        if not path.exists():
            LOG.warning("Whitelist file not found: %s", filepath)
            return

        LOG.info("Loading whitelist from: %s", filepath)
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        rule = WhitelistRule(line)
                        self.rules.append(rule)
                    except Exception as e:
                        LOG.warning("Invalid whitelist rule '%s': %s", line, e)

        self.enabled = len(self.rules) > 0
        LOG.info("Loaded %d whitelist rules", len(self.rules))

    def is_allowed(self, title: str, recording_time: Optional[datetime] = None) -> bool:
        """Check if a recording is allowed by the whitelist.

        Args:
            title: Recording title
            recording_time: When the recording was made

        Returns:
            True if recording should be processed
        """
        # If whitelist is disabled, allow everything
        if not self.enabled:
            return True

        # Check if any rule matches
        for rule in self.rules:
            if rule.matches(title, recording_time):
                LOG.info(
                    "Recording '%s' matches whitelist rule: %s", title, rule.show_name
                )
                return True

        LOG.info("Recording '%s' not in whitelist, skipping", title)
        return False
