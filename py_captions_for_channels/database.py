"""Database connection and session management."""

import os
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.pool import NullPool

# Database file location
DB_PATH = os.getenv("DB_PATH", "/app/data/py_captions.db")
DB_URL = f"sqlite:///{DB_PATH}"

# Create engine with NullPool for SQLite
# NullPool creates a new connection for each session, avoiding
# "another row available" errors from shared connections
# check_same_thread=False is safe because each session gets its own connection
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    poolclass=NullPool,  # No pooling - each session gets its own connection
    echo=False,  # Set to True for SQL query logging
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database sessions.

    Usage in FastAPI:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception as e:
            # Ignore "cannot rollback - no transaction is active" errors during cleanup
            error_msg = str(e).lower()
            if "cannot rollback" not in error_msg:
                raise


def init_db():
    """Initialize database tables.

    Creates all tables defined in models if they don't exist.
    Should be called on application startup.
    """
    # Import all models here to register them with Base
    from . import models  # noqa: F401

    # Ensure data directory exists
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Create tables
    Base.metadata.create_all(bind=engine)

    # Apply schema migrations for existing databases
    _apply_migrations()


def _apply_migrations():
    """Apply schema migrations to existing database."""
    import logging
    from sqlalchemy import inspect, text

    LOG = logging.getLogger(__name__)

    try:
        inspector = inspect(engine)

        # Migration: Add job_number column to executions table
        if "executions" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("executions")]
            if "job_number" not in columns:
                LOG.info("Adding job_number column to executions table")
                with engine.connect() as conn:
                    conn.execute(
                        text("ALTER TABLE executions ADD COLUMN job_number INTEGER")
                    )
                    conn.commit()
                LOG.info("Migration complete: job_number column added")

    except Exception as e:
        LOG.warning(f"Error applying migrations: {e}")
        # Don't fail startup if migration fails - column might already exist
