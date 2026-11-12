import uuid
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    LeakageExceptionEvidence,
    LeakageRunEvidence,
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    DetectionRunStatus,
)
from app.models.forensic import (
    ForensicInvestigation,
    ForensicClaimDraft,
    InvestigationStatus,
    ClaimDraftStatus,
    ClaimDraftReviewStatus,
)
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.services.forensics.claim_draft_service import ClaimDraftService
from app.services.forensics.exceptions import InvalidInvestigationStateError, ResourceNotFoundError


def _seed_completed_investigation(db: Session):
    tenant = Tenant(name="T1", slug=f"t1-{uuid.uuid4().hex[:8]}")
    db.add(tenant)
    db.flush()

    run = LeakageDetectionRun(
        tenant_id=tenant.id,
        run_number=1,
        status=DetectionRunStatus.COMPLETED.value
    )
    db.add(run)
    db.flush()

    exc = LeakageException(
        tenant_id=tenant.id,
        detection_run_id=run.id,
        latest_detection_run_id=run.id,
        detector_type=DetectorType.UNCREDITED_SETTLEMENT.value,
        exception_type=LeakageExceptionType.UNCREDITED_SETTLEMENT.value,
        status=ExceptionStatus.OPEN.value,
        severity=ExceptionSeverity.CRITICAL.value,
        severity_reason="Settlement uncredited by bank after 72 hours",
        source_entity_type="canonical_settlements",
        source_entity_id=uuid.uuid4(),
        source_reference="set_hdfc_uncredited_99",
        gateway_name="HDFC_BANK",
        expected_amount=Decimal("450000.0000"),
        actual_amount=Decimal("0.0000"),
        leakage_amount=Decimal("450000.0000"),
        recoverable_amount=Decimal("450000.0000"),
        currency="INR",
        explanation="Bank statement missing settlement batch",
    )
    db.add(exc)
    db.flush()

    ev = LeakageExceptionEvidence(
        tenant_id=tenant.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="SETTLEMENT_BATCH",
        entity_type="canonical_settlements",
        entity_id=exc.source_entity_id,
        details={"settlement_id": "set_hdfc_uncredited_99", "amount": "450000.0000"}
    )
    db.add(ev)
    db.flush()

    db.add(LeakageRunEvidence(tenant_id=tenant.id, detection_run_id=run.id, evidence_id=ev.id))
    db.commit()

    inv = ForensicInvestigationService.create_investigation(db, tenant.id, exc.id)
    inv = ForensicInvestigationService.execute_investigation(db, inv.id)
    return tenant, run, exc, inv


def test_claim_draft_creation_success(db_session: Session):
    tenant, run, exc, inv = _seed_completed_investigation(db_session)

    draft = ClaimDraftService.create_claim_draft(
        db=db_session,
        tenant_id=tenant.id,
        investigation_id=inv.id,
        notes="Urgent escalation to bank branch manager"
    )

    assert draft.id is not None
    assert draft.status == ClaimDraftStatus.DRAFT.value
    # Financial amount is strictly copied without recalculation
    assert draft.dispute_amount == Decimal("450000.0000")
    assert draft.currency == "INR"
    assert draft.target_entity == "HDFC_BANK"
    assert draft.target_reference == "set_hdfc_uncredited_99"
    assert draft.draft_number == 1
    assert draft.human_review_status == ClaimDraftReviewStatus.PENDING_HUMAN_REVIEW.value
    assert "DRAFT — HUMAN REVIEW REQUIRED" in draft.disclaimer
    assert "Urgent escalation" in draft.claim_summary

    # Ensure exception status was NOT automatically modified
    assert exc.status == ExceptionStatus.OPEN.value


def test_claim_draft_version_preservation(db_session: Session):
    tenant, run, exc, inv = _seed_completed_investigation(db_session)

    draft1 = ClaimDraftService.create_claim_draft(
        db=db_session,
        tenant_id=tenant.id,
        investigation_id=inv.id
    )
    draft2 = ClaimDraftService.create_claim_draft(
        db=db_session,
        tenant_id=tenant.id,
        investigation_id=inv.id,
        notes="Second revision with additional remarks"
    )

    assert draft1.draft_number == 1
    assert draft2.draft_number == 2
    assert draft1.id != draft2.id


def test_claim_draft_fails_on_incomplete_investigation(db_session: Session):
    tenant, run, exc, inv = _seed_completed_investigation(db_session)

    # Revert investigation status to PENDING
    inv.status = InvestigationStatus.PENDING.value
    db_session.commit()

    with pytest.raises(InvalidInvestigationStateError, match="must be COMPLETED"):
        ClaimDraftService.create_claim_draft(
            db=db_session,
            tenant_id=tenant.id,
            investigation_id=inv.id
        )


def test_claim_draft_cross_tenant_access_blocked(db_session: Session):
    tenant, run, exc, inv = _seed_completed_investigation(db_session)

    other_tenant = Tenant(name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_tenant)
    db_session.commit()

    draft = ClaimDraftService.create_claim_draft(
        db=db_session,
        tenant_id=tenant.id,
        investigation_id=inv.id
    )

    with pytest.raises(ResourceNotFoundError):
        ClaimDraftService.get_claim_draft(
            db=db_session,
            tenant_id=other_tenant.id,
            draft_id=draft.id
        )
