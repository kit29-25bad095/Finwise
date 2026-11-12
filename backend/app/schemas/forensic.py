import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

from app.models.forensic import (
    InvestigationStatus,
    InvestigationConclusion,
    InvestigationConfidence,
    ClaimDraftStatus,
    ClaimDraftReviewStatus,
)


class ModelProvenance(BaseModel):
    provider: str
    model: str
    prompt_version: str = "v1.0"
    schema_version: str = "v1.0"


class Hypothesis(BaseModel):
    hypothesis_id: str = Field(..., description="Unique hypothesis identifier, e.g., H1, H2")
    title: str = Field(..., description="Short title describing the root cause hypothesis")
    explanation: str = Field(..., description="Detailed reasoning strictly grounded in verified evidence")
    supporting_evidence_ids: List[str] = Field(default_factory=list, description="List of evidence IDs supporting this hypothesis")
    contradicting_evidence_ids: List[str] = Field(default_factory=list, description="List of evidence IDs contradicting this hypothesis")
    missing_evidence: List[str] = Field(default_factory=list, description="Identified missing evidence needed to confirm or rule out")
    confidence: InvestigationConfidence = Field(default=InvestigationConfidence.LOW)


class InvestigationResultContract(BaseModel):
    summary: str = Field(..., description="Executive summary of the forensic investigation")
    hypotheses: List[Hypothesis] = Field(default_factory=list, description="Root cause hypotheses evaluated against evidence")
    verified_facts: List[str] = Field(default_factory=list, description="Empirical facts substantiated by verified evidence records")
    contradictions: List[str] = Field(default_factory=list, description="Direct contradictions detected between evidence records")
    missing_information: List[str] = Field(default_factory=list, description="Gaps in evidence preventing full confirmation")
    recommended_human_checks: List[str] = Field(default_factory=list, description="Actionable inspection steps recommended for human operators")


class EvidenceItemSummary(BaseModel):
    evidence_id: uuid.UUID
    evidence_type: str
    entity_type: str
    entity_id: uuid.UUID
    fingerprint_sha256: str
    verification_status: str  # VERIFIED, TAMPERED, UNVERIFIED
    details: Optional[Dict[str, Any]] = None


class FinancialExposure(BaseModel):
    leakage_amount: str
    recoverable_amount: str
    expected_amount: str
    actual_amount: str
    currency: str


class EvidenceBundlePayload(BaseModel):
    bundle_fingerprint: str
    exception_id: uuid.UUID
    detector_type: str
    exception_type: str
    current_status: str
    financial_exposure: FinancialExposure
    severity: str
    detection_run_id: uuid.UUID
    snapshot_id: Optional[uuid.UUID] = None
    snapshot_quality: Optional[str] = None
    evidence_items: List[EvidenceItemSummary]
    reviewer_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# API Request / Response Schemas
# ---------------------------------------------------------------------------

class InvestigationCreateRequest(BaseModel):
    idempotency_key: Optional[str] = Field(
        None,
        max_length=100,
        description="Optional client idempotency key to prevent duplicate runs"
    )
    force_refresh: bool = Field(
        False,
        description="If True, forces creation of a new investigation even if an immutable one exists for the latest run"
    )


class InvestigationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    exception_id: uuid.UUID
    detection_run_id: uuid.UUID
    idempotency_key: Optional[str] = None
    status: InvestigationStatus
    conclusion: InvestigationConclusion
    confidence: InvestigationConfidence
    summary: str
    evidence_bundle_fingerprint: str
    investigation_result: Optional[InvestigationResultContract] = None
    model_provider: str
    model_name: str
    prompt_version: str
    schema_version: str
    error_message: Optional[str] = None
    created_at: datetime


class EvidenceBundleResponse(BaseModel):
    evidence_bundle_fingerprint: str
    bundle_snapshot: Dict[str, Any]


class ClaimDraftCreateRequest(BaseModel):
    target_entity: Optional[str] = Field(
        None,
        description="Override counterparty name (e.g. RAZORPAY, HDFC_BANK). If omitted, inferred from exception."
    )
    notes: Optional[str] = Field(
        None,
        description="Optional instructions for claim draft generation"
    )


class ClaimDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    exception_id: uuid.UUID
    investigation_id: uuid.UUID
    detection_run_id: uuid.UUID
    draft_number: int
    status: ClaimDraftStatus
    dispute_amount: Decimal
    currency: str
    target_entity: str
    target_reference: str
    claim_summary: str
    supporting_facts: List[str]
    evidence_references: List[Dict[str, Any]]
    unresolved_questions: Optional[List[str]] = None
    required_attachments: Optional[List[str]] = None
    human_review_status: ClaimDraftReviewStatus
    disclaimer: str
    created_at: datetime
