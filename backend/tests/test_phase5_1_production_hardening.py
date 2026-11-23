import uuid
from decimal import Decimal
from unittest.mock import patch
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import get_password_hash, create_access_token
from app.core.rbac import Role
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.base import ImmutabilityViolationError
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
from app.services.forensics.evidence_validator import EvidenceValidator
from app.services.forensics.monitoring import ForensicMetricsCollector
from app.services.forensics.llm_adapter import MockLLMAdapter
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.services.forensics.claim_draft_service import ClaimDraftService
from app.services.leakage.evidence_hasher import serialize_canonical_value


def _seed_test_investigation_and_exception(db: Session):
    tenant = Tenant(name="Hardening Tenant", slug=f"hard-{uuid.uuid4().hex[:8]}")
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
        severity_reason="Fee overcharge detected",
        source_entity_type="canonical_payments",
        source_entity_id=uuid.uuid4(),
        source_reference="pay_hard_001",
        gateway_name="RAZORPAY",
        expected_amount=Decimal("20.0000"),
        actual_amount=Decimal("25.0000"),
        leakage_amount=Decimal("5.0000"),
        recoverable_amount=Decimal("5.0000"),
        currency="INR",
        explanation="Contract fee variance",
    )
    db.add(exc)
    db.flush()

    ev = LeakageExceptionEvidence(
        tenant_id=tenant.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc.source_entity_id,
        details={"payment_id": "pay_hard_001", "gross_amount": "1000.0000"}
    )
    db.add(ev)
    db.flush()

    db.add(LeakageRunEvidence(tenant_id=tenant.id, detection_run_id=run.id, evidence_id=ev.id))
    db.commit()

    return tenant, run, exc, ev


