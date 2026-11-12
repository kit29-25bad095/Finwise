import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
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
)
from app.core.security import get_password_hash, create_access_token
from app.core.rbac import Role
from app.services.forensics.investigation_service import ForensicInvestigationService


def _setup_api_tenant_and_users(db: Session):
    t1 = Tenant(name="API Tenant 1", slug=f"t1-api-{uuid.uuid4().hex[:8]}")
    t2 = Tenant(name="API Tenant 2", slug=f"t2-api-{uuid.uuid4().hex[:8]}")
    db.add_all([t1, t2])
    db.flush()

    # Users for Tenant 1
    u_admin = User(email="admin@t1.com", hashed_password=get_password_hash("pass123"), full_name="Admin T1")
    u_fm = User(email="fm@t1.com", hashed_password=get_password_hash("pass123"), full_name="FM T1")
    u_auditor = User(email="auditor@t1.com", hashed_password=get_password_hash("pass123"), full_name="Auditor T1")

    # User for Tenant 2
    u_t2_admin = User(email="admin@t2.com", hashed_password=get_password_hash("pass123"), full_name="Admin T2")

    db.add_all([u_admin, u_fm, u_auditor, u_t2_admin])
    db.flush()

    # Memberships
    m_admin = TenantMembership(tenant_id=t1.id, user_id=u_admin.id, role=Role.ADMIN.value)
    m_fm = TenantMembership(tenant_id=t1.id, user_id=u_fm.id, role=Role.FINANCE_MANAGER.value)
    m_auditor = TenantMembership(tenant_id=t1.id, user_id=u_auditor.id, role=Role.AUDITOR.value)
    m_t2 = TenantMembership(tenant_id=t2.id, user_id=u_t2_admin.id, role=Role.ADMIN.value)

    db.add_all([m_admin, m_fm, m_auditor, m_t2])
    db.flush()

    # Seed an exception for Tenant 1
    run = LeakageDetectionRun(tenant_id=t1.id, run_number=1, status=DetectionRunStatus.COMPLETED.value)
    db.add(run)
    db.flush()

    exc = LeakageException(
        tenant_id=t1.id,
        detection_run_id=run.id,
        latest_detection_run_id=run.id,
        detector_type=DetectorType.MISSING_SETTLEMENT.value,
        exception_type=LeakageExceptionType.MISSING_SETTLEMENT.value,
        status=ExceptionStatus.OPEN.value,
        severity=ExceptionSeverity.HIGH.value,
        severity_reason="Missing settlement",
        source_entity_type="canonical_payments",
        source_entity_id=uuid.uuid4(),
        source_reference="pay_api_test_01",
        gateway_name="RAZORPAY",
        expected_amount=Decimal("1200.0000"),
        actual_amount=Decimal("0.0000"),
        leakage_amount=Decimal("1200.0000"),
        recoverable_amount=Decimal("1200.0000"),
        currency="INR",
        explanation="Test explanation",
    )
    db.add(exc)
    db.flush()

    ev = LeakageExceptionEvidence(
        tenant_id=t1.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc.source_entity_id,
        details={"payment_id": "pay_api_test_01"}
    )
    db.add(ev)
    db.flush()
    db.add(LeakageRunEvidence(tenant_id=t1.id, detection_run_id=run.id, evidence_id=ev.id))
    db.commit()

    tokens = {
        "admin": create_access_token(subject=str(u_admin.id), tenant_id=str(t1.id), role=Role.ADMIN.value),
        "fm": create_access_token(subject=str(u_fm.id), tenant_id=str(t1.id), role=Role.FINANCE_MANAGER.value),
        "auditor": create_access_token(subject=str(u_auditor.id), tenant_id=str(t1.id), role=Role.AUDITOR.value),
        "t2_admin": create_access_token(subject=str(u_t2_admin.id), tenant_id=str(t2.id), role=Role.ADMIN.value),
    }

    return t1, t2, exc, tokens


def test_api_unauthenticated_request_rejected(client: TestClient, db_session: Session):
    t1, t2, exc, tokens = _setup_api_tenant_and_users(db_session)
    res = client.post(f"/api/v1/forensics/exceptions/{exc.id}/investigations", json={})
    assert res.status_code == 401


