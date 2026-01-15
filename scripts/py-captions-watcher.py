#!/usr/bin/env python3
import asyncio
import os
import sys

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from py_captions_for_channels.watcher import main


if __name__ == "__main__":
    asyncio.run(main())
