"""Service for managing polling cache in database."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from ..models import PollingCache
from ..logging.structured_logger import get_logger

LOG = get_logger(__name__)


class PollingCacheService:
    """CRUD operations for polling cache.

    Tracks which recordings have been yielded to prevent duplicate
    processing across restarts.
    """

    def __init__(self, db: Session):
        """Initialize service with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def add_yielded(self, rec_id: str, yielded_at: Optional[datetime] = None) -> bool:
        """Add a recording to the yielded cache.

        Args:
            rec_id: Recording identifier
            yielded_at: When recording was yielded (defaults to now)

        Returns:
            True if added, False if already exists
        """
        if yielded_at is None:
            yielded_at = datetime.now(timezone.utc)

        # Check if already exists
        existing = self.db.query(PollingCache).filter_by(rec_id=rec_id).first()
        if existing:
            # Update timestamp
            existing.yielded_at = yielded_at
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return False

        # Add new entry
        cache_item = PollingCache(rec_id=rec_id, yielded_at=yielded_at)
        self.db.add(cache_item)
        try:
            self.db.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                pass
            else:
                try:
                    self.db.rollback()
                except Exception:
                    pass  # Rollback itself may fail if no transaction
                raise
        return True

    def has_yielded(self, rec_id: str) -> bool:
        """Check if recording has been yielded.

        Args:
            rec_id: Recording identifier

        Returns:
            True if recording has been yielded
        """
        try:
            return (
                self.db.query(PollingCache).filter_by(rec_id=rec_id).first() is not None
            )
        except Exception as e:
            # Handle session errors by rolling back and returning False
            try:
                self.db.rollback()
            except Exception:
                pass  # Rollback itself may fail
            LOG.warning("Error checking polling cache for %s: %s", rec_id, e)
            return False  # Assume not yielded on error to allow retry

    def get_yielded_time(self, rec_id: str) -> Optional[datetime]:
        """Get when a recording was yielded.

        Args:
            rec_id: Recording identifier

        Returns:
            Datetime when yielded, or None if not found
        """
        try:
            cache_item = self.db.query(PollingCache).filter_by(rec_id=rec_id).first()
            return cache_item.yielded_at if cache_item else None
        except Exception as e:
            # Handle session errors by rolling back and returning None
            try:
                self.db.rollback()
            except Exception:
                pass  # Rollback itself may fail
            LOG.warning("Error getting yielded time for %s: %s", rec_id, e)
            return None

    def cleanup_old(self, max_age_hours: int = 24) -> int:
        """Remove old cache entries.

        Args:
            max_age_hours: Maximum age in hours to keep

        Returns:
            Number of entries removed
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            result = (
                self.db.query(PollingCache)
                .filter(PollingCache.yielded_at < cutoff)
                .delete()
            )
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return result
        except Exception as e:
            # Handle session errors
            try:
                self.db.rollback()
            except Exception:
                pass
            LOG.warning("Error cleaning up old polling cache entries: %s", e)
            return 0

    def get_all(self) -> dict:
        """Get all cache entries as dict (for debugging/migration).

        Returns:
            Dict mapping rec_id to yielded_at datetime
        """
        try:
            items = self.db.query(PollingCache).all()
            return {item.rec_id: item.yielded_at for item in items}
        except Exception as e:
            # Handle session errors
            try:
                self.db.rollback()
            except Exception:
                pass
            LOG.warning("Error getting all polling cache entries: %s", e)
            return {}

    def clear_all(self) -> int:
        """Clear all cache entries (for testing).

        Returns:
            Number of entries removed
        """
        try:
            result = self.db.query(PollingCache).delete()
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return result
        except Exception as e:
            # Handle session errors
            try:
                self.db.rollback()
            except Exception:
                pass
            LOG.warning("Error clearing polling cache: %s", e)
            return 0
