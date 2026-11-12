import uuid
from decimal import Decimal
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.reconciliation import FeeContractResponse


class FlowStageSummary(BaseModel):
    total_count: int = 0
    total_amount: Decimal = Decimal("0.0000")
    matched_count: int = 0
    matched_amount: Decimal = Decimal("0.0000")
    unmatched_count: int = 0
    unmatched_amount: Decimal = Decimal("0.0000")


class ThreeWayFlowOverview(BaseModel):
    shopify_orders: FlowStageSummary
    razorpay_payments: FlowStageSummary
    gateway_settlements: FlowStageSummary
    hdfc_bank_credits: FlowStageSummary


class LeakageTrendItem(BaseModel):
    date: str
    reconciled_amount: Decimal
    unmatched_amount: Decimal


class CategoryLeakageSummary(BaseModel):
    category: str
    display_name: str
    count: int
    total_amount: Decimal


class SeverityLeakageSummary(BaseModel):
    severity: str
    count: int
    total_amount: Decimal


class DashboardOverviewResponse(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    currency: str = "INR"

    # Executive Overview Totals
    total_orders_count: int
    total_orders_amount: Decimal
    total_captured_count: int
    total_captured_amount: Decimal
    total_settlements_count: int
    total_settled_amount: Decimal
    total_bank_credits_count: int
    total_bank_credited_amount: Decimal

    # Reconciled vs Unmatched
    reconciled_amount: Decimal
    unmatched_amount: Decimal
    reconciliation_accuracy_percentage: Decimal

    # Leakage & Review Metrics
    total_detected_leakage: Decimal
    leakage_findings_count: int
    pending_review_count: int

    # Latest Run Information
    latest_run_id: Optional[uuid.UUID] = None
    latest_run_number: Optional[int] = None
    latest_run_status: Optional[str] = None
    latest_run_timestamp: Optional[datetime] = None

    # Visual Flow & Breakdown
    flow: ThreeWayFlowOverview
    trends: List[LeakageTrendItem] = []
    leakage_by_category: List[CategoryLeakageSummary] = []
    leakage_by_severity: List[SeverityLeakageSummary] = []

    model_config = ConfigDict(from_attributes=True)


class LeakageFindingItem(BaseModel):
    id: str
    finding_id: str
    category: str
    title: str
    expected_amount: Decimal
    actual_amount: Decimal
    difference: Decimal
    severity: str  # HIGH, MEDIUM, LOW
    detection_date: datetime
    evidence_references: Dict[str, Any] = {}
    review_status: str  # PENDING, APPROVED, REJECTED, RESOLVED
    match_id: Optional[uuid.UUID] = None
    entity_type: Optional[str] = None
    entity_id: Optional[uuid.UUID] = None


class LeakageFindingsResponse(BaseModel):
    total_findings: int
    total_leakage_amount: Decimal
    high_severity_count: int
    medium_severity_count: int
    low_severity_count: int
    findings: List[LeakageFindingItem]


class ReviewQueueCandidate(BaseModel):
    id: str
    reference: str
    amount: Decimal
    date: Optional[str] = None
    score: Optional[Decimal] = None


class ReviewQueueItem(BaseModel):
    match_id: uuid.UUID
    run_id: uuid.UUID
    run_number: int
    match_type: str
    classification: str
    pass_number: int
    confidence_score: Decimal
    source_amount: Decimal
    target_amount: Decimal
    allocated_amount: Decimal
    discrepancy_amount: Decimal
    fee_discrepancy: Decimal
    explanation: str
    evidence_metadata: Optional[Dict[str, Any]] = None
    review_status: str
    reviewed_by_user_id: Optional[uuid.UUID] = None
    reviewed_at: Optional[datetime] = None
    review_action: Optional[str] = None
    review_notes: Optional[str] = None
    created_at: datetime
    candidates: List[ReviewQueueCandidate] = []

    model_config = ConfigDict(from_attributes=True)


class ReviewQueueResponse(BaseModel):
    total_pending: int
    items: List[ReviewQueueItem]


class FeeInstrumentTierAnalytics(BaseModel):
    instrument_type: str
    percentage_rate: Decimal
    fixed_fee_per_txn: Decimal
    transactions_evaluated: int
    gross_volume: Decimal
    actual_gateway_fees: Decimal
    contractual_expected_fees: Decimal
    variance: Decimal


class FeeAnalyticsResponse(BaseModel):
    active_contract: Optional[FeeContractResponse] = None
    contract_version: int = 1
    gst_rate: Decimal = Decimal("0.180000")
    total_gross_volume: Decimal = Decimal("0.0000")
    total_reported_fees: Decimal = Decimal("0.0000")
    total_contractual_fees: Decimal = Decimal("0.0000")
    total_fee_drift: Decimal = Decimal("0.0000")
    total_fee_overcharges: Decimal = Decimal("0.0000")
    tiers: List[FeeInstrumentTierAnalytics] = []


class AIInvestigationStatusResponse(BaseModel):
    provider: str = "GOOGLE_GEMINI"
    status: str = "PENDING_CONFIGURATION"
    is_configured: bool = False
    model_version: str = "gemini-2.0-flash"
    investigations_count: int = 0
    message: str = (
        "Google Gemini API integration is currently pending API key provisioning. "
        "AI-assisted forensic dossiers and grounded dispute recovery narratives will activate "
        "automatically once the GEMINI_API_KEY environment variable is configured."
    )
    recent_investigations: List[Dict[str, Any]] = []


class AuditLogItem(BaseModel):
    id: uuid.UUID
    action: str
    target_entity_type: str
    target_entity_id: Optional[uuid.UUID] = None
    user_email: Optional[str] = None
    user_rationale: Optional[str] = None
    ip_address: Optional[str] = None
    performed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogsResponse(BaseModel):
    total_logs: int
    logs: List[AuditLogItem]
