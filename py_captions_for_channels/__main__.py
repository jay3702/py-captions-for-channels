"""
Main entry point for py-captions-for-channels.

This allows running the package as a module:
    python -m py_captions_for_channels
"""

import asyncio
import logging

from .watcher import main

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    asyncio.run(main())
