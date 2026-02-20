"""SQLAlchemy database models for persistence layer."""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Float,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from .database import Base


class Setting(Base):
    """Application settings storage.

    Replaces: .env file, settings.json
    Key-value store with type preservation.
    """

    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    # Type: 'string', 'bool', 'int', 'float'
    value_type = Column(String(20), nullable=False)
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self):
        return (
            f"<Setting(key='{self.key}', "
            f"value='{self.value}', type='{self.value_type}')>"
        )


class Execution(Base):
    """Pipeline execution tracking.

    Replaces: execution_tracker.py JSON storage
    Tracks entire lifecycle of processing jobs.
    """

    __tablename__ = "executions"
    __table_args__ = (
        Index("idx_executions_status", "status"),
        Index("idx_executions_path", "path"),
        Index("idx_executions_started_at", "started_at"),
        Index("idx_executions_job_sequence", "job_sequence"),
    )

    id = Column(String(200), primary_key=True)  # job_id
    title = Column(String(500), nullable=False)
    path = Column(String(1000), nullable=True)
    status = Column(
        String(50), nullable=False
    )  # discovered, pending, running, completed, failed, cancelled
    kind = Column(String(50), nullable=True)  # manual_process, polling, webhook
    job_number = Column(Integer, nullable=True)  # Sequential job number (resets daily)
    job_sequence = Column(Integer, nullable=True)  # Global autoincrement sequence
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    success = Column(Boolean, nullable=True)
    error_message = Column(Text, nullable=True)

    # Statistics
    elapsed_seconds = Column(Float, nullable=True)
    input_size_bytes = Column(Integer, nullable=True)
    output_size_bytes = Column(Integer, nullable=True)

    # Cancellation support
    cancel_requested = Column(Boolean, default=False)

    # Relationships
    steps = relationship(
        "ExecutionStep", back_populates="execution", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<Execution(id='{self.id}', status='{self.status}', path='{self.path}')>"
        )


class JobSequence(Base):
    """Global autoincrement sequence for executions."""

    __tablename__ = "job_sequence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self):
        return f"<JobSequence(id={self.id})>"


class ExecutionStep(Base):
    """Individual steps within a pipeline execution.

    New feature: Enables smart recovery after interruptions.
    Tracks: temp copy creation, SRT generation, ffmpeg processing, deployment
    """

    __tablename__ = "execution_steps"
    __table_args__ = (Index("idx_steps_execution_id", "execution_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(200), ForeignKey("executions.id"), nullable=False)

    step_name = Column(
        String(100), nullable=False
    )  # 'wait_stable', 'create_temp', 'generate_srt', 'ffmpeg', 'deploy'
    status = Column(
        String(50), nullable=False
    )  # pending, running, completed, failed, skipped
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Step-specific data
    input_path = Column(String(1000), nullable=True)
    output_path = Column(String(1000), nullable=True)
    step_metadata = Column(Text, nullable=True)  # JSON for step-specific details

    # Relationship
    execution = relationship("Execution", back_populates="steps")

    def __repr__(self):
        return (
            f"<ExecutionStep(execution_id='{self.execution_id}', "
            f"step='{self.step_name}', status='{self.status}')>"
        )


class ManualQueueItem(Base):
    """Manual processing queue.

    Replaces: state.py manual_process_queue list
    Tracks paths marked for manual processing with settings.
    """

    __tablename__ = "manual_queue"
    __table_args__ = (Index("idx_manual_queue_priority", "priority", "added_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String(1000), unique=True, nullable=False)
    skip_caption_generation = Column(Boolean, default=False, nullable=False)
    log_verbosity = Column(String(50), default="NORMAL", nullable=False)
    added_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    priority = Column(Integer, default=0, nullable=False)

    def __repr__(self):
        return f"<ManualQueueItem(path='{self.path}', priority={self.priority})>"


class Heartbeat(Base):
    """Service heartbeat tracking.

    Replaces: heartbeat_*.txt files
    """

    __tablename__ = "heartbeats"

    service_name = Column(String(50), primary_key=True)  # 'polling', 'manual', 'web'
    last_beat = Column(DateTime, nullable=False)
    status = Column(String(50), nullable=False)  # 'alive', 'stale', 'dead'

    def __repr__(self):
        return f"<Heartbeat(service='{self.service_name}', status='{self.status}')>"


class Progress(Base):
    """Real-time progress tracking.

    Replaces: progress_tracker.py JSON storage
    """

    __tablename__ = "progress"

    job_id = Column(String(200), primary_key=True)
    process_type = Column(String(50), nullable=False)  # 'whisper', 'ffmpeg'
    percent = Column(Float, nullable=False)
    message = Column(String(500), nullable=True)
    progress_metadata = Column(Text, nullable=True)  # JSON
    updated_at = Column(DateTime, nullable=False)

    def __repr__(self):
        return (
            f"<Progress(job_id='{self.job_id}', "
            f"type='{self.process_type}', percent={self.percent})>"
        )


class OrphanCleanupHistory(Base):
    """Track orphan cleanup runs for execution history retention.

    Stores the last successful orphan cleanup run date.
    Used to determine safe cutoff date for execution history cleanup.
    """

    __tablename__ = "orphan_cleanup_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cleanup_timestamp = Column(DateTime, nullable=False)
    orig_files_deleted = Column(Integer, default=0)
    srt_files_deleted = Column(Integer, default=0)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self):
        return (
            f"<OrphanCleanupHistory(id={self.id}, "
            f"cleanup_timestamp={self.cleanup_timestamp}, "
            f"deleted={self.orig_files_deleted + self.srt_files_deleted})>"
        )


class PollingCache(Base):
    """Polling source yielded cache (persistent).

    Replaces: in-memory _yielded_cache dict.
    Prevents duplicate processing across restarts.
    """

    __tablename__ = "polling_cache"
    __table_args__ = (Index("idx_polling_cache_yielded_at", "yielded_at"),)

    rec_id = Column(String(100), primary_key=True)
    yielded_at = Column(DateTime, nullable=False)

    def __repr__(self):
        return (
            f"<PollingCache(rec_id='{self.rec_id}', "
            f"yielded_at='{self.yielded_at}')>"
        )
