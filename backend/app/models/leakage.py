import uuid
from decimal import Decimal
from datetime import datetime, date, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    DateTime,
    Date,
    Boolean,
    ForeignKey,
    Text,
    JSON,
    Index,
    UniqueConstraint,
    CheckConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, ImmutabilityViolationError


class DetectorType(str, Enum):
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    UNCREDITED_SETTLEMENT = "UNCREDITED_SETTLEMENT"
    FEE_OVERCHARGE = "FEE_OVERCHARGE"
    REFUND_ANOMALY = "REFUND_ANOMALY"


class LeakageExceptionType(str, Enum):
    # Detector 1: Missing Settlements
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    PARTIALLY_MISSING_SETTLEMENT = "PARTIALLY_MISSING_SETTLEMENT"
    SETTLEMENT_OVERDUE = "SETTLEMENT_OVERDUE"

    # Detector 2: Uncredited Settlements
    UNCREDITED_SETTLEMENT = "UNCREDITED_SETTLEMENT"
    PARTIALLY_UNCREDITED_SETTLEMENT = "PARTIALLY_UNCREDITED_SETTLEMENT"
    SETTLEMENT_AMOUNT_MISMATCH = "SETTLEMENT_AMOUNT_MISMATCH"
    AMBIGUOUS_BANK_CREDIT = "AMBIGUOUS_BANK_CREDIT"

    # Detector 3: Contractual Fee Overcharges
    FEE_OVERCHARGE = "FEE_OVERCHARGE"
    UNAUTHORIZED_FEE = "UNAUTHORIZED_FEE"
    FEE_CALCULATION_DISCREPANCY = "FEE_CALCULATION_DISCREPANCY"
    CONTRACT_CONFIGURATION_MISSING = "CONTRACT_CONFIGURATION_MISSING"

    # Detector 4: Duplicate & Unauthorized Refunds
    DUPLICATE_REFUND = "DUPLICATE_REFUND"
    UNAUTHORIZED_REFUND = "UNAUTHORIZED_REFUND"
    EXCESS_REFUND = "EXCESS_REFUND"
    REFUND_REFERENCE_COLLISION = "REFUND_REFERENCE_COLLISION"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    RECOVERED = "RECOVERED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    CLOSED = "CLOSED"


class ExceptionSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DetectionRunStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SnapshotQuality(str, Enum):
    VERIFIED_AT_EXECUTION = "VERIFIED_AT_EXECUTION"
    LEGACY_BACKFILL = "LEGACY_BACKFILL"



# ---------------------------------------------------------------------------
# Leakage Detection Runs
# ---------------------------------------------------------------------------

class LeakageDetectionRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Execution run of the deterministic revenue leakage detectors.
    Tracks detection parameters, evaluation counts, total leakage and potential recovery.
    """
    __tablename__ = "leakage_detection_runs"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    run_number = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default=DetectionRunStatus.PENDING.value)
    is_active = Column(Boolean, nullable=False, default=True)

    triggered_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    reconciliation_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reconciliation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    parameters = Column(JSON, nullable=True)

    # Counts & Metrics
    total_captures_evaluated = Column(Integer, nullable=False, default=0)
    total_settlements_evaluated = Column(Integer, nullable=False, default=0)
    total_refunds_evaluated = Column(Integer, nullable=False, default=0)
    exceptions_count = Column(Integer, nullable=False, default=0)

    # Monetary Totals (Arbitrary Precision NUMERIC)
    total_leakage_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_potential_recovery = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))

    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships (Foreign keys enforce RESTRICT; parent does not cascade-delete children)
    exceptions = relationship(
        "LeakageException",
        back_populates="detection_run",
        foreign_keys="LeakageException.detection_run_id",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    run_observations = relationship(
        "LeakageRunException",
        back_populates="detection_run",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    run_evidence_items = relationship(
        "LeakageRunEvidence",
        back_populates="detection_run",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_leakage_run_tenant", "tenant_id", "run_number"),
        Index("ix_leakage_run_status", "tenant_id", "status"),
        UniqueConstraint("tenant_id", "run_number", name="uq_tenant_leakage_run_number"),
    )


# ---------------------------------------------------------------------------
# Leakage Exceptions
# ---------------------------------------------------------------------------

class LeakageException(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Substantiated financial leakage exception with full evidence provenance and lifecycle.
    """
    __tablename__ = "leakage_exceptions"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    # The run in which this exception was first detected (immutable origin lineage)
    detection_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_detection_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    # The most recent run that evaluated this exception
    latest_detection_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_detection_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True
    )

    detector_type = Column(String(50), nullable=False)  # MISSING_SETTLEMENT, UNCREDITED_SETTLEMENT, FEE_OVERCHARGE, REFUND_ANOMALY
    exception_type = Column(String(50), nullable=False) # Specific sub-classification
    status = Column(String(50), nullable=False, default=ExceptionStatus.OPEN.value)
    severity = Column(String(20), nullable=False, default=ExceptionSeverity.MEDIUM.value)
    severity_reason = Column(Text, nullable=False)

    # Source Entity Traceability
    source_entity_type = Column(String(50), nullable=False)  # canonical_payments, canonical_settlements, canonical_refunds
    source_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_reference = Column(String(100), nullable=False)   # gateway_payment_id, settlement_reference, gateway_refund_id
    order_reference = Column(String(100), nullable=True)
    gateway_name = Column(String(50), nullable=False, default="RAZORPAY")

    # Financial Quantums (Strict Decimal)
    expected_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    actual_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    leakage_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    recoverable_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    currency = Column(String(3), nullable=False, default="INR")

    # Forensic Calculation Breakdown & Explainability
    calculation_breakdown = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=False)
    detector_version = Column(String(20), nullable=False, default="1.0.0")
    rule_version = Column(String(50), nullable=False, default="FINORA-DETECTORS-V3")
    contract_id = Column(UUID(as_uuid=True), ForeignKey("fee_contracts.id", ondelete="SET NULL"), nullable=True)
    contract_version = Column(Integer, nullable=True)

    # Human Review & Resolution
    reviewed_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_action = Column(String(50), nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # Relationships
    detection_run = relationship(
        "LeakageDetectionRun",
        back_populates="exceptions",
        foreign_keys=[detection_run_id],
    )
    latest_detection_run = relationship(
        "LeakageDetectionRun",
        foreign_keys=[latest_detection_run_id],
    )
    evidence_items = relationship(
        "LeakageExceptionEvidence",
        back_populates="exception",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    reviews = relationship(
        "LeakageExceptionReview",
        back_populates="exception",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    run_observations = relationship(
        "LeakageRunException",
        back_populates="exception",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_leakage_exc_tenant_detector", "tenant_id", "detector_type"),
        Index("ix_leakage_exc_tenant_status", "tenant_id", "status"),
        Index("ix_leakage_exc_tenant_severity", "tenant_id", "severity"),
        Index("ix_leakage_exc_source", "tenant_id", "source_entity_type", "source_entity_id"),
        CheckConstraint("leakage_amount >= 0", name="chk_positive_leakage_amount"),
        CheckConstraint("recoverable_amount >= 0", name="chk_positive_recoverable_amount"),
    )


# ---------------------------------------------------------------------------
# Point-in-time Observation: LeakageRunException
# ---------------------------------------------------------------------------

class LeakageRunException(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Immutable point-in-time observation of an exception within a specific detection run.
    Preserves historical financial quantums, status, breakdown and explanation.
    """
    __tablename__ = "leakage_run_exceptions"

    detection_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_detection_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    exception_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_exceptions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )

    observed_status = Column(String(50), nullable=False)
    observed_severity = Column(String(20), nullable=False)
    observed_expected_amount = Column(Numeric(18, 4), nullable=False)
    observed_actual_amount = Column(Numeric(18, 4), nullable=False)
    observed_leakage_amount = Column(Numeric(18, 4), nullable=False)
    observed_recoverable_amount = Column(Numeric(18, 4), nullable=False)

    calculation_breakdown = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=False)
    snapshot_quality = Column(String(50), nullable=False, default=SnapshotQuality.VERIFIED_AT_EXECUTION.value)

    detection_run = relationship("LeakageDetectionRun", back_populates="run_observations")
    exception = relationship("LeakageException", back_populates="run_observations")

    __table_args__ = (
        UniqueConstraint("detection_run_id", "exception_id", name="uq_run_exception_snapshot"),
        Index("ix_run_exception_tenant", "tenant_id", "detection_run_id"),
    )


# ---------------------------------------------------------------------------
# Leakage Exception Evidence Items
# ---------------------------------------------------------------------------

class LeakageExceptionEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Structured evidence record substantiating a leakage finding.
    Evidence rows are immutable and fingerprinted with SHA-256 over canonicalized payload.
    """
    __tablename__ = "leakage_exception_evidence"

    exception_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_exceptions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    fingerprint_sha256 = Column(String(64), nullable=False, index=True)
    detection_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_detection_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True
    )

    evidence_type = Column(String(50), nullable=False)  # PAYMENT_CAPTURE, SETTLEMENT_BATCH, BANK_TRANSACTION, REFUND_EVENT, FEE_TIER, CALENDAR_RULE
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    source_batch_id = Column(UUID(as_uuid=True), nullable=True)
    source_row_index = Column(Integer, nullable=True)

    details = Column(JSON, nullable=True)

    exception = relationship("LeakageException", back_populates="evidence_items")
    detection_run = relationship("LeakageDetectionRun")
    run_associations = relationship(
        "LeakageRunEvidence",
        back_populates="evidence",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_evidence_exception", "exception_id", "evidence_type"),
        Index("ix_evidence_entity", "tenant_id", "entity_type", "entity_id"),
        UniqueConstraint("exception_id", "fingerprint_sha256", name="uq_evidence_exception_fingerprint"),
    )

    def __init__(self, *args, **kwargs):
        if not kwargs.get("fingerprint_sha256"):
            from app.services.leakage.evidence_hasher import generate_evidence_fingerprint
            kwargs["fingerprint_sha256"] = generate_evidence_fingerprint(
                evidence_type=kwargs.get("evidence_type", ""),
                entity_type=kwargs.get("entity_type", ""),
                entity_id=kwargs.get("entity_id"),
                details=kwargs.get("details"),
            )
        super().__init__(*args, **kwargs)



# ---------------------------------------------------------------------------
# Run Evidence Junction: LeakageRunEvidence
# ---------------------------------------------------------------------------

class LeakageRunEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Immutable association between a detection run and an evidence item evaluated in that run.
    """
    __tablename__ = "leakage_run_evidence"

    detection_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_detection_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    evidence_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_exception_evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )

    detection_run = relationship("LeakageDetectionRun", back_populates="run_evidence_items")
    evidence = relationship("LeakageExceptionEvidence", back_populates="run_associations")

    __table_args__ = (
        UniqueConstraint("detection_run_id", "evidence_id", name="uq_run_evidence_item"),
        Index("ix_run_evidence_tenant", "tenant_id", "detection_run_id"),
    )


# ---------------------------------------------------------------------------
# Leakage Exception Reviews (Audit Trail of Decisions)
# ---------------------------------------------------------------------------

class LeakageExceptionReview(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Immutable review record tracking human lifecycle transitions and dispute decisions.
    """
    __tablename__ = "leakage_exception_reviews"

    exception_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_exceptions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    reviewer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    from_status = Column(String(50), nullable=False)
    to_status = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)  # CONFIRM, FLAG_DISPUTED, MARK_FALSE_POSITIVE, RESOLVE, CLOSE
    notes = Column(Text, nullable=True)

    exception = relationship("LeakageException", back_populates="reviews")

    __table_args__ = (
        Index("ix_review_exception", "exception_id"),
        Index("ix_review_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# SQLAlchemy Immutability Event Listeners
# ---------------------------------------------------------------------------

def _prevent_update_or_delete(mapper, connection, target):
    raise ImmutabilityViolationError(
        f"Modifications or deletions of {target.__class__.__name__} records are strictly prohibited for audit integrity."
    )


event.listen(LeakageRunException, "before_update", _prevent_update_or_delete)
event.listen(LeakageRunException, "before_delete", _prevent_update_or_delete)
event.listen(LeakageRunEvidence, "before_update", _prevent_update_or_delete)
event.listen(LeakageRunEvidence, "before_delete", _prevent_update_or_delete)
event.listen(LeakageExceptionEvidence, "before_update", _prevent_update_or_delete)
event.listen(LeakageExceptionEvidence, "before_delete", _prevent_update_or_delete)
