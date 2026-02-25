"""Service layer for quarantine operations."""

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session
from ..models import QuarantineItem


class QuarantineService:
    """Service for managing quarantined orphaned files."""

    def __init__(self, db: Session, quarantine_dir: str):
        self.db = db
        self.quarantine_dir = Path(quarantine_dir)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    def quarantine_file(
        self,
        original_path: str,
        file_type: str,
        recording_path: Optional[str] = None,
        reason: str = "orphaned_by_pipeline",
        expiration_days: int = 30,
    ) -> QuarantineItem:
        """Move a file to quarantine instead of deleting it.

        Args:
            original_path: Original file path
            file_type: Type of file ('orig', 'srt')
            recording_path: Associated recording path
            reason: Reason for quarantine
            expiration_days: Days until auto-deletion

        Returns:
            Created QuarantineItem
        """
        original_path_obj = Path(original_path)

        # Generate quarantine path with timestamp to avoid collisions
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{original_path_obj.name}"
        quarantine_path = self.quarantine_dir / filename

        # Get file size
        file_size = None
        if original_path_obj.exists():
            file_size = original_path_obj.stat().st_size

        # Create database record first
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
        self.db.commit()
        self.db.refresh(item)

        # Move the file if it exists
        if original_path_obj.exists():
            shutil.move(str(original_path), str(quarantine_path))

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

        # Move file back
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

        return query.order_by(QuarantineItem.created_at.desc()).all()

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
