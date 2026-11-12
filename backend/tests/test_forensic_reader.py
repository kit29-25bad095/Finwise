import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    LeakageRunException,
    LeakageExceptionEvidence,
    LeakageRunEvidence,
    LeakageExceptionReview,
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    DetectionRunStatus,
    SnapshotQuality,
)
from app.models.canonical import CanonicalPayment
from app.models.reconciliation import FeeContract
from app.services.forensics.forensic_reader import LeakageForensicReader
from app.services.forensics.exceptions import ResourceNotFoundError


def _seed_basic_setup(db: Session):
    t1 = Tenant(name="Tenant 1", slug=f"t1-{uuid.uuid4().hex[:8]}")
    t2 = Tenant(name="Tenant 2", slug=f"t2-{uuid.uuid4().hex[:8]}")
    db.add_all([t1, t2])
    db.flush()

    run1 = LeakageDetectionRun(
        tenant_id=t1.id,
        run_number=1,
        status=DetectionRunStatus.COMPLETED.value
    )
    db.add(run1)
    db.flush()

    exc1 = LeakageException(
        tenant_id=t1.id,
        detection_run_id=run1.id,
        latest_detection_run_id=run1.id,
        detector_type=DetectorType.MISSING_SETTLEMENT.value,
        exception_type=LeakageExceptionType.MISSING_SETTLEMENT.value,
        status=ExceptionStatus.OPEN.value,
        severity=ExceptionSeverity.HIGH.value,
        severity_reason="Payment captured 5 days ago without settlement",
        source_entity_type="canonical_payments",
        source_entity_id=uuid.uuid4(),
        source_reference="pay_test_123",
        gateway_name="RAZORPAY",
        expected_amount=Decimal("1500.0000"),
        actual_amount=Decimal("0.0000"),
        leakage_amount=Decimal("1500.0000"),
        recoverable_amount=Decimal("1500.0000"),
        currency="INR",
        explanation="Missing settlement test",
    )
    db.add(exc1)
    db.flush()

    snapshot1 = LeakageRunException(
        tenant_id=t1.id,
        detection_run_id=run1.id,
        exception_id=exc1.id,
        observed_status=ExceptionStatus.OPEN.value,
        observed_severity=ExceptionSeverity.HIGH.value,
        observed_expected_amount=Decimal("1500.0000"),
        observed_actual_amount=Decimal("0.0000"),
        observed_leakage_amount=Decimal("1500.0000"),
        observed_recoverable_amount=Decimal("1500.0000"),
        explanation="Snapshot explanation",
        snapshot_quality=SnapshotQuality.VERIFIED_AT_EXECUTION.value
    )
    db.add(snapshot1)

    ev1 = LeakageExceptionEvidence(
        tenant_id=t1.id,
        exception_id=exc1.id,
        detection_run_id=run1.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=exc1.source_entity_id,
        details={"payment_id": "pay_test_123", "amount": "1500.0000"}
    )
    db.add(ev1)
    db.flush()

    run_ev = LeakageRunEvidence(
        tenant_id=t1.id,
        detection_run_id=run1.id,
        evidence_id=ev1.id
    )
    db.add(run_ev)

    rev1 = LeakageExceptionReview(
        tenant_id=t1.id,
        exception_id=exc1.id,
        from_status=ExceptionStatus.OPEN.value,
        to_status=ExceptionStatus.UNDER_REVIEW.value,
        action="FLAG_UNDER_REVIEW",
        notes="Reviewer opened ticket #456"
    )
    db.add(rev1)

    db.commit()
    return t1, t2, run1, exc1, snapshot1, ev1, rev1


def test_forensic_reader_get_exception_success(db_session: Session):
    t1, t2, run1, exc1, snapshot1, ev1, rev1 = _seed_basic_setup(db_session)
    fetched = LeakageForensicReader.get_exception(db_session, t1.id, exc1.id)
    assert fetched.id == exc1.id
    assert fetched.leakage_amount == Decimal("1500.0000")


def test_forensic_reader_cross_tenant_isolation(db_session: Session):
    t1, t2, run1, exc1, snapshot1, ev1, rev1 = _seed_basic_setup(db_session)
    # Tenant 2 attempting to read Tenant 1's exception must raise ResourceNotFoundError
    with pytest.raises(ResourceNotFoundError):
        LeakageForensicReader.get_exception(db_session, t2.id, exc1.id)


def test_forensic_reader_get_run_snapshot(db_session: Session):
    t1, t2, run1, exc1, snapshot1, ev1, rev1 = _seed_basic_setup(db_session)
    snap = LeakageForensicReader.get_run_snapshot(db_session, t1.id, exc1.id, run1.id)
    assert snap is not None
    assert snap.observed_leakage_amount == Decimal("1500.0000")
    assert snap.snapshot_quality == SnapshotQuality.VERIFIED_AT_EXECUTION.value


def test_forensic_reader_get_evidence_for_run(db_session: Session):
    t1, t2, run1, exc1, snapshot1, ev1, rev1 = _seed_basic_setup(db_session)
    ev_list = LeakageForensicReader.get_evidence_for_run(db_session, t1.id, exc1.id, run1.id)
    assert len(ev_list) == 1
    assert ev_list[0].id == ev1.id
    assert ev_list[0].fingerprint_sha256 is not None


def test_forensic_reader_get_reviewer_history(db_session: Session):
    t1, t2, run1, exc1, snapshot1, ev1, rev1 = _seed_basic_setup(db_session)
    reviews = LeakageForensicReader.get_reviewer_history(db_session, t1.id, exc1.id)
    assert len(reviews) == 1
    assert reviews[0].notes == "Reviewer opened ticket #456"
