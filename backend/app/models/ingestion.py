import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class IngestionStatus:
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SourceType:
    SHOPIFY = "SHOPIFY"
    RAZORPAY = "RAZORPAY"
    HDFC = "HDFC"


class IngestionBatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Tracks uploaded files, processing lifecycle, validation metrics, and cryptographic hashes.
    """
    __tablename__ = "ingestion_batches"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    source_type = Column(String(50), nullable=False)  # SHOPIFY, RAZORPAY, HDFC
    filename = Column(String(255), nullable=False)
    file_hash_sha256 = Column(String(64), nullable=False, index=True)
    file_size_bytes = Column(Integer, nullable=False, default=0)

    status = Column(String(50), nullable=False, default=IngestionStatus.UPLOADED, index=True)
    error_message = Column(Text, nullable=True)

    total_rows = Column(Integer, nullable=False, default=0)
    valid_rows = Column(Integer, nullable=False, default=0)
    invalid_rows = Column(Integer, nullable=False, default=0)
    duplicate_rows = Column(Integer, nullable=False, default=0)
    warning_rows = Column(Integer, nullable=False, default=0)

    processing_duration_ms = Column(Integer, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    row_errors = relationship("SourceRowError", back_populates="batch", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_ingestion_tenant_status", "tenant_id", "status"),
        Index("ix_ingestion_tenant_hash", "tenant_id", "file_hash_sha256"),
    )


class SourceRowError(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Detailed row-level errors and warnings isolated during ingestion.
    Never silently discard invalid or duplicate records.
    """
    __tablename__ = "source_row_errors"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    row_index = Column(Integer, nullable=False)
    error_level = Column(String(20), nullable=False, default="ERROR")  # ERROR, WARNING, DUPLICATE
    field_name = Column(String(100), nullable=True)
    raw_value = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    raw_record = Column(JSON, nullable=True)

    batch = relationship("IngestionBatch", back_populates="row_errors")

    __table_args__ = (
        Index("ix_row_error_tenant_batch", "tenant_id", "batch_id"),
    )
