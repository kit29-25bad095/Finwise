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
    InvestigationStatus,
    InvestigationConclusion,
    InvestigationConfidence,
)
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.services.forensics.llm_adapter import MockLLMAdapter
from app.workers.forensic_tasks import process_forensic_investigation_job


def _seed_exception_with_evidence(db: Session):
    tenant = Tenant(name="Acme Corp", slug=f"acme-{uuid.uuid4().hex[:8]}")
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
        detector_type=DetectorType.FEE_OVERCHARGE.value,
        exception_type=LeakageExceptionType.FEE_OVERCHARGE.value,
        status=ExceptionStatus.OPEN.value,
        severity=ExceptionSeverity.MEDIUM.value,
        severity_reason="Gateway fee exceeds contracted MDR by 0.5%",
        source_entity_type="canonical_payments",
        source_entity_id=uuid.uuid4(),
        source_reference="pay_fee_overcharge_001",
        gateway_name="RAZORPAY",
        expected_amount=Decimal("20.0000"),
        actual_amount=Decimal("25.0000"),
        leakage_amount=Decimal("5.0000"),
        recoverable_amount=Decimal("5.0000"),
        currency="INR",
        explanation="MDR contract specifies 2.0% fee; gateway charged 2.5%",
    )
    db.add(exc)
    db.flush()

    ev1 = LeakageExceptionEvidence(
        tenant_id=tenant.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc.source_entity_id,
        details={"payment_id": "pay_fee_overcharge_001", "gross_amount": "1000.0000"}
    )
    ev2 = LeakageExceptionEvidence(
        tenant_id=tenant.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="FEE_TIER",
        entity_type="fee_contracts",
        entity_id=uuid.uuid4(),
        details={"rate_percentage": "2.0000", "tier_name": "Standard Card MDR"}
    )
    db.add_all([ev1, ev2])
    db.flush()

    # Link run to evidence
    db.add_all([
        LeakageRunEvidence(tenant_id=tenant.id, detection_run_id=run.id, evidence_id=ev1.id),
        LeakageRunEvidence(tenant_id=tenant.id, detection_run_id=run.id, evidence_id=ev2.id),
    ])
    db.commit()

    return tenant, run, exc, ev1, ev2


def test_investigation_creation_and_idempotency(db_session: Session):
    tenant, run, exc, ev1, ev2 = _seed_exception_with_evidence(db_session)

    # 1. First creation with idempotency key
    inv1 = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        idempotency_key="idem-key-001"
    )
    assert inv1.status == InvestigationStatus.PENDING.value
    assert inv1.evidence_bundle_fingerprint is not None

    # 2. Duplicate creation with same idempotency key returns same instance
    inv2 = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        idempotency_key="idem-key-001"
    )
    assert inv2.id == inv1.id

    # 3. Snapshot reuse without force_refresh returns existing investigation
    inv3 = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        force_refresh=False
    )
    assert inv3.id == inv1.id

    # 4. Force refresh creates new investigation record
    inv4 = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        force_refresh=True
    )
    assert inv4.id != inv1.id


def test_investigation_execution_success(db_session: Session):
    tenant, run, exc, ev1, ev2 = _seed_exception_with_evidence(db_session)

    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id
    )

    custom_response = {
        "summary": "Forensic audit confirms gateway fee overcharge against contracted MDR.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Contractual Rate Discrepancy",
                "explanation": "Payment fee assessed at 2.5% while contracted tier mandates 2.0%.",
                "supporting_evidence_ids": [str(ev1.id), str(ev2.id)],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
                "confidence": "MEDIUM"
            }
        ],
        "verified_facts": [
            "Payment captured with INR 1000.00 gross amount",
            "Contracted rate tier specifies 2.0% fee",
        ],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": ["Review invoice settlement breakdown with Razorpay account manager"]
    }

    mock_adapter = MockLLMAdapter(predefined_response=custom_response)

    completed_inv = ForensicInvestigationService.execute_investigation(
        db=db_session,
        investigation_id=inv.id,
        adapter=mock_adapter
    )

    assert completed_inv.status == InvestigationStatus.COMPLETED.value
    assert completed_inv.conclusion == InvestigationConclusion.SUPPORTED.value
    assert completed_inv.confidence == InvestigationConfidence.MEDIUM.value
    assert completed_inv.investigation_result is not None
    assert len(completed_inv.investigation_result["hypotheses"]) == 1
    assert completed_inv.model_provider == "mock"


def test_investigation_blocks_on_tampered_evidence(db_session: Session):
    import json
    from sqlalchemy import text
    tenant, run, exc, ev1, ev2 = _seed_exception_with_evidence(db_session)

    # Tamper with an evidence item's details via raw SQL (simulating external database tampering)
    db_session.execute(
        text("UPDATE leakage_exception_evidence SET details = :details WHERE id = :id"),
        {"details": json.dumps({"payment_id": "TAMPERED_DETAILS_HACK"}), "id": ev1.id.hex}
    )
    db_session.commit()
    db_session.expire_all()

    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        force_refresh=True
    )

    completed_inv = ForensicInvestigationService.execute_investigation(
        db=db_session,
        investigation_id=inv.id,
        adapter=MockLLMAdapter()
    )

    assert completed_inv.status == InvestigationStatus.BLOCKED.value
    assert completed_inv.conclusion == InvestigationConclusion.INCONCLUSIVE.value
    assert completed_inv.confidence == InvestigationConfidence.LOW.value
    assert "blocked" in completed_inv.summary.lower()


def test_worker_task_execution(db_session: Session):
    tenant, run, exc, ev1, ev2 = _seed_exception_with_evidence(db_session)

    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id
    )

    result = process_forensic_investigation_job(str(inv.id))
    assert result["investigation_id"] == str(inv.id)
    assert result["status"] == InvestigationStatus.COMPLETED.value
