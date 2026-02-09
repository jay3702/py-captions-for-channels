"""Service layer for progress tracking operations."""

import json
from datetime import datetime, timezone
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from ..models import Progress


class ProgressService:
    """Service for managing process progress in database."""

    def __init__(self, db: Session):
        self.db = db

    def update_progress(
        self,
        job_id: str,
        process_type: str,
        percent: float,
        message: str = "",
        details: dict = None,
    ) -> Progress:
        """Update or create progress entry for a job.

        Args:
            job_id: Job identifier
            process_type: Type of process ("whisper" or "ffmpeg")
            percent: Progress percentage (0-100)
            message: Optional progress message
            details: Optional additional details dict

        Returns:
            Updated or created Progress object or None if database error
        """
        try:
            # Clamp percent to 0-100 range
            percent = min(100.0, max(0.0, percent))

            # Check if progress entry exists
            progress = self.db.query(Progress).filter(Progress.job_id == job_id).first()

            # Serialize details to JSON if present
            details_json = json.dumps(details) if details else None
            now = datetime.now(timezone.utc)

            if progress:
                # Update existing
                progress.process_type = process_type
                progress.percent = percent
                progress.message = message
                progress.progress_metadata = details_json
                progress.updated_at = now
            else:
                # Create new
                progress = Progress(
                    job_id=job_id,
                    process_type=process_type,
                    percent=percent,
                    message=message,
                    progress_metadata=details_json,
                    updated_at=now,
                )
                self.db.add(progress)

            try:
                self.db.commit()
            except Exception as e:
                # Handle "no transaction is active" errors from concurrent access
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    # Transaction already handled by concurrent process
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise

            # Only refresh if commit succeeded
            try:
                self.db.refresh(progress)
            except Exception:
                pass  # Refresh may fail if commit didn't succeed

            return progress
        except Exception:
            # Database operations can fail in various states, don't crash the job
            # Return None to indicate failure
            return None

    def get_progress(self, job_id: str) -> Optional[Progress]:
        """Get progress for a specific job.

        Args:
            job_id: Job identifier

        Returns:
            Progress object or None if not found
        """
        return self.db.query(Progress).filter(Progress.job_id == job_id).first()

    def get_all_progress(self) -> List[Progress]:
        """Get all current progress entries.

        Returns:
            List of Progress objects
        """
        return self.db.query(Progress).all()

    def clear_progress(self, job_id: str) -> bool:
        """Remove progress data for a job.

        Args:
            job_id: Job identifier to remove

        Returns:
            True if removed, False if not found
        """
        try:
            progress = self.get_progress(job_id)
            if progress:
                self.db.delete(progress)
                try:
                    self.db.commit()
                except Exception as e:
                    error_msg = str(e).lower()
                    if "no transaction" in error_msg:
                        # Transaction already handled by concurrent process
                        pass
                    else:
                        try:
                            self.db.rollback()
                        except Exception:
                            pass  # Rollback itself may fail if no transaction
                        raise
                return True
            return False
        except Exception:
            # Database queries can fail in various states, don't crash the job
            return False

    def clear_all_progress(self) -> int:
        """Remove all progress entries.

        Returns:
            Number of entries removed
        """
        count = self.db.query(Progress).count()
        self.db.query(Progress).delete()
        try:
            self.db.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                # Transaction already handled by concurrent process
                pass
            else:
                try:
                    self.db.rollback()
                except Exception:
                    pass  # Rollback itself may fail if no transaction
                raise
        return count

    def to_dict(self, progress: Progress) -> dict:
        """Convert Progress to dict for API compatibility.

        Args:
            progress: Progress object

        Returns:
            Dict representation matching old JSON format
        """
        # Deserialize metadata from JSON
        metadata = {}
        if progress.progress_metadata:
            try:
                metadata = json.loads(progress.progress_metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        return {
            "process_type": progress.process_type,
            "percent": progress.percent,
            "message": progress.message,
            "details": metadata,
            "updated_at": progress.updated_at.isoformat(),
        }

    def get_all_progress_dict(self) -> Dict[str, dict]:
        """Get all progress as dict mapping job_id to progress info.

        Returns:
            Dict mapping job_id to progress dict (matches old JSON format)
        """
        all_progress = self.get_all_progress()
        return {prog.job_id: self.to_dict(prog) for prog in all_progress}
