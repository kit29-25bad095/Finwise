import uuid
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    LeakageExceptionEvidence,
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    DetectionRunStatus,
)
from app.services.forensics.evidence_validator import EvidenceValidator
from app.services.forensics.evidence_bundle_builder import EvidenceBundleBuilder
from app.services.leakage.evidence_hasher import serialize_canonical_value, canonical_json_dumps


def _seed_test_exception(db_session: Session, tenant: Tenant):
    run = LeakageDetectionRun(
        tenant_id=tenant.id,
        run_number=1,
        status=DetectionRunStatus.COMPLETED.value
    )
    db_session.add(run)
    db_session.flush()

    exc = LeakageException(
        tenant_id=tenant.id,
        detection_run_id=run.id,
        latest_detection_run_id=run.id,
        detector_type=DetectorType.MISSING_SETTLEMENT.value,
        exception_type=LeakageExceptionType.MISSING_SETTLEMENT.value,
        status=ExceptionStatus.OPEN.value,
        severity=ExceptionSeverity.HIGH.value,
        severity_reason="Test exception for evidence verification",
        source_entity_type="canonical_payments",
        source_entity_id=uuid.uuid4(),
        source_reference="pay_evidence_test_123",
        gateway_name="RAZORPAY",
        expected_amount=Decimal("5000.0000"),
        actual_amount=Decimal("0.0000"),
        leakage_amount=Decimal("5000.0000"),
        recoverable_amount=Decimal("5000.0000"),
        currency="INR",
        explanation="Missing settlement test",
    )
    db_session.add(exc)
    db_session.flush()
    return run, exc


def test_evidence_fingerprint_verification_success(db_session: Session):
    tenant = Tenant(name="T1", slug=f"t1-{uuid.uuid4().hex[:8]}")
    db_session.add(tenant)
    db_session.flush()
    run, exc = _seed_test_exception(db_session, tenant)

    ev = LeakageExceptionEvidence(
        tenant_id=tenant.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc.source_entity_id,
        details={"payment_id": "pay_valid_123", "amount": "100.0000"}
    )
    db_session.add(ev)
    db_session.flush()

    status, reason = EvidenceValidator.verify_evidence_fingerprint(
        evidence=ev,
        expected_tenant_id=tenant.id,
        expected_exception_id=exc.id
    )
    assert status == "VERIFIED"
    assert reason is None


def test_tampered_evidence_fingerprint_rejection(db_session: Session):
    tenant = Tenant(name="T1", slug=f"t1-{uuid.uuid4().hex[:8]}")
    db_session.add(tenant)
    db_session.flush()
    run, exc = _seed_test_exception(db_session, tenant)

    ev = LeakageExceptionEvidence(
        tenant_id=tenant.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc.source_entity_id,
        details={"payment_id": "pay_valid_123", "amount": "100.0000"}
    )
    # Manually tamper with details in memory before validation
    ev.details = {"payment_id": "pay_TAMPERED_999", "amount": "9999.0000"}

    status, reason = EvidenceValidator.verify_evidence_fingerprint(
        evidence=ev,
        expected_tenant_id=tenant.id,
        expected_exception_id=exc.id
    )
    assert status == "TAMPERED"
    assert "fingerprint mismatch" in reason.lower()


def test_evidence_wrong_tenant_rejection(db_session: Session):
    tenant1 = Tenant(name="T1", slug=f"t1-{uuid.uuid4().hex[:8]}")
    tenant2 = Tenant(name="T2", slug=f"t2-{uuid.uuid4().hex[:8]}")
    db_session.add_all([tenant1, tenant2])
    db_session.flush()
    run, exc = _seed_test_exception(db_session, tenant1)

    ev = LeakageExceptionEvidence(
        tenant_id=tenant1.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc.source_entity_id,
        details={"payment_id": "pay_123"}
    )

    status, reason = EvidenceValidator.verify_evidence_fingerprint(
        evidence=ev,
        expected_tenant_id=tenant2.id,  # Expecting tenant 2
        expected_exception_id=exc.id
    )
    assert status == "TAMPERED"
    assert "tenant_id" in reason


def test_deterministic_bundle_fingerprint_reproducibility(db_session: Session):
    tenant = Tenant(name="T1", slug=f"t1-{uuid.uuid4().hex[:8]}")
    db_session.add(tenant)
    db_session.flush()
    run, exc = _seed_test_exception(db_session, tenant)

    ev = LeakageExceptionEvidence(
        tenant_id=tenant.id,
        exception_id=exc.id,
        detection_run_id=run.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc.source_entity_id,
        details={"gateway_id": "pay_123"}
    )
    db_session.add(ev)
    db_session.flush()

    bundle1, fp1, all_v1 = EvidenceBundleBuilder.build_bundle(
        exception=exc,
        run_id=exc.detection_run_id,
        snapshot=None,
        evidence_items=[ev],
        reviewer_notes="Some note"
    )

    bundle2, fp2, all_v2 = EvidenceBundleBuilder.build_bundle(
        exception=exc,
        run_id=exc.detection_run_id,
        snapshot=None,
        evidence_items=[ev],
        reviewer_notes="Some note"
    )

    assert fp1 == fp2
    assert all_v1 is True
    assert all_v2 is True
    assert bundle1["financial_exposure"]["leakage_amount"] == "5000.0000"


def test_canonical_serializer_float_rejection():
    with pytest.raises(TypeError, match="Floating-point value"):
        serialize_canonical_value(123.45)


def test_canonical_serializer_non_finite_rejection():
    with pytest.raises(ValueError, match="Non-finite Decimal"):
        serialize_canonical_value(Decimal("NaN"))

    with pytest.raises(ValueError, match="Non-finite Decimal"):
        serialize_canonical_value(Decimal("Infinity"))


def test_pii_minimization_redacts_sensitive_fields():
    raw_payload = {
        "customer_email": "john.doe@example.com",
        "phone_number": "+91-9876543210",
        "customer_name": "John Doe",
        "bank_account_number": "123456789012",
        "api_secret": "sk_test_super_secret_token_12345",
        "notes": "Customer reached out via support@company.org regarding payment"
    }

    redacted = EvidenceValidator.redact_pii(raw_payload)

    assert redacted["customer_email"] == "[REDACTED_EMAIL]"
    assert redacted["phone_number"] == "[REDACTED_PHONE]"
    assert redacted["customer_name"] == "[REDACTED_NAME]"
    assert redacted["bank_account_number"] == "*******9012"
    assert redacted["api_secret"] == "[REDACTED_SECRET]"
    assert "[REDACTED_EMAIL]" in redacted["notes"]
    assert "john.doe@example.com" not in str(redacted)
