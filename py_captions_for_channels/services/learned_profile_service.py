"""Service for managing learned encoding profiles from test suite results."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from ..models import LearnedProfile
from ..logging.structured_logger import get_logger

LOG = get_logger(__name__)


def compute_signature_hash(signature_data: Dict[str, Any]) -> str:
    """
    Compute deterministic hash from signature data.

    Args:
        signature_data: Dictionary with video characteristics

    Returns:
        SHA256 hash string (hex)
    """
    # Use sorted keys for deterministic hashing
    canonical = json.dumps(signature_data, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class LearnedProfileService:
    """
    CRUD operations for learned encoding profiles.

    Manages optimal ffmpeg configurations learned from test suite results,
    enabling automatic profile selection based on recording signatures.
    """

    def __init__(self, db: Session):
        """
        Initialize service with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def save_profile(
        self,
        signature_data: Dict[str, Any],
        profile_name: str,
        variant_name: str,
        performance_data: Optional[Dict[str, Any]] = None,
        ffmpeg_command: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> LearnedProfile:
        """
        Save or update a learned profile.

        Args:
            signature_data: Video characteristics (codec, resolution, fps, etc.)
            profile_name: Encoding profile name
            variant_name: Test suite variant name
            performance_data: Optional performance metrics
            ffmpeg_command: Optional ffmpeg command used
            notes: Optional user notes

        Returns:
            Created or updated LearnedProfile
        """
        signature_hash = compute_signature_hash(signature_data)

        # Check if profile exists
        existing = (
            self.db.query(LearnedProfile)
            .filter_by(signature_hash=signature_hash)
            .first()
        )

        if existing:
            # Update existing
            existing.profile_name = profile_name
            existing.variant_name = variant_name
            existing.signature_data = json.dumps(signature_data)
            if performance_data:
                existing.performance_data = json.dumps(performance_data)
            if ffmpeg_command:
                existing.ffmpeg_command = ffmpeg_command
            if notes:
                existing.notes = notes

            try:
                self.db.commit()
                self.db.refresh(existing)
                LOG.info(
                    f"Updated learned profile {signature_hash[:8]} "
                    f"-> {profile_name}/{variant_name}"
                )
                return existing
            except Exception as e:
                self.db.rollback()
                LOG.error(f"Failed to update learned profile: {e}")
                raise

        # Create new
        profile = LearnedProfile(
            signature_hash=signature_hash,
            signature_data=json.dumps(signature_data),
            profile_name=profile_name,
            variant_name=variant_name,
            performance_data=json.dumps(performance_data) if performance_data else None,
            ffmpeg_command=ffmpeg_command,
            notes=notes,
            times_used=0,
        )

        self.db.add(profile)
        try:
            self.db.commit()
            self.db.refresh(profile)
            LOG.info(
                f"Saved new learned profile {signature_hash[:8]} "
                f"-> {profile_name}/{variant_name}"
            )
            return profile
        except Exception as e:
            self.db.rollback()
            LOG.error(f"Failed to save learned profile: {e}")
            raise

    def find_by_signature(
        self, signature_data: Dict[str, Any]
    ) -> Optional[LearnedProfile]:
        """
        Find learned profile by source signature.

        Args:
            signature_data: Video characteristics to match

        Returns:
            LearnedProfile if found, None otherwise
        """
        signature_hash = compute_signature_hash(signature_data)

        try:
            profile = (
                self.db.query(LearnedProfile)
                .filter_by(signature_hash=signature_hash)
                .first()
            )

            if profile:
                # Update usage stats
                profile.times_used += 1
                profile.last_used_at = datetime.now(timezone.utc)
                try:
                    self.db.commit()
                except Exception:
                    # Don't fail lookup if stats update fails
                    try:
                        self.db.rollback()
                    except Exception:
                        pass

            return profile
        except Exception as e:
            LOG.warning(f"Error finding learned profile: {e}")
            try:
                self.db.rollback()
            except Exception:
                pass
            return None

    def get_all(self) -> List[LearnedProfile]:
        """
        Get all learned profiles.

        Returns:
            List of LearnedProfile objects
        """
        try:
            return (
                self.db.query(LearnedProfile)
                .order_by(LearnedProfile.created_at.desc())
                .all()
            )
        except Exception as e:
            LOG.error(f"Failed to get learned profiles: {e}")
            return []

    def get_by_id(self, profile_id: int) -> Optional[LearnedProfile]:
        """
        Get learned profile by ID.

        Args:
            profile_id: Profile ID

        Returns:
            LearnedProfile if found, None otherwise
        """
        try:
            return self.db.query(LearnedProfile).filter_by(id=profile_id).first()
        except Exception as e:
            LOG.warning(f"Error getting learned profile {profile_id}: {e}")
            return None

    def delete(self, profile_id: int) -> bool:
        """
        Delete learned profile.

        Args:
            profile_id: Profile ID to delete

        Returns:
            True if deleted, False if not found
        """
        profile = self.get_by_id(profile_id)
        if not profile:
            return False

        try:
            self.db.delete(profile)
            self.db.commit()
            LOG.info(f"Deleted learned profile {profile_id}")
            return True
        except Exception as e:
            self.db.rollback()
            LOG.error(f"Failed to delete learned profile {profile_id}: {e}")
            raise

    def get_profile_stats(self) -> Dict[str, Any]:
        """
        Get statistics about learned profiles.

        Returns:
            Dictionary with total count, most used, recent, etc.
        """
        try:
            total = self.db.query(LearnedProfile).count()

            most_used = (
                self.db.query(LearnedProfile)
                .order_by(LearnedProfile.times_used.desc())
                .first()
            )

            recently_used = (
                self.db.query(LearnedProfile)
                .filter(LearnedProfile.last_used_at.isnot(None))
                .order_by(LearnedProfile.last_used_at.desc())
                .first()
            )

            return {
                "total_profiles": total,
                "most_used": (
                    {
                        "profile_name": most_used.profile_name if most_used else None,
                        "times_used": most_used.times_used if most_used else 0,
                    }
                    if most_used
                    else None
                ),
                "recently_used": (
                    {
                        "profile_name": (
                            recently_used.profile_name if recently_used else None
                        ),
                        "last_used_at": (
                            recently_used.last_used_at.isoformat()
                            if recently_used and recently_used.last_used_at
                            else None
                        ),
                    }
                    if recently_used
                    else None
                ),
            }
        except Exception as e:
            LOG.error(f"Failed to get profile stats: {e}")
            return {"total_profiles": 0}