def test_production_environment_rejects_worker_fallback_sync():
    """Verify that in production, WORKER_FALLBACK_SYNC cannot be True."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=True,
            SECRET_KEY="production-secret-key-must-be-very-secure",
        )
    assert "WORKER_FALLBACK_SYNC must be False in production" in str(exc_info.value)


def test_development_allows_worker_fallback_sync():
    """Verify that in development or test, WORKER_FALLBACK_SYNC can be set."""
    s = Settings(
        ENVIRONMENT="development",
        WORKER_FALLBACK_SYNC=True,
    )
    assert s.WORKER_FALLBACK_SYNC is True


def test_pii_adversarial_preserves_financial_identifiers():
    """
    Ensure financial identifiers (UTRs, Payment IDs, Order IDs, ISO dates, Decimals)
    are strictly preserved without false positive redactions.
    """
    payload = {
        "bank_utr": "HDFCR5202611128912",
        "payment_id": "pay_Oz82K194Nal",
        "order_id": "ORD-89421",
        "date": "2026-11-12",
        "amount": Decimal("12500.00"),
        "narration": "NEFT Cr-HDFCR5202611128912-RAZORPAY SOFTWARE-ORD-89421",
    }
    redacted = EvidenceValidator.redact_pii(payload)

    assert redacted["bank_utr"] == "HDFCR5202611128912"
    assert redacted["payment_id"] == "pay_Oz82K194Nal"
    assert redacted["order_id"] == "ORD-89421"
    assert redacted["date"] == "2026-11-12"
    assert redacted["amount"] == Decimal("12500.00")
    assert "HDFCR5202611128912" in redacted["narration"]
    assert "ORD-89421" in redacted["narration"]


def test_pii_redacts_free_form_bank_accounts():
    """
    Ensure 9-18 digit standalone or explicit bank account numbers in free text
    are masked while preserving the last 4 digits.
    """
    payload = {
        "note1": "Transfer to account 50200012345678 approved by merchant",
        "note2": "Customer A/C: 98765432101234 credited",
        "phone": "+91 9876543210",
        "email": "audit@merchant.com",
    }
    redacted = EvidenceValidator.redact_pii(payload)

    assert "50200012345678" not in redacted["note1"]
    assert "*******5678" in redacted["note1"]
    assert "98765432101234" not in redacted["note2"]
    assert "*******1234" in redacted["note2"]
    assert redacted["email"] == "[REDACTED_EMAIL]"
    assert redacted["phone"] == "[REDACTED_PHONE]"


def test_canonical_serializer_rejects_floats_and_non_finite():
    """
    Financial safety rule: floats and non-finite numbers must be strictly rejected
    in evidence payloads.
    """
    with pytest.raises(TypeError, match="Floating-point value"):
        serialize_canonical_value(12.34)

    with pytest.raises(ValueError, match="Non-finite Decimal"):
        serialize_canonical_value(Decimal("Infinity"))

    with pytest.raises(ValueError, match="Non-finite Decimal"):
        serialize_canonical_value(Decimal("NaN"))


def test_operational_metrics_collector():
    """Verify that the ForensicMetricsCollector aggregates investigation counts and costs."""
    initial_summary = ForensicMetricsCollector.get_metrics_summary()
    assert "investigations" in initial_summary
    assert "started" in initial_summary["investigations"]
    assert "completed" in initial_summary["investigations"]

    ForensicMetricsCollector.record_investigation_started(tenant_id="tenant-123", model="mock-model")
    ForensicMetricsCollector.record_investigation_completed(
        tenant_id="tenant-123",
        model="mock-model",
        latency_ms=120.0,
        tokens=350,
        cost_usd=0.0005,
    )

    updated_summary = ForensicMetricsCollector.get_metrics_summary()
    assert updated_summary["investigations"]["started"] >= initial_summary["investigations"]["started"] + 1
    assert updated_summary["investigations"]["completed"] >= initial_summary["investigations"]["completed"] + 1


@pytest.mark.asyncio
async def test_llm_adapter_metadata_tracking():
    """Verify MockLLMAdapter returns execution_metadata including token counts and costs."""
    adapter = MockLLMAdapter()
    result = await adapter.generate_investigation(
        system_prompt="System instructions",
        user_prompt='{"detector_type": "FEE_OVERCHARGE", "evidence_items": [{"evidence_id": "ev-123"}]}',
    )
    metadata = result.get("_execution_metadata")
    assert metadata is not None
    assert metadata["total_tokens"] > 0
    assert metadata["latency_ms"] >= 0
    assert float(metadata["estimated_cost_usd"]) >= 0.0


# ---------------------------------------------------------------------------
# Fix 1: Forensic Immutability Tests
# ---------------------------------------------------------------------------

def test_investigation_immutable_after_terminal_status(db_session: Session):
    """
    Verify that once a ForensicInvestigation reaches a terminal state
    (COMPLETED, BLOCKED, FAILED), any subsequent ORM update is rejected.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    inv = ForensicInvestigationService.create_investigation(db_session, tenant.id, exc.id)

    # Transition to COMPLETED
    inv.status = InvestigationStatus.IN_PROGRESS.value
    db_session.commit()
    inv.status = InvestigationStatus.COMPLETED.value
    inv.summary = "Initial completed summary"
    db_session.commit()

    # Attempting to mutate summary after COMPLETED must raise ImmutabilityViolationError
    inv.summary = "Tampered summary"
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "Modifications to COMPLETED ForensicInvestigation" in str(exc_info.value)
    db_session.rollback()

    # Attempting to transition status out of COMPLETED must also raise ImmutabilityViolationError
    inv.status = InvestigationStatus.IN_PROGRESS.value
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "Modifications to COMPLETED ForensicInvestigation" in str(exc_info.value)
    db_session.rollback()


