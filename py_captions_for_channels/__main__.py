"""
Main entry point for py-captions-for-channels.

This allows running the package as a module:
    python -m py_captions_for_channels
"""

import asyncio

from .logging_config import configure_logging
from .config import LOG_VERBOSITY
from .watcher import main

# Configure logging with job markers and verbosity support
configure_logging(verbosity=LOG_VERBOSITY)

if __name__ == "__main__":
    asyncio.run(main())
