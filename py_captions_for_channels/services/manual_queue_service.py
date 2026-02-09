"""Service layer for manual process queue operations."""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from ..models import ManualQueueItem


class ManualQueueService:
    """Service for managing manual process queue in database."""

    def __init__(self, db: Session):
        self.db = db

    def add_to_queue(
        self,
        path: str,
        skip_caption_generation: bool = False,
        log_verbosity: str = "NORMAL",
    ) -> ManualQueueItem:
        """Add a path to the manual process queue.

        Args:
            path: File path to process
            skip_caption_generation: Whether to skip caption generation
            log_verbosity: Log verbosity level

        Returns:
            Created ManualQueueItem
        """
        # Check if already exists
        existing = (
            self.db.query(ManualQueueItem).filter(ManualQueueItem.path == path).first()
        )

        if existing:
            # Update settings if already in queue
            existing.skip_caption_generation = skip_caption_generation
            existing.log_verbosity = log_verbosity
            existing.updated_at = datetime.now(timezone.utc)
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    self.db.rollback()
                    raise
            self.db.refresh(existing)
            return existing

        # Create new queue item
        item = ManualQueueItem(
            path=path,
            skip_caption_generation=skip_caption_generation,
            log_verbosity=log_verbosity,
        )
        self.db.add(item)
        try:
            self.db.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                pass
            else:
                self.db.rollback()
                raise
        self.db.refresh(item)
        return item

    def get_queue_item(self, path: str) -> Optional[ManualQueueItem]:
        """Get a specific queue item by path.

        Args:
            path: File path to look up

        Returns:
            ManualQueueItem if found, None otherwise
        """
        return (
            self.db.query(ManualQueueItem).filter(ManualQueueItem.path == path).first()
        )

    def get_queue(self) -> List[ManualQueueItem]:
        """Get all items in the manual process queue.

        Returns:
            List of ManualQueueItem objects
        """
        return self.db.query(ManualQueueItem).order_by(ManualQueueItem.id).all()

    def get_queue_paths(self) -> List[str]:
        """Get list of paths in the manual process queue.

        Returns:
            List of file paths
        """
        items = self.get_queue()
        return [item.path for item in items]

    def has_path(self, path: str) -> bool:
        """Check if a path is in the queue.

        Args:
            path: File path to check

        Returns:
            True if path is in queue, False otherwise
        """
        count = (
            self.db.query(ManualQueueItem).filter(ManualQueueItem.path == path).count()
        )
        return count > 0

    def remove_from_queue(self, path: str) -> bool:
        """Remove a path from the manual process queue.

        Args:
            path: File path to remove

        Returns:
            True if removed, False if not found
        """
        item = self.get_queue_item(path)
        if item:
            self.db.delete(item)
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    self.db.rollback()
                    raise
            return True
        return False

    def clear_queue(self) -> int:
        """Remove all items from the queue.

        Returns:
            Number of items removed
        """
        count = self.db.query(ManualQueueItem).count()
        self.db.query(ManualQueueItem).delete()
        try:
            self.db.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                pass
            else:
                self.db.rollback()
                raise
        return count

    def to_dict(self, item: ManualQueueItem) -> dict:
        """Convert ManualQueueItem to dict for API compatibility.

        Args:
            item: ManualQueueItem object

        Returns:
            Dict representation
        """
        return {
            "path": item.path,
            "skip_caption_generation": item.skip_caption_generation,
            "log_verbosity": item.log_verbosity,
            "added_at": item.added_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