def test_investigation_immutable_core_attributes(db_session: Session):
    """
    Verify that core audit references (fingerprint, snapshot, tenant_id, exception_id)
    cannot be changed even while in PENDING status.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    inv = ForensicInvestigationService.create_investigation(db_session, tenant.id, exc.id)

    inv.evidence_bundle_fingerprint = "tampered_fingerprint_hash_00000000000000000000000000000000"
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "evidence_bundle_fingerprint" in str(exc_info.value)
    db_session.rollback()


def test_investigation_valid_lifecycle_transitions(db_session: Session):
    """
    Verify legitimate lifecycle transitions PENDING -> IN_PROGRESS -> COMPLETED succeed.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    inv = ForensicInvestigationService.create_investigation(db_session, tenant.id, exc.id)
    assert inv.status == InvestigationStatus.PENDING.value

    inv.status = InvestigationStatus.IN_PROGRESS.value
    db_session.commit()
    assert inv.status == InvestigationStatus.IN_PROGRESS.value

    inv.status = InvestigationStatus.COMPLETED.value
    inv.summary = "Completed successfully"
    db_session.commit()
    assert inv.status == InvestigationStatus.COMPLETED.value


def test_claim_draft_immutable_core_fields(db_session: Session):
    """
    Verify that core deterministic financial quantum and references in ForensicClaimDraft
    cannot be altered once created.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    inv = ForensicInvestigationService.create_investigation(db_session, tenant.id, exc.id)
    inv.status = InvestigationStatus.IN_PROGRESS.value
    db_session.commit()
    inv.status = InvestigationStatus.COMPLETED.value
    db_session.commit()

    draft = ClaimDraftService.create_claim_draft(db_session, tenant.id, inv.id)
    assert draft.dispute_amount == exc.recoverable_amount

    # Attempt to tamper with dispute amount
    draft.dispute_amount = Decimal("999999.0000")
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "dispute_amount" in str(exc_info.value)
    db_session.rollback()

    # Attempt to tamper with currency
    draft.currency = "USD"
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "currency" in str(exc_info.value)
    db_session.rollback()

    # Attempt to tamper with target reference
    draft.target_reference = "tampered_ref"
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "target_reference" in str(exc_info.value)
    db_session.rollback()


def test_claim_draft_review_lifecycle_allowed(db_session: Session):
    """
    Verify that human review status and review notes can be updated,
    but once ARCHIVED, modifications are permanently rejected.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    inv = ForensicInvestigationService.create_investigation(db_session, tenant.id, exc.id)
    inv.status = InvestigationStatus.IN_PROGRESS.value
    db_session.commit()
    inv.status = InvestigationStatus.COMPLETED.value
    db_session.commit()

    draft = ClaimDraftService.create_claim_draft(db_session, tenant.id, inv.id)

    # Legitimate human review update
    draft.human_review_status = ClaimDraftReviewStatus.REVIEWED_APPROVED.value
    draft.claim_summary = "Approved by senior financial auditor"
    db_session.commit()
    assert draft.human_review_status == ClaimDraftReviewStatus.REVIEWED_APPROVED.value

    # Legitimate archiving
    draft.status = ClaimDraftStatus.ARCHIVED.value
    db_session.commit()
    assert draft.status == ClaimDraftStatus.ARCHIVED.value

    # Subsequent update on ARCHIVED draft must be rejected
    draft.claim_summary = "Modified after archiving"
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "ARCHIVED" in str(exc_info.value)
    db_session.rollback()


