"""Service for managing service heartbeats in database."""

from datetime import datetime, timezone
from typing import Optional, Dict
from sqlalchemy.orm import Session
from ..models import Heartbeat


class HeartbeatService:
    """CRUD operations for service heartbeats.

    Tracks health and liveness of background services.
    """

    def __init__(self, db: Session):
        """Initialize service with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def beat(
        self,
        service_name: str,
        status: str = "alive",
        beat_time: Optional[datetime] = None,
    ) -> None:
        """Record a heartbeat for a service.

        Args:
            service_name: Service identifier ('polling', 'manual', 'web')
            status: Service status ('alive', 'stale', 'dead')
            beat_time: Heartbeat timestamp (defaults to now)
        """
        if beat_time is None:
            beat_time = datetime.now(timezone.utc)

        # Check if heartbeat exists
        heartbeat = (
            self.db.query(Heartbeat).filter_by(service_name=service_name).first()
        )

        if heartbeat:
            # Update existing heartbeat
            heartbeat.last_beat = beat_time
            heartbeat.status = status
        else:
            # Create new heartbeat
            heartbeat = Heartbeat(
                service_name=service_name, last_beat=beat_time, status=status
            )
            self.db.add(heartbeat)

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

    def get_heartbeat(self, service_name: str) -> Optional[Dict]:
        """Get heartbeat for a service.

        Args:
            service_name: Service identifier

        Returns:
            Dict with last_beat, status, age_seconds, or None if not found
        """
        heartbeat = (
            self.db.query(Heartbeat).filter_by(service_name=service_name).first()
        )

        if not heartbeat:
            return None

        age_seconds = (datetime.now(timezone.utc) - heartbeat.last_beat).total_seconds()

        return {
            "service_name": heartbeat.service_name,
            "last_beat": heartbeat.last_beat.isoformat(),
            "status": heartbeat.status,
            "age_seconds": age_seconds,
            "alive": age_seconds < 30,  # Alive if < 30 seconds old
        }

    def get_all_heartbeats(self) -> Dict[str, Dict]:
        """Get all service heartbeats.

        Returns:
            Dict mapping service_name to heartbeat dict
        """
        heartbeats = self.db.query(Heartbeat).all()
        now = datetime.now(timezone.utc)

        result = {}
        for hb in heartbeats:
            age_seconds = (now - hb.last_beat).total_seconds()
            result[hb.service_name] = {
                "service_name": hb.service_name,
                "last_beat": hb.last_beat.isoformat(),
                "status": hb.status,
                "age_seconds": age_seconds,
                "alive": age_seconds < 30,
            }

        return result

    def check_stale(self, service_name: str, timeout_seconds: int = 30) -> bool:
        """Check if a service heartbeat is stale.

        Args:
            service_name: Service identifier
            timeout_seconds: Timeout before considering stale

        Returns:
            True if heartbeat is stale or missing
        """
        heartbeat = (
            self.db.query(Heartbeat).filter_by(service_name=service_name).first()
        )

        if not heartbeat:
            return True

        age_seconds = (datetime.now(timezone.utc) - heartbeat.last_beat).total_seconds()
        return age_seconds > timeout_seconds

    def clear_heartbeat(self, service_name: str) -> bool:
        """Remove a heartbeat entry.

        Args:
            service_name: Service identifier

        Returns:
            True if removed, False if not found
        """
        result = self.db.query(Heartbeat).filter_by(service_name=service_name).delete()
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
        return result > 0

    def clear_all(self) -> int:
        """Clear all heartbeats (for testing).

        Returns:
            Number of entries removed
        """
        result = self.db.query(Heartbeat).delete()
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
