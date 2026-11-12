import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class DetectionRunCreate(BaseModel):
    reconciliation_run_id: Optional[uuid.UUID] = None
    parameters: Optional[Dict[str, Any]] = None


class DetectionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    run_number: int
    status: str
    is_active: bool
    reconciliation_run_id: Optional[uuid.UUID] = None
    parameters: Optional[Dict[str, Any]] = None
    total_captures_evaluated: int
    total_settlements_evaluated: int
    total_refunds_evaluated: int
    exceptions_count: int
    total_leakage_amount: Decimal
    total_potential_recovery: Decimal
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class EvidenceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exception_id: uuid.UUID
    evidence_type: str
    entity_type: str
    entity_id: uuid.UUID
    fingerprint_sha256: Optional[str] = None
    detection_run_id: Optional[uuid.UUID] = None
    source_batch_id: Optional[uuid.UUID] = None
    source_row_index: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    created_at: datetime


class LeakageRunExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    detection_run_id: uuid.UUID
    exception_id: uuid.UUID
    tenant_id: uuid.UUID
    observed_status: str
    observed_severity: str
    observed_expected_amount: Decimal
    observed_actual_amount: Decimal
    observed_leakage_amount: Decimal
    observed_recoverable_amount: Decimal
    calculation_breakdown: Optional[Dict[str, Any]] = None
    explanation: str
    snapshot_quality: str
    created_at: datetime


class ExceptionReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_status: str
    to_status: str
    action: str
    notes: Optional[str] = None
    reviewer_id: Optional[uuid.UUID] = None
    created_at: datetime


class LeakageExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    detection_run_id: uuid.UUID
    latest_detection_run_id: Optional[uuid.UUID] = None
    detector_type: str
    exception_type: str
    status: str
    severity: str
    severity_reason: str
    source_entity_type: str
    source_entity_id: uuid.UUID
    source_reference: str
    order_reference: Optional[str] = None
    gateway_name: str
    expected_amount: Decimal
    actual_amount: Decimal
    leakage_amount: Decimal
    recoverable_amount: Decimal
    currency: str
    calculation_breakdown: Optional[Dict[str, Any]] = None
    explanation: str
    detector_version: str
    rule_version: str
    contract_id: Optional[uuid.UUID] = None
    contract_version: Optional[int] = None
    reviewed_by_user_id: Optional[uuid.UUID] = None
    reviewed_at: Optional[datetime] = None
    review_action: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ExceptionReviewRequest(BaseModel):
    action: str = Field(..., description="CONFIRM, DISPUTE, MARK_FALSE_POSITIVE, MARK_RECOVERED, RESOLVE, CLOSE, REVIEW, REOPEN")
    notes: Optional[str] = None


class LeakageSummaryResponse(BaseModel):
    total_leakage_amount: Decimal
    total_potential_recovery: Decimal
    total_exceptions: int
    open_exceptions: int
    confirmed_exceptions: int
    disputed_exceptions: int
    recovered_exceptions: int
    resolved_exceptions: int
    breakdown_by_detector: Dict[str, Dict[str, Any]]
    breakdown_by_severity: Dict[str, int]
