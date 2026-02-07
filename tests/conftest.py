import os
import sys
from pathlib import Path
import pytest

# Ensure repository root is on sys.path so tests can import the package
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolate_database(tmp_path):
    """Ensure each test uses an isolated database."""
    # Set unique DB_PATH for this test
    db_path = tmp_path / "test.db"
    os.environ["DB_PATH"] = str(db_path)

    # Force reload of database module to pick up new DB_PATH
    import py_captions_for_channels.database as db_module

    # Update the module-level variables
    db_module.DB_PATH = str(db_path)
    db_module.DB_URL = f"sqlite:///{db_path}"

    # Recreate engine and session with new path
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    db_module.engine = create_engine(
        db_module.DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_module.engine
    )

    # Initialize fresh database
    db_module.init_db()

    yield

    # Cleanup
    db_module.engine.dispose()