def test_forensic_deletion_prohibited(db_session: Session):
    """
    Verify that hard deletion of ForensicInvestigation or ForensicClaimDraft
    is strictly prohibited.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    inv = ForensicInvestigationService.create_investigation(db_session, tenant.id, exc.id)
    inv.status = InvestigationStatus.IN_PROGRESS.value
    db_session.commit()
    inv.status = InvestigationStatus.COMPLETED.value
    db_session.commit()

    draft = ClaimDraftService.create_claim_draft(db_session, tenant.id, inv.id)

    db_session.delete(draft)
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "Deletions of ForensicClaimDraft" in str(exc_info.value)
    db_session.rollback()

    db_session.delete(inv)
    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.commit()
    assert "Deletions of ForensicInvestigation" in str(exc_info.value)
    db_session.rollback()


# ---------------------------------------------------------------------------
# Fix 2: Tenant-Scoped Metrics Tests
# ---------------------------------------------------------------------------

def test_tenant_scoped_metrics_isolation():
    """
    Verify that ForensicMetricsCollector strictly partitions metrics by tenant.
    """
    ForensicMetricsCollector.reset_metrics_for_testing()

    t_alpha = "tenant-alpha"
    t_beta = "tenant-beta"

    # Record metrics for Tenant Alpha
    ForensicMetricsCollector.record_investigation_started(t_alpha, "mock-v1")
    ForensicMetricsCollector.record_investigation_started(t_alpha, "mock-v1")
    ForensicMetricsCollector.record_investigation_completed(
        tenant_id=t_alpha,
        model="mock-v1",
        latency_ms=150.0,
        tokens=600,
        cost_usd=0.0012,
        conclusion="SUPPORTED",
        confidence="HIGH",
    )

    # Record metrics for Tenant Beta
    ForensicMetricsCollector.record_investigation_started(t_beta, "mock-v1")
    ForensicMetricsCollector.record_investigation_failed(t_beta, "TimeoutError")
    ForensicMetricsCollector.record_investigation_blocked(t_beta, "integrity_failure")

    # Inspect Alpha's summary
    alpha_summary = ForensicMetricsCollector.get_tenant_metrics_summary(t_alpha)
    assert alpha_summary["tenant_id"] == t_alpha
    assert alpha_summary["investigations"]["started"] == 2
    assert alpha_summary["investigations"]["completed"] == 1
    assert alpha_summary["investigations"]["failed"] == 0
    assert alpha_summary["investigations"]["blocked"] == 0
    assert alpha_summary["ai_consumption"]["total_tokens_consumed"] == 600
    assert alpha_summary["ai_consumption"]["estimated_cost_usd"] == 0.0012

    # Inspect Beta's summary
    beta_summary = ForensicMetricsCollector.get_tenant_metrics_summary(t_beta)
    assert beta_summary["tenant_id"] == t_beta
    assert beta_summary["investigations"]["started"] == 1
    assert beta_summary["investigations"]["completed"] == 0
    assert beta_summary["investigations"]["failed"] == 1
    assert beta_summary["investigations"]["blocked"] == 1
    assert beta_summary["ai_consumption"]["total_tokens_consumed"] == 0
    assert beta_summary["ai_consumption"]["estimated_cost_usd"] == 0.0

    # Ensure queue depth is reported in both
    assert "worker_queue" in alpha_summary
    assert "worker_queue" in beta_summary


def test_api_metrics_endpoint_tenant_isolation(client: TestClient, db_session: Session):
    """
    Verify GET /api/v1/forensics/metrics returns only the authenticated tenant's metrics.
    """
    ForensicMetricsCollector.reset_metrics_for_testing()

    t1 = Tenant(name="Metrics T1", slug=f"m-t1-{uuid.uuid4().hex[:8]}")
    t2 = Tenant(name="Metrics T2", slug=f"m-t2-{uuid.uuid4().hex[:8]}")
    db_session.add_all([t1, t2])
    db_session.flush()

    u1 = User(email="admin@m-t1.com", hashed_password=get_password_hash("pass"), full_name="Admin T1")
    u2 = User(email="admin@m-t2.com", hashed_password=get_password_hash("pass"), full_name="Admin T2")
    db_session.add_all([u1, u2])
    db_session.flush()

    m1 = TenantMembership(tenant_id=t1.id, user_id=u1.id, role=Role.ADMIN.value)
    m2 = TenantMembership(tenant_id=t2.id, user_id=u2.id, role=Role.ADMIN.value)
    db_session.add_all([m1, m2])
    db_session.commit()

    token1 = create_access_token(subject=str(u1.id), tenant_id=str(t1.id), role=Role.ADMIN.value)
    token2 = create_access_token(subject=str(u2.id), tenant_id=str(t2.id), role=Role.ADMIN.value)

    # Record 5 completions for T1, 1 failure for T2
    for _ in range(5):
        ForensicMetricsCollector.record_investigation_started(str(t1.id), "mock-v1")
        ForensicMetricsCollector.record_investigation_completed(str(t1.id), "mock-v1", 100.0, 50, 0.0001)

    ForensicMetricsCollector.record_investigation_started(str(t2.id), "mock-v1")
    ForensicMetricsCollector.record_investigation_failed(str(t2.id), "Error")

    # Request as T1 Admin
    res1 = client.get("/api/v1/forensics/metrics", headers={"Authorization": f"Bearer {token1}"})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["tenant_id"] == str(t1.id)
    assert data1["investigations"]["completed"] == 5
    assert data1["investigations"]["failed"] == 0

    # Request as T2 Admin
    res2 = client.get("/api/v1/forensics/metrics", headers={"Authorization": f"Bearer {token2}"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["tenant_id"] == str(t2.id)
    assert data2["investigations"]["completed"] == 0
    assert data2["investigations"]["failed"] == 1


# ---------------------------------------------------------------------------
# Fix 3: Production Config Validation Tests
# ---------------------------------------------------------------------------

def test_production_config_rejects_weak_or_default_secret_key():
    """Verify that in production, weak or default SECRET_KEY is rejected without leaking the key."""
    # Test short key (< 32 chars)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=False,
            SECRET_KEY="short-secret",
            DATABASE_URL="postgresql://user:pass@localhost:5432/finora",
            SYNC_DATABASE_URL="postgresql://user:pass@localhost:5432/finora",
        )
    err = str(exc_info.value)
    assert "SECRET_KEY of at least 32 characters is required in production" in err
    assert "short-secret" not in err  # Secret must NOT be leaked in error

    # Test default placeholder key
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=False,
            SECRET_KEY="finora-super-secure-production-ready-jwt-secret-key-32-chars-min",
            DATABASE_URL="postgresql://user:pass@localhost:5432/finora",
            SYNC_DATABASE_URL="postgresql://user:pass@localhost:5432/finora",
        )
    err = str(exc_info.value)
    assert "A non-default SECRET_KEY" in err


def test_production_config_rejects_sqlite():
    """Verify that in production, SQLite database URLs are strictly rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=False,
            SECRET_KEY="valid-and-strong-production-secret-key-32-bytes",
            DATABASE_URL="sqlite:///./finora.db",
            SYNC_DATABASE_URL="sqlite:///./finora.db",
        )
    assert "PostgreSQL is required in production; SQLite is strictly prohibited" in str(exc_info.value)


