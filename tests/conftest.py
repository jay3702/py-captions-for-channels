import os
import sys
import tempfile
from pathlib import Path

# Set up temp database for testing BEFORE any imports
temp_dir = tempfile.mkdtemp()
os.environ["DB_PATH"] = str(Path(temp_dir) / "test.db")

# Ensure repository root is on sys.path so tests can import the package
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