def test_api_create_investigation_rbac(client: TestClient, db_session: Session):
    t1, t2, exc, tokens = _setup_api_tenant_and_users(db_session)

    # 1. Auditor cannot trigger an investigation (403)
    res_auditor = client.post(
        f"/api/v1/forensics/exceptions/{exc.id}/investigations",
        json={"idempotency_key": "key-auditor"},
        headers={"Authorization": f"Bearer {tokens['auditor']}"}
    )
    assert res_auditor.status_code == 403

    # 2. Finance Manager can trigger an investigation (201)
    res_fm = client.post(
        f"/api/v1/forensics/exceptions/{exc.id}/investigations",
        json={"idempotency_key": "key-fm"},
        headers={"Authorization": f"Bearer {tokens['fm']}"}
    )
    assert res_fm.status_code == 201
    data = res_fm.json()
    assert data["exception_id"] == str(exc.id)
    assert "evidence_bundle_fingerprint" in data


def test_api_auditor_read_investigation_and_evidence(client: TestClient, db_session: Session):
    t1, t2, exc, tokens = _setup_api_tenant_and_users(db_session)

    # Admin creates and runs investigation
    inv = ForensicInvestigationService.create_investigation(db_session, t1.id, exc.id)
    inv = ForensicInvestigationService.execute_investigation(db_session, inv.id)

    # Auditor reads investigation
    res = client.get(
        f"/api/v1/forensics/investigations/{inv.id}",
        headers={"Authorization": f"Bearer {tokens['auditor']}"}
    )
    assert res.status_code == 200
    assert res.json()["id"] == str(inv.id)

    # Auditor reads immutable evidence bundle
    res_ev = client.get(
        f"/api/v1/forensics/investigations/{inv.id}/evidence",
        headers={"Authorization": f"Bearer {tokens['auditor']}"}
    )
    assert res_ev.status_code == 200
    assert "bundle_snapshot" in res_ev.json()
    assert res_ev.json()["evidence_bundle_fingerprint"] == inv.evidence_bundle_fingerprint


def test_api_claim_draft_endpoints_and_rbac(client: TestClient, db_session: Session):
    t1, t2, exc, tokens = _setup_api_tenant_and_users(db_session)

    inv = ForensicInvestigationService.create_investigation(db_session, t1.id, exc.id)
    inv = ForensicInvestigationService.execute_investigation(db_session, inv.id)

    # Auditor cannot create claim draft
    res_auditor = client.post(
        f"/api/v1/forensics/investigations/{inv.id}/claim-drafts",
        json={},
        headers={"Authorization": f"Bearer {tokens['auditor']}"}
    )
    assert res_auditor.status_code == 403

    # Admin creates claim draft
    res_admin = client.post(
        f"/api/v1/forensics/investigations/{inv.id}/claim-drafts",
        json={"notes": "Audited via API"},
        headers={"Authorization": f"Bearer {tokens['admin']}"}
    )
    assert res_admin.status_code == 201
    draft_data = res_admin.json()
    assert draft_data["status"] == "DRAFT"
    assert "DRAFT — HUMAN REVIEW REQUIRED" in draft_data["disclaimer"]

    # Auditor can read the created claim draft
    draft_id = draft_data["id"]
    res_read = client.get(
        f"/api/v1/forensics/claim-drafts/{draft_id}",
        headers={"Authorization": f"Bearer {tokens['auditor']}"}
    )
    assert res_read.status_code == 200
    assert res_read.json()["id"] == draft_id


def test_api_cross_tenant_isolation(client: TestClient, db_session: Session):
    t1, t2, exc, tokens = _setup_api_tenant_and_users(db_session)

    inv = ForensicInvestigationService.create_investigation(db_session, t1.id, exc.id)
    inv = ForensicInvestigationService.execute_investigation(db_session, inv.id)

    # Tenant 2 attempts to read Tenant 1's investigation -> must receive 404
    res_inv = client.get(
        f"/api/v1/forensics/investigations/{inv.id}",
        headers={"Authorization": f"Bearer {tokens['t2_admin']}"}
    )
    assert res_inv.status_code == 404

    # Tenant 2 attempts to trigger investigation on Tenant 1's exception -> must receive 404
    res_trigger = client.post(
        f"/api/v1/forensics/exceptions/{exc.id}/investigations",
        json={},
        headers={"Authorization": f"Bearer {tokens['t2_admin']}"}
    )
    assert res_trigger.status_code == 404
