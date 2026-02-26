"""Service layer for quarantine operations."""

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..models import QuarantineItem

LOG = logging.getLogger(__name__)


class QuarantineService:
    """Service for managing quarantined orphaned files."""

    def __init__(self, db: Session, quarantine_dir: str):
        self.db = db
        self.quarantine_dir = Path(quarantine_dir)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    def is_already_quarantined(self, original_path: str) -> bool:
        """Check if a file is already quarantined (active record exists).

        Args:
            original_path: Original file path to check

        Returns:
            True if an active quarantine record exists for this path
        """
        existing = (
            self.db.query(QuarantineItem)
            .filter(
                QuarantineItem.original_path == original_path,
                QuarantineItem.status == "quarantined",
            )
            .first()
        )
        return existing is not None

    def quarantine_file(
        self,
        original_path: str,
        file_type: str,
        recording_path: Optional[str] = None,
        reason: str = "orphaned_by_pipeline",
        expiration_days: int = 30,
        defer_commit: bool = False,
    ) -> Optional[QuarantineItem]:
        """Move a file to quarantine instead of deleting it.

        Skips files that don't exist or are already quarantined.

        Args:
            original_path: Original file path
            file_type: Type of file ('orig', 'srt')
            recording_path: Associated recording path
            reason: Reason for quarantine
            expiration_days: Days until auto-deletion

        Returns:
            Created QuarantineItem, or None if skipped
        """
        original_path_obj = Path(original_path)

        # Skip if file doesn't exist (already moved by concurrent scan, etc.)
        if not original_path_obj.exists():
            LOG.debug(
                "Skipping quarantine of %s: file does not exist (already moved?)",
                original_path,
            )
            return None

        # Skip if already quarantined (prevents duplicate DB records)
        if self.is_already_quarantined(original_path):
            LOG.debug(
                "Skipping quarantine of %s: already quarantined",
                original_path,
            )
            return None

        # Generate quarantine path with timestamp + microseconds to avoid collisions
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{original_path_obj.name}"
        quarantine_path = self.quarantine_dir / filename

        # Ensure uniqueness if file already exists
        counter = 1
        while quarantine_path.exists():
            filename = f"{timestamp}_{counter}_{original_path_obj.name}"
            quarantine_path = self.quarantine_dir / filename
            counter += 1

        # Get file size before moving
        file_size = original_path_obj.stat().st_size

        # Move the file first, then create DB record (avoids ghost records)
        # Try os.rename first (instant on same filesystem), fall back to
        # shutil.move (cross-device copy) if that fails.
        try:
            os.rename(str(original_path), str(quarantine_path))
        except OSError:
            shutil.move(str(original_path), str(quarantine_path))

        # Create database record after successful move
        expires_at = datetime.now(timezone.utc) + timedelta(days=expiration_days)
        item = QuarantineItem(
            original_path=str(original_path),
            quarantine_path=str(quarantine_path),
            file_type=file_type,
            recording_path=recording_path,
            file_size_bytes=file_size,
            reason=reason,
            status="quarantined",
            expires_at=expires_at,
        )
        self.db.add(item)
        if not defer_commit:
            self.db.commit()
            self.db.refresh(item)

        return item

    def restore_file(self, item_id: int) -> bool:
        """Restore a quarantined file to its original location.

        Args:
            item_id: QuarantineItem ID

        Returns:
            True if restored successfully, False otherwise
        """
        item = (
            self.db.query(QuarantineItem).filter(QuarantineItem.id == item_id).first()
        )
        if not item or item.status != "quarantined":
            return False

        quarantine_path = Path(item.quarantine_path)
        original_path = Path(item.original_path)

        # Check if quarantined file exists
        if not quarantine_path.exists():
            return False

        # Check if original location is available
        if original_path.exists():
            return False  # Can't restore, original location occupied

        # Create parent directory if needed
        original_path.parent.mkdir(parents=True, exist_ok=True)

        # Move file back — try rename first (instant on same FS)
        try:
            os.rename(str(quarantine_path), str(original_path))
        except OSError:
            shutil.move(str(quarantine_path), str(original_path))

        # Update database
        item.status = "restored"
        item.restored_at = datetime.now(timezone.utc)
        self.db.commit()

        return True

    def delete_file(self, item_id: int) -> bool:
        """Permanently delete a quarantined file.

        Args:
            item_id: QuarantineItem ID

        Returns:
            True if deleted successfully, False otherwise
        """
        item = (
            self.db.query(QuarantineItem).filter(QuarantineItem.id == item_id).first()
        )
        if not item or item.status != "quarantined":
            return False

        quarantine_path = Path(item.quarantine_path)

        # Delete the file if it exists
        if quarantine_path.exists():
            os.remove(quarantine_path)

        # Update database
        item.status = "deleted"
        item.deleted_at = datetime.now(timezone.utc)
        self.db.commit()

        return True

    def get_quarantined_files(
        self, include_expired: bool = True
    ) -> List[QuarantineItem]:
        """Get all quarantined files.

        Args:
            include_expired: Include expired items

        Returns:
            List of quarantined items
        """
        query = self.db.query(QuarantineItem).filter(
            QuarantineItem.status == "quarantined"
        )

        if not include_expired:
            query = query.filter(QuarantineItem.expires_at > datetime.utcnow())

        return query.order_by(QuarantineItem.original_path.asc()).all()

    def get_expired_files(self) -> List[QuarantineItem]:
        """Get all quarantined files past their expiration date.

        Returns:
            List of expired quarantined items
        """
        return (
            self.db.query(QuarantineItem)
            .filter(
                QuarantineItem.status == "quarantined",
                QuarantineItem.expires_at <= datetime.utcnow(),
            )
            .order_by(QuarantineItem.created_at.desc())
            .all()
        )

    def delete_expired_files(self) -> int:
        """Delete all expired quarantined files.

        Returns:
            Number of files deleted
        """
        expired = self.get_expired_files()
        count = 0

        for item in expired:
            if self.delete_file(item.id):
                count += 1

        return count

    def delete_files_batch(
        self,
        item_ids: List[int],
        batch_size: int = 50,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        """Delete multiple quarantined files with batched DB commits.

        Yields progress tuples as (current, total, deleted, failed, cancelled).

        Args:
            item_ids: List of QuarantineItem IDs to delete
            batch_size: Number of items to process before committing
            cancel_check: Called between items; return True to cancel

        Yields:
            Tuples of (current, total, deleted, failed, cancelled)
        """
        deleted = 0
        failed = 0
        cancelled = False
        total = len(item_ids)
        now = datetime.now(timezone.utc)

        # Pre-fetch all items in one query
        items = (
            self.db.query(QuarantineItem).filter(QuarantineItem.id.in_(item_ids)).all()
        )
        item_map = {item.id: item for item in items}

        for i, item_id in enumerate(item_ids):
            # Check cancellation
            if cancel_check and cancel_check():
                cancelled = True
                LOG.info(
                    "Delete batch cancelled at %d/%d (deleted=%d)",
                    i,
                    total,
                    deleted,
                )
                break

            item = item_map.get(item_id)
            if not item or item.status != "quarantined":
                failed += 1
                continue

            try:
                quarantine_path = Path(item.quarantine_path)
                if quarantine_path.exists():
                    os.remove(quarantine_path)

                item.status = "deleted"
                item.deleted_at = now
                deleted += 1

            except Exception as e:
                failed += 1
                LOG.error("Failed to delete item %d: %s", item_id, e)

            # Batch commit
            if (i + 1) % batch_size == 0:
                self.db.commit()

            # Yield progress periodically or on last item
            progress_interval = max(1, min(50, total // 20))
            if (i + 1) % progress_interval == 0 or i == total - 1:
                yield (i + 1, total, deleted, failed, cancelled)

        # Final commit for remaining items
        self.db.commit()

        # Yield final state
        yield (total if not cancelled else i, total, deleted, failed, cancelled)

    def deduplicate(self) -> dict:
        """Remove duplicate quarantine entries (keep newest for each original_path).

        Duplicates can arise from race conditions in concurrent scans.

        Returns:
            Dict with duplicates_removed count and details
        """
        # Find original_paths with more than one active quarantine record
        dupes = (
            self.db.query(
                QuarantineItem.original_path,
                func.count(QuarantineItem.id).label("cnt"),
            )
            .filter(QuarantineItem.status == "quarantined")
            .group_by(QuarantineItem.original_path)
            .having(func.count(QuarantineItem.id) > 1)
            .all()
        )

        removed = 0
        details = []

        for original_path, count in dupes:
            # Get all records for this path, newest first
            records = (
                self.db.query(QuarantineItem)
                .filter(
                    QuarantineItem.original_path == original_path,
                    QuarantineItem.status == "quarantined",
                )
                .order_by(QuarantineItem.created_at.desc())
                .all()
            )

            # Keep the first (newest) record, mark the rest as duplicates
            for dup in records[1:]:
                # If the quarantine file doesn't exist, just mark as deleted
                quarantine_path = Path(dup.quarantine_path)
                if quarantine_path.exists():
                    try:
                        os.remove(quarantine_path)
                    except OSError as e:
                        LOG.warning(
                            "Could not remove duplicate quarantine file %s: %s",
                            quarantine_path,
                            e,
                        )

                dup.status = "deleted"
                dup.deleted_at = datetime.now(timezone.utc)
                removed += 1
                details.append(f"Removed duplicate #{dup.id} for {original_path}")

        if removed > 0:
            self.db.commit()
            LOG.info("Deduplicated quarantine: removed %d duplicate entries", removed)

        return {
            "duplicates_removed": removed,
            "duplicate_paths": len(dupes),
            "details": details,
        }

    def get_quarantine_stats(self) -> dict:
        """Get statistics about quarantined files.

        Returns:
            Dictionary with stats
        """
        quarantined = self.get_quarantined_files()
        expired = self.get_expired_files()

        total_size = sum(
            item.file_size_bytes for item in quarantined if item.file_size_bytes
        )

        return {
            "total_quarantined": len(quarantined),
            "total_expired": len(expired),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }
