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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class ReconciliationStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_EXCEPTIONS = "COMPLETED_WITH_EXCEPTIONS"
    FAILED = "FAILED"


class MatchType(str, Enum):
    ORDER_TO_PAYMENT = "ORDER_TO_PAYMENT"
    SETTLEMENT_TO_BANK = "SETTLEMENT_TO_BANK"
    THREE_WAY = "THREE_WAY"


class MatchClassification(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    AGGREGATED_MATCH = "AGGREGATED_MATCH"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    UNMATCHED = "UNMATCHED"
    UNRESOLVED = "UNRESOLVED"
    UNRESOLVED_SUBSET_BOUND_EXCEEDED = "UNRESOLVED_SUBSET_BOUND_EXCEEDED"
    AMBIGUOUS_AGGREGATION_COLLISION = "AMBIGUOUS_AGGREGATION_COLLISION"


class ReviewStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Fee Contracts and Tiers
# ---------------------------------------------------------------------------

class FeeContract(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Versioned Merchant Payment Gateway Fee Contract.
    Enforces contract-driven MDR, GST, refund fees, dispute fees, and rolling reserves.
    """
    __tablename__ = "fee_contracts"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    gateway_name = Column(String(50), nullable=False, default="RAZORPAY")
    contract_name = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)

    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)

    # General Tax and Policy
    gst_rate = Column(Numeric(8, 6), nullable=False, default=Decimal("0.180000"))  # 18% GST
    chargeback_dispute_fee = Column(Numeric(18, 4), nullable=False, default=Decimal("500.0000"))
    rolling_reserve_percentage = Column(Numeric(8, 6), nullable=False, default=Decimal("0.000000"))
    rolling_reserve_hold_days = Column(Integer, nullable=False, default=0)

    # Refund Fee Policy
    retain_mdr_on_refund = Column(Boolean, nullable=False, default=True)
    instant_refund_flat_fee = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    instant_refund_percentage_fee = Column(Numeric(8, 6), nullable=False, default=Decimal("0.000000"))

    # Relationships
    tiers = relationship("FeeScheduleTier", back_populates="contract", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_fee_contract_tenant", "tenant_id", "gateway_name", "is_active"),
    )


class FeeScheduleTier(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Payment method & instrument specific tariff tier within a FeeContract.
    """
    __tablename__ = "fee_schedule_tiers"

    contract_id = Column(
        UUID(as_uuid=True),
        ForeignKey("fee_contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )

    instrument_type = Column(String(50), nullable=False)  # UPI, DEBIT, CREDIT_STANDARD, CREDIT_CORPORATE, NETBANKING, INTERNATIONAL
    percentage_rate = Column(Numeric(8, 6), nullable=False, default=Decimal("0.020000"))  # e.g. 0.02 = 2.00%
    fixed_fee_per_txn = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    min_fee_cap = Column(Numeric(18, 4), nullable=True)
    max_fee_cap = Column(Numeric(18, 4), nullable=True)

    contract = relationship("FeeContract", back_populates="tiers")

    __table_args__ = (
        Index("ix_tier_contract_instrument", "contract_id", "instrument_type"),
    )


# ---------------------------------------------------------------------------
# Reconciliation Runs
# ---------------------------------------------------------------------------

class ReconciliationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Immutable Three-Way Financial Reconciliation Execution Run.
    Each execution produces an immutable ledger version. Re-runs create new runs.
    """
    __tablename__ = "reconciliation_runs"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    run_number = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default=ReconciliationStatus.PENDING.value)
    is_active = Column(Boolean, nullable=False, default=True)  # Set to False when superseded by a newer run

    triggered_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    parameters = Column(JSON, nullable=True)
    # Stored run parameters:
    # {
    #   "fee_overcharge_tolerance": "0.05",
    #   "max_knapsack_bound": 5,
    #   "settlement_window_days": 3,
    #   "settlement_cutoff_time": "23:00",
    #   "min_auto_match_score": "0.90",
    #   "min_collision_delta": "0.15"
    # }

    # Quantitative Evaluation Metrics
    total_orders_evaluated = Column(Integer, nullable=False, default=0)
    total_payments_evaluated = Column(Integer, nullable=False, default=0)
    total_settlements_evaluated = Column(Integer, nullable=False, default=0)
    total_bank_transactions_evaluated = Column(Integer, nullable=False, default=0)

    matched_orders_count = Column(Integer, nullable=False, default=0)
    matched_payments_count = Column(Integer, nullable=False, default=0)
    matched_settlements_count = Column(Integer, nullable=False, default=0)
    matched_bank_txs_count = Column(Integer, nullable=False, default=0)

    unmatched_orders_count = Column(Integer, nullable=False, default=0)
    unmatched_payments_count = Column(Integer, nullable=False, default=0)
    unmatched_settlements_count = Column(Integer, nullable=False, default=0)
    unmatched_bank_txs_count = Column(Integer, nullable=False, default=0)

    ambiguous_matches_count = Column(Integer, nullable=False, default=0)
    unresolved_count = Column(Integer, nullable=False, default=0)

    # Monetary Totals (Arbitrary Precision NUMERIC)
    total_order_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_captured_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_settled_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_matched_bank_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_discrepancy_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_fee_drift_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))

    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    matches = relationship("ReconciliationMatch", back_populates="run", cascade="all, delete-orphan")
    allocations = relationship("ReconciliationAllocation", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_recon_run_tenant", "tenant_id", "run_number"),
        Index("ix_recon_run_status", "tenant_id", "status"),
        UniqueConstraint("tenant_id", "run_number", name="uq_tenant_recon_run_number"),
    )


# ---------------------------------------------------------------------------
# Reconciliation Matches
# ---------------------------------------------------------------------------

class ReconciliationMatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Correlation record matching source and target entities across reconciliation passes.
    Preserves confidence scores, pass metadata, discrepancy amounts, and human review status.
    """
    __tablename__ = "reconciliation_matches"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    match_type = Column(String(50), nullable=False)  # ORDER_TO_PAYMENT, SETTLEMENT_TO_BANK, THREE_WAY
    classification = Column(String(50), nullable=False)  # EXACT_MATCH, PARTIAL_MATCH, AGGREGATED_MATCH, AMBIGUOUS_MATCH, UNRESOLVED...
    pass_number = Column(Integer, nullable=False)  # 1 to 6
    confidence_score = Column(Numeric(6, 4), nullable=False)  # 0.0000 to 1.0000

    # Linked Entity Identifiers (nullable depending on match type)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("canonical_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    payment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("canonical_payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    settlement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("canonical_settlements.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    bank_transaction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("canonical_bank_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Financial Amounts
    source_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    target_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    allocated_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    discrepancy_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    expected_fee = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    expected_tax = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    fee_discrepancy = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))

    explanation = Column(Text, nullable=False)
    evidence_metadata = Column(JSON, nullable=True)
    # Stored explanation details:
    # {
    #   "utr_score": 1.0,
    #   "amount_score": 1.0,
    #   "date_score": 0.9,
    #   "narration_score": 0.8,
    #   "candidate_scores": [{"id": "...", "score": 0.75}],
    #   "score_delta": 0.25,
    #   "subset_settlement_ids": ["..."],
    #   "calculated_mdr": "24.0000",
    #   "calculated_gst": "4.3200"
    # }

    # Human Review & Resolution
    review_status = Column(String(50), nullable=False, default=ReviewStatus.NOT_REQUIRED.value)
    reviewed_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_action = Column(String(50), nullable=True)  # APPROVE, REJECT, MANUAL_ALLOCATE
    review_notes = Column(Text, nullable=True)

    run = relationship("ReconciliationRun", back_populates="matches")
    allocations = relationship("ReconciliationAllocation", back_populates="match", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_match_tenant_run", "tenant_id", "run_id"),
        Index("ix_match_classification", "tenant_id", "classification"),
        Index("ix_match_review_status", "tenant_id", "review_status"),
    )


# ---------------------------------------------------------------------------
# Reconciliation Allocations (Double-Entry Ledger)
# ---------------------------------------------------------------------------

class ReconciliationAllocation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Atomic double-entry allocation between financial entities.
    Enforces that allocated amounts conserve value without exceeding source balances.
    """
    __tablename__ = "reconciliation_allocations"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    match_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reconciliation_matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    source_entity_type = Column(String(50), nullable=False)  # canonical_orders, canonical_payments, canonical_settlements
    source_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    target_entity_type = Column(String(50), nullable=False)  # canonical_payments, canonical_settlements, canonical_bank_transactions
    target_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    allocated_amount = Column(Numeric(18, 4), nullable=False)
    status = Column(String(50), nullable=False, default=AllocationStatus.ACTIVE.value)

    run = relationship("ReconciliationRun", back_populates="allocations")
    match = relationship("ReconciliationMatch", back_populates="allocations")

    __table_args__ = (
        Index("ix_alloc_tenant_run", "tenant_id", "run_id"),
        Index("ix_alloc_source", "tenant_id", "source_entity_type", "source_entity_id"),
        Index("ix_alloc_target", "tenant_id", "target_entity_type", "target_entity_id"),
        CheckConstraint("allocated_amount > 0", name="chk_positive_allocated_amount"),
    )


# ---------------------------------------------------------------------------
# Reconciliation Run Deltas
# ---------------------------------------------------------------------------

class ReconciliationRunDelta(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Tracks state differences between consecutive reconciliation runs (Run N vs Run N+1).
    Records newly resolved matches, broken correlations, and newly surfaced exceptions.
    """
    __tablename__ = "reconciliation_run_deltas"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    current_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    previous_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    delta_type = Column(String(50), nullable=False)  # NEW_MATCH, BROKEN_MATCH, STATUS_CHANGED, NEW_UNMATCHED
    match_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reconciliation_matches.id", ondelete="SET NULL"),
        nullable=True
    )
    details = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_run_delta_tenant", "tenant_id", "current_run_id", "previous_run_id"),
    )
