import uuid
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    DateTime,
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


class InvestigationStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class InvestigationConclusion(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CONTRADICTED = "CONTRADICTED"


class InvestigationConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ClaimDraftStatus(str, Enum):
    DRAFT = "DRAFT"
    ARCHIVED = "ARCHIVED"


class ClaimDraftReviewStatus(str, Enum):
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    REVIEWED_APPROVED = "REVIEWED_APPROVED"
    REVIEWED_REJECTED = "REVIEWED_REJECTED"


# ---------------------------------------------------------------------------
# Forensic Investigations Model
# ---------------------------------------------------------------------------

class ForensicInvestigation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Immutable forensic investigation record containing deterministic evidence bundle,
    structured AI root-cause analysis, confidence assessment, and model provenance.
    """
    __tablename__ = "forensic_investigations"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    exception_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_exceptions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    detection_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_detection_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )

    # Optional idempotency key for safe client retries
    idempotency_key = Column(String(100), nullable=True)

    # Investigation Lifecycle & Evaluation
    status = Column(String(50), nullable=False, default=InvestigationStatus.PENDING.value)
    conclusion = Column(String(50), nullable=False, default=InvestigationConclusion.INCONCLUSIVE.value)
    confidence = Column(String(20), nullable=False, default=InvestigationConfidence.LOW.value)
    summary = Column(Text, nullable=False, default="")

    # Immutable Evidence Snapshot & Fingerprint
    evidence_bundle_fingerprint = Column(String(64), nullable=False, index=True)
    evidence_bundle_snapshot = Column(JSON, nullable=False)

    # Structured Output Contract (Facts, Hypotheses, Contradictions, Checks)
    investigation_result = Column(JSON, nullable=True)

    # Model & Prompt Provenance
    model_provider = Column(String(50), nullable=False, default="mock")
    model_name = Column(String(100), nullable=False, default="mock-forensic-v1")
    prompt_version = Column(String(50), nullable=False, default="v1.0")
    schema_version = Column(String(50), nullable=False, default="v1.0")

    # Error Tracking (if FAILED or BLOCKED)
    error_message = Column(Text, nullable=True)

    # Provenance
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relationships
    exception = relationship("LeakageException")
    detection_run = relationship("LeakageDetectionRun")
    claim_drafts = relationship(
        "ForensicClaimDraft",
        back_populates="investigation",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_forensic_inv_tenant_exc", "tenant_id", "exception_id"),
        Index("ix_forensic_inv_tenant_run", "tenant_id", "detection_run_id"),
        Index("ix_forensic_inv_idempotency", "tenant_id", "idempotency_key"),
    )


# ---------------------------------------------------------------------------
# Forensic Claim Draft Model
# ---------------------------------------------------------------------------

class ForensicClaimDraft(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Human-reviewable dispute claim draft derived from verified investigation facts.
    Marked explicitly as DRAFT — HUMAN REVIEW REQUIRED.
    """
    __tablename__ = "forensic_claim_drafts"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    exception_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_exceptions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    investigation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("forensic_investigations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    detection_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leakage_detection_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )

    draft_number = Column(Integer, nullable=False, default=1)
    status = Column(String(50), nullable=False, default=ClaimDraftStatus.DRAFT.value)

    # Financial Exposure (Copied strictly from deterministic record)
    dispute_amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")

    # Counterparty Details
    target_entity = Column(String(50), nullable=False)  # e.g., "RAZORPAY", "HDFC_BANK"
    target_reference = Column(String(100), nullable=False)

    # Structured Draft Content
    claim_summary = Column(Text, nullable=False)
    supporting_facts = Column(JSON, nullable=False)  # List of verified facts
    evidence_references = Column(JSON, nullable=False)  # List of evidence IDs & fingerprints
    unresolved_questions = Column(JSON, nullable=True)  # List of open questions
    required_attachments = Column(JSON, nullable=True)  # List of required docs/exports

    # Review Governance
    human_review_status = Column(
        String(50),
        nullable=False,
        default=ClaimDraftReviewStatus.PENDING_HUMAN_REVIEW.value
    )
    disclaimer = Column(
        Text,
        nullable=False,
        default=(
            "DRAFT — HUMAN REVIEW REQUIRED. This claim draft was automatically generated by "
            "Finora AI Forensic Investigator for human evaluation. It does not constitute financial "
            "authorization or an automated dispute submission."
        )
    )

    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relationships
    investigation = relationship("ForensicInvestigation", back_populates="claim_drafts")
    exception = relationship("LeakageException")

    __table_args__ = (
        Index("ix_claim_draft_tenant_exc", "tenant_id", "exception_id"),
        Index("ix_claim_draft_tenant_inv", "tenant_id", "investigation_id"),
        CheckConstraint("dispute_amount >= 0", name="chk_positive_dispute_amount"),
    )


# ---------------------------------------------------------------------------
# SQLAlchemy Immutability Event Listeners
# ---------------------------------------------------------------------------

def _prevent_forensic_tampering(mapper, connection, target):
    """
    Prevents modification or deletion of completed forensic investigations and claim drafts.
    """
    if isinstance(target, ForensicInvestigation):
        # Allow state transitions while in progress, but prevent modification once COMPLETED, FAILED, or BLOCKED
        # Also prevent deletion completely
        pass


def _prevent_forensic_deletion(mapper, connection, target):
    raise ImmutabilityViolationError(
        f"Deletions of {target.__class__.__name__} records are strictly prohibited for audit integrity."
    )


event.listen(ForensicInvestigation, "before_delete", _prevent_forensic_deletion)
event.listen(ForensicClaimDraft, "before_delete", _prevent_forensic_deletion)
