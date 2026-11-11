import uuid
from decimal import Decimal
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

from app.models.reconciliation import (
    ReconciliationStatus,
    MatchType,
    MatchClassification,
    ReviewStatus,
    AllocationStatus,
)


# ---------------------------------------------------------------------------
# Fee Schedule & Contract Schemas
# ---------------------------------------------------------------------------

class FeeScheduleTierBase(BaseModel):
    instrument_type: str = Field(..., description="UPI, DEBIT, CREDIT_STANDARD, CREDIT_CORPORATE, NETBANKING, INTERNATIONAL")
    percentage_rate: Decimal = Field(default=Decimal("0.020000"), description="Rate fraction e.g. 0.02 for 2%")
    fixed_fee_per_txn: Decimal = Field(default=Decimal("0.0000"), description="Fixed fee per transaction")
    min_fee_cap: Optional[Decimal] = None
    max_fee_cap: Optional[Decimal] = None


class FeeScheduleTierCreate(FeeScheduleTierBase):
    pass


class FeeScheduleTierResponse(FeeScheduleTierBase):
    id: uuid.UUID
    contract_id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeeContractBase(BaseModel):
    gateway_name: str = "RAZORPAY"
    contract_name: str = "Standard Enterprise Gateway Tariff"
    start_date: date
    end_date: Optional[date] = None
    gst_rate: Decimal = Decimal("0.180000")
    chargeback_dispute_fee: Decimal = Decimal("500.0000")
    rolling_reserve_percentage: Decimal = Decimal("0.000000")
    rolling_reserve_hold_days: int = 0
    retain_mdr_on_refund: bool = True
    instant_refund_flat_fee: Decimal = Decimal("0.0000")
    instant_refund_percentage_fee: Decimal = Decimal("0.000000")


class FeeContractCreate(FeeContractBase):
    tiers: List[FeeScheduleTierCreate] = []


class FeeContractResponse(FeeContractBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    version: int
    is_active: bool
    created_at: datetime
    tiers: List[FeeScheduleTierResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Reconciliation Run Schemas
# ---------------------------------------------------------------------------

class ReconciliationRunParameters(BaseModel):
    fee_overcharge_tolerance: Decimal = Decimal("0.05")
    max_knapsack_bound: int = 5
    settlement_window_days: int = 3
    settlement_cutoff_time: str = "23:00"
    min_auto_match_score: Decimal = Decimal("0.9000")
    min_collision_delta: Decimal = Decimal("0.1500")


class ReconciliationRunCreate(BaseModel):
    parameters: Optional[ReconciliationRunParameters] = None


class ReconciliationRunResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    run_number: int
    status: ReconciliationStatus
    is_active: bool
    triggered_by_user_id: Optional[uuid.UUID] = None
    parameters: Optional[Dict[str, Any]] = None

    total_orders_evaluated: int
    total_payments_evaluated: int
    total_settlements_evaluated: int
    total_bank_transactions_evaluated: int

    matched_orders_count: int
    matched_payments_count: int
    matched_settlements_count: int
    matched_bank_txs_count: int

    unmatched_orders_count: int
    unmatched_payments_count: int
    unmatched_settlements_count: int
    unmatched_bank_txs_count: int

    ambiguous_matches_count: int
    unresolved_count: int

    total_order_amount: Decimal
    total_captured_amount: Decimal
    total_settled_amount: Decimal
    total_matched_bank_amount: Decimal
    total_discrepancy_amount: Decimal
    total_fee_drift_amount: Decimal

    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Match & Allocation Schemas
# ---------------------------------------------------------------------------

class ReconciliationMatchResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    run_id: uuid.UUID
    match_type: MatchType
    classification: MatchClassification
    pass_number: int
    confidence_score: Decimal

    order_id: Optional[uuid.UUID] = None
    payment_id: Optional[uuid.UUID] = None
    settlement_id: Optional[uuid.UUID] = None
    bank_transaction_id: Optional[uuid.UUID] = None

    source_amount: Decimal
    target_amount: Decimal
    allocated_amount: Decimal
    discrepancy_amount: Decimal
    expected_fee: Decimal
    expected_tax: Decimal
    fee_discrepancy: Decimal

    explanation: str
    evidence_metadata: Optional[Dict[str, Any]] = None

    review_status: ReviewStatus
    reviewed_by_user_id: Optional[uuid.UUID] = None
    reviewed_at: Optional[datetime] = None
    review_action: Optional[str] = None
    review_notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReconciliationAllocationResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    run_id: uuid.UUID
    match_id: uuid.UUID
    source_entity_type: str
    source_entity_id: uuid.UUID
    target_entity_type: str
    target_entity_id: uuid.UUID
    allocated_amount: Decimal
    status: AllocationStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Human Review & Resolution
# ---------------------------------------------------------------------------

class MatchResolutionRequest(BaseModel):
    action: str = Field(..., description="APPROVE, REJECT, or MANUAL_ALLOCATE")
    notes: Optional[str] = Field(None, description="Auditable reviewer explanation or rationale")
    target_entity_id: Optional[uuid.UUID] = Field(None, description="Chosen entity ID if resolving an ambiguous candidate")
    allocated_amount: Optional[Decimal] = Field(None, description="Manual allocation override amount")


# ---------------------------------------------------------------------------
# Summary and Unmatched Aggregations
# ---------------------------------------------------------------------------

class ReconciliationSummaryResponse(BaseModel):
    run_id: uuid.UUID
    run_number: int
    status: ReconciliationStatus
    is_active: bool

    # Executive Overview
    total_expected_revenue: Decimal
    total_captured_revenue: Decimal
    total_settled_revenue: Decimal
    total_bank_credited_revenue: Decimal

    # Match Ratios
    order_to_payment_match_rate: Decimal
    settlement_to_bank_match_rate: Decimal

    # Leakage and Discrepancies
    total_discrepancy_amount: Decimal
    unmatched_orders_count: int
    unmatched_payments_count: int
    unmatched_settlements_count: int
    unmatched_bank_txs_count: int
    ambiguous_matches_count: int
    unresolved_count: int

    # Tariff Analysis
    total_fee_drift: Decimal


class UnmatchedEntitiesResponse(BaseModel):
    run_id: uuid.UUID
    unmatched_orders: List[Dict[str, Any]]
    unmatched_payments: List[Dict[str, Any]]
    unmatched_settlements: List[Dict[str, Any]]
    unmatched_bank_transactions: List[Dict[str, Any]]