def test_production_config_rejects_missing_gemini_api_key():
    """Verify that in production when AI_PROVIDER is gemini, AI_API_KEY is required."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=False,
            SECRET_KEY="valid-and-strong-production-secret-key-32-bytes",
            DATABASE_URL="postgresql://user:pass@localhost:5432/finora",
            SYNC_DATABASE_URL="postgresql://user:pass@localhost:5432/finora",
            AI_PROVIDER="gemini",
            AI_API_KEY=None,
        )
    assert "AI_API_KEY is required in production when AI_PROVIDER is 'gemini'" in str(exc_info.value)


def test_production_config_accepts_valid_settings():
    """Verify valid production settings pass validation successfully."""
    s = Settings(
        ENVIRONMENT="production",
        WORKER_FALLBACK_SYNC=False,
        SECRET_KEY="valid-and-strong-production-secret-key-32-bytes",
        DATABASE_URL="postgresql://finora_user:secure_pwd@db.prod:5432/finora_prod",
        SYNC_DATABASE_URL="postgresql://finora_user:secure_pwd@db.prod:5432/finora_prod",
        AI_PROVIDER="gemini",
        AI_API_KEY="AIzaSyDummyProductionValidKey12345",
    )
    assert s.ENVIRONMENT == "production"
    assert s.WORKER_FALLBACK_SYNC is False


# ---------------------------------------------------------------------------
# Fix 4: Worker Terminal-State Guard Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_guard_skips_terminal_investigation(db_session: Session):
    """
    Verify that execute_investigation_async skips execution if the investigation
    is already in COMPLETED, BLOCKED, or FAILED status, without modifying state
    or raising immutability violations.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    inv = ForensicInvestigationService.create_investigation(db_session, tenant.id, exc.id)

    # Complete it first
    inv.status = InvestigationStatus.IN_PROGRESS.value
    db_session.commit()
    inv.status = InvestigationStatus.COMPLETED.value
    inv.summary = "Original completed summary"
    db_session.commit()

    # Re-executing already COMPLETED investigation should return immediately
    result = await ForensicInvestigationService.execute_investigation_async(
        db=db_session,
        investigation_id=inv.id,
        adapter=MockLLMAdapter(),
    )
    assert result.id == inv.id
    assert result.status == InvestigationStatus.COMPLETED.value
    assert result.summary == "Original completed summary"


