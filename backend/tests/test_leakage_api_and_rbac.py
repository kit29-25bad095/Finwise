import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalPayment
from app.models.leakage import (
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    LeakageDetectionRun,
    LeakageException,
    LeakageExceptionEvidence,
)
from app.services.leakage.detection_engine import DetectionEngine


def seed_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="api_test.csv",
        file_hash_sha256=f"hash_api_{uuid.uuid4().hex[:16]}",
        file_size_bytes=1024,
        total_rows=10,
        valid_rows=10,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


def seed_exception_with_evidence(db_session: Session, tenant_id: uuid.UUID) -> LeakageException:
    batch = seed_batch(db_session, tenant_id)

    run = LeakageDetectionRun(
        tenant_id=tenant_id,
        run_number=1,
        status="COMPLETED",
        is_active=True,
        total_captures_evaluated=5,
        total_settlements_evaluated=5,
        total_refunds_evaluated=2,
        exceptions_count=1,
        total_leakage_amount=Decimal("12500.0000"),
        total_potential_recovery=Decimal("12500.0000"),
    )
    db_session.add(run)
    db_session.flush()

    exc = LeakageException(
        tenant_id=tenant_id,
        detection_run_id=run.id,
        detector_type=DetectorType.MISSING_SETTLEMENT.value,
        exception_type=LeakageExceptionType.MISSING_SETTLEMENT.value,
        status=ExceptionStatus.OPEN.value,
        severity=ExceptionSeverity.HIGH.value,
        severity_reason="Payment capture unsettled past due date.",
        source_entity_type="canonical_payments",
        source_entity_id=uuid.uuid4(),
        source_reference="pay_API_TEST_001",
        expected_amount=Decimal("12500.0000"),
        actual_amount=Decimal("0.0000"),
        leakage_amount=Decimal("12500.0000"),
        recoverable_amount=Decimal("12500.0000"),
        currency="INR",
        calculation_breakdown={"due_date": "2026-11-04", "remaining_unsettled": "12500.0000"},
        explanation="Payment pay_API_TEST_001 remains unsettled after T+2 window.",
    )
    db_session.add(exc)
    db_session.flush()

    ev = LeakageExceptionEvidence(
        exception_id=exc.id,
        tenant_id=tenant_id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc.source_entity_id,
        source_batch_id=batch.id,
        source_row_index=1,
        details={"captured_amount": "12500.0000", "gateway_payment_id": "pay_API_TEST_001"}
    )
    db_session.add(ev)
    db_session.commit()
    return exc


