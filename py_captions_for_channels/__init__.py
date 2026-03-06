"""py-captions-for-channels
A modular, event-driven captioning pipeline for Channels DVR.
"""

from .version import VERSION as __version__  # noqa: F401

__all__ = ["state", "watcher", "mock_source", "channelwatch_source", "parser"]
