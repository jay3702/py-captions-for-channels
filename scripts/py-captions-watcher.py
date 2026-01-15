#!/usr/bin/env python3
import sys
from pathlib import Path


def run() -> None:
    """Run the watcher from the project sources.

    This inserts the repository root on sys.path so the package can be
    imported when the script is executed directly (CI does not install the
    package). The import of the project module is done inside the function to
    avoid module-level imports after side-effecting code (flake8 E402).
    """
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Import the watcher from the project and run its async main
    import asyncio

    from py_captions_for_channels.watcher import main

    asyncio.run(main())


if __name__ == "__main__":
    run()
