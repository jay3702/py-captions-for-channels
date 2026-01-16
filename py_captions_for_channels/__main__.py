"""
Main entry point for py-captions-for-channels.

This allows running the package as a module:
    python -m py_captions_for_channels
"""

import asyncio
import logging
import sys

from .watcher import main

# Configure logging with explicit flushing
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)

LOG = logging.getLogger(__name__)

if __name__ == "__main__":
    LOG.info("=" * 70)
    LOG.info("py-captions-for-channels starting...")
    LOG.info("=" * 70)
    sys.stdout.flush()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOG.info("Shutting down...")
    except Exception as e:
        LOG.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