# ---------------------------------------------------------------------------
# Fix 5: Safe API Error Handling Tests
# ---------------------------------------------------------------------------

def test_api_create_investigation_safe_error_handling_on_queue_failure(client: TestClient, db_session: Session):
    """
    Verify that if background queue dispatch fails, the endpoint returns HTTP 503
    with a generic, sanitized error message without leaking internal exceptions.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    u_admin = User(email=f"admin-{uuid.uuid4().hex[:6]}@t.com", hashed_password=get_password_hash("pass"), full_name="Admin")
    db_session.add(u_admin)
    db_session.flush()
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=u_admin.id, role=Role.ADMIN.value))
    db_session.commit()

    token = create_access_token(subject=str(u_admin.id), tenant_id=str(tenant.id), role=Role.ADMIN.value)

    with patch("app.api.v1.forensic.enqueue_job", side_effect=RuntimeError("Redis connection refused on redis://pass@internal.redis:6379")):
        res = client.post(
            f"/api/v1/forensics/exceptions/{exc.id}/investigations",
            json={},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail == "Background worker queue is currently unavailable."
    assert "internal.redis" not in detail
    assert "pass@" not in detail


def test_api_create_investigation_safe_error_handling_on_unexpected_error(client: TestClient, db_session: Session):
    """
    Verify that unexpected server errors return HTTP 500 with generic sanitized detail.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    u_admin = User(email=f"admin-{uuid.uuid4().hex[:6]}@t.com", hashed_password=get_password_hash("pass"), full_name="Admin")
    db_session.add(u_admin)
    db_session.flush()
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=u_admin.id, role=Role.ADMIN.value))
    db_session.commit()

    token = create_access_token(subject=str(u_admin.id), tenant_id=str(tenant.id), role=Role.ADMIN.value)

    with patch("app.api.v1.forensic.ForensicInvestigationService.create_investigation", side_effect=Exception("Database driver internal crash: connection closed")):
        res = client.post(
            f"/api/v1/forensics/exceptions/{exc.id}/investigations",
            json={},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert res.status_code == 500
    detail = res.json()["detail"]
    assert detail == "Failed to initiate investigation due to an internal server error."
    assert "Database driver" not in detail


def test_api_create_claim_draft_safe_error_handling_on_unexpected_error(client: TestClient, db_session: Session):
    """
    Verify that unexpected errors generating claim drafts return HTTP 500 with sanitized detail.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    u_admin = User(email=f"admin-{uuid.uuid4().hex[:6]}@t.com", hashed_password=get_password_hash("pass"), full_name="Admin")
    db_session.add(u_admin)
    db_session.flush()
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=u_admin.id, role=Role.ADMIN.value))
    db_session.commit()

    token = create_access_token(subject=str(u_admin.id), tenant_id=str(tenant.id), role=Role.ADMIN.value)

    inv = ForensicInvestigationService.create_investigation(db_session, tenant.id, exc.id)
    inv.status = InvestigationStatus.IN_PROGRESS.value
    db_session.commit()
    inv.status = InvestigationStatus.COMPLETED.value
    db_session.commit()

    with patch("app.api.v1.forensic.ClaimDraftService.create_claim_draft", side_effect=Exception("Draft generator traceback with internal query info")):
        res = client.post(
            f"/api/v1/forensics/investigations/{inv.id}/claim-drafts",
            json={"target_entity": "RAZORPAY"},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert res.status_code == 500
    detail = res.json()["detail"]
    assert detail == "Failed to generate claim draft due to an internal server error."
    assert "Draft generator traceback" not in detail