def test_leakage_api_trigger_and_list_runs(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    # 1. Trigger detection run
    resp = client.post(
        "/api/v1/leakage/runs",
        headers=headers,
        json={"parameters": {"grace_period_days": 1}}
    )
    assert resp.status_code == 201
    run_data = resp.json()
    assert run_data["run_number"] >= 1
    run_id = run_data["id"]

    # 2. List runs
    resp_list = client.get("/api/v1/leakage/runs", headers=headers)
    assert resp_list.status_code == 200
    runs = resp_list.json()
    assert len(runs) >= 1
    assert any(r["id"] == run_id for r in runs)

    # 3. Get specific run
    resp_get = client.get(f"/api/v1/leakage/runs/{run_id}", headers=headers)
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == run_id


def test_leakage_api_list_exceptions_and_filters(client: TestClient, db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    headers = seeded_entities["headers_a_admin"]

    exc = seed_exception_with_evidence(db_session, tenant_id)

    # List all
    resp = client.get("/api/v1/leakage/exceptions", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(e["id"] == str(exc.id) for e in data)

    # Filter by detector_type
    resp_det = client.get("/api/v1/leakage/exceptions?detector_type=MISSING_SETTLEMENT", headers=headers)
    assert resp_det.status_code == 200
    assert len(resp_det.json()) >= 1

    # Filter by non-matching detector
    resp_nomatch = client.get("/api/v1/leakage/exceptions?detector_type=REFUND_ANOMALY", headers=headers)
    assert resp_nomatch.status_code == 200
    assert len(resp_nomatch.json()) == 0

    # Filter by status
    resp_status = client.get("/api/v1/leakage/exceptions?status=OPEN", headers=headers)
    assert resp_status.status_code == 200
    assert len(resp_status.json()) >= 1


def test_leakage_api_exception_evidence(client: TestClient, db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    headers = seeded_entities["headers_a_admin"]

    exc = seed_exception_with_evidence(db_session, tenant_id)

    # Get single exception
    resp = client.get(f"/api/v1/leakage/exceptions/{exc.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["source_reference"] == "pay_API_TEST_001"

    # Get evidence items
    resp_ev = client.get(f"/api/v1/leakage/exceptions/{exc.id}/evidence", headers=headers)
    assert resp_ev.status_code == 200
    ev_list = resp_ev.json()
    assert len(ev_list) == 1
    assert ev_list[0]["evidence_type"] == "PAYMENT_CAPTURE"
    assert ev_list[0]["details"]["gateway_payment_id"] == "pay_API_TEST_001"


def test_leakage_api_summary_metrics(client: TestClient, db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    headers = seeded_entities["headers_a_admin"]

    seed_exception_with_evidence(db_session, tenant_id)

    resp = client.get("/api/v1/leakage/summary", headers=headers)
    assert resp.status_code == 200
    summary = resp.json()
    assert Decimal(str(summary["total_leakage_amount"])) >= Decimal("12500.0000")
    assert summary["open_exceptions"] >= 1
    assert "MISSING_SETTLEMENT" in summary["breakdown_by_detector"]
    assert summary["breakdown_by_detector"]["MISSING_SETTLEMENT"]["count"] >= 1


def test_leakage_api_review_and_resolve_lifecycle(client: TestClient, db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    headers = seeded_entities["headers_a_admin"]

    exc = seed_exception_with_evidence(db_session, tenant_id)

    # 1. REVIEW: OPEN -> UNDER_REVIEW
    resp1 = client.post(
        f"/api/v1/leakage/exceptions/{exc.id}/review",
        headers=headers,
        json={"action": "REVIEW", "notes": "Auditing settlement batch logs."}
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == ExceptionStatus.UNDER_REVIEW.value

    # 2. CONFIRM: UNDER_REVIEW -> CONFIRMED
    resp2 = client.post(
        f"/api/v1/leakage/exceptions/{exc.id}/review",
        headers=headers,
        json={"action": "CONFIRM", "notes": "Confirmed gateway failed to initiate NEFT."}
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == ExceptionStatus.CONFIRMED.value

    # 3. Invalid action on CONFIRMED: cannot REVIEW
    resp_invalid = client.post(
        f"/api/v1/leakage/exceptions/{exc.id}/review",
        headers=headers,
        json={"action": "REVIEW", "notes": "Invalid backwards step."}
    )
    assert resp_invalid.status_code == 400

    # 4. RESOLVE: CONFIRMED -> RESOLVED
    resp3 = client.post(
        f"/api/v1/leakage/exceptions/{exc.id}/resolve",
        headers=headers,
        json={"action": "RESOLVE", "notes": "Razorpay credited missing amount manually."}
    )
    assert resp3.status_code == 200
    assert resp3.json()["status"] == ExceptionStatus.RESOLVED.value


def test_leakage_rbac_auditor_permissions(client: TestClient, db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    headers_auditor = seeded_entities["headers_a_auditor"]

    exc = seed_exception_with_evidence(db_session, tenant_id)

    # Auditor can READ runs
    resp_runs = client.get("/api/v1/leakage/runs", headers=headers_auditor)
    assert resp_runs.status_code == 200

    # Auditor can READ exceptions & evidence
    resp_exc = client.get("/api/v1/leakage/exceptions", headers=headers_auditor)
    assert resp_exc.status_code == 200

    resp_ev = client.get(f"/api/v1/leakage/exceptions/{exc.id}/evidence", headers=headers_auditor)
    assert resp_ev.status_code == 200

    # Auditor can READ summary
    resp_sum = client.get("/api/v1/leakage/summary", headers=headers_auditor)
    assert resp_sum.status_code == 200

    # Auditor CANNOT trigger run -> 403 Forbidden
    resp_post_run = client.post(
        "/api/v1/leakage/runs",
        headers=headers_auditor,
        json={"parameters": {}}
    )
    assert resp_post_run.status_code == 403

    # Auditor CANNOT review exception -> 403 Forbidden
    resp_review = client.post(
        f"/api/v1/leakage/exceptions/{exc.id}/review",
        headers=headers_auditor,
        json={"action": "REVIEW", "notes": "Unauthorized attempt"}
    )
    assert resp_review.status_code == 403

    # Auditor CANNOT resolve exception -> 403 Forbidden
    resp_resolve = client.post(
        f"/api/v1/leakage/exceptions/{exc.id}/resolve",
        headers=headers_auditor,
        json={"action": "RESOLVE", "notes": "Unauthorized attempt"}
    )
    assert resp_resolve.status_code == 403


def test_leakage_api_tenant_isolation(client: TestClient, db_session: Session, seeded_entities: dict):
    tenant_a_id = seeded_entities["tenant_a"].id
    headers_b = seeded_entities["headers_b_admin"]

    exc_a = seed_exception_with_evidence(db_session, tenant_a_id)

    # Tenant B requests Tenant A's exception -> 404 Not Found
    resp_get = client.get(f"/api/v1/leakage/exceptions/{exc_a.id}", headers=headers_b)
    assert resp_get.status_code == 404

    # Tenant B requests Tenant A's evidence -> 404 Not Found
    resp_ev = client.get(f"/api/v1/leakage/exceptions/{exc_a.id}/evidence", headers=headers_b)
    assert resp_ev.status_code == 404

    # Tenant B attempts to review Tenant A's exception -> 400 or 404 Not Found
    resp_review = client.post(
        f"/api/v1/leakage/exceptions/{exc_a.id}/review",
        headers=headers_b,
        json={"action": "CONFIRM", "notes": "Cross-tenant intrusion attempt"}
    )
    assert resp_review.status_code in (400, 404)
