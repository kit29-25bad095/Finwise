import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalPayment, CanonicalRefund
from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity
from app.services.leakage.refund_anomaly_detector import RefundAnomalyDetector


def seed_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="refunds.csv",
        file_hash_sha256="dummyhash_refunds",
        file_size_bytes=1024,
        total_rows=10,
        valid_rows=10,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


def test_refund_anomaly_duplicate_financial_execution(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Legitimate payment of ₹10,000
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_DUP_REF_001",
        captured_amount=Decimal("10000.0000"),
        status="captured",
        captured_at=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    # Two processed refund records with the exact same refund reference 'rfnd_DUP_999'
    r1 = CanonicalRefund(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_refund_id="rfnd_DUP_999",
        gateway_payment_id="pay_DUP_REF_001",
        refund_amount=Decimal("3000.0000"),
        status="processed",
        processed_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )
    r2 = CanonicalRefund(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        gateway_refund_id="rfnd_DUP_999",
        gateway_payment_id="pay_DUP_REF_001",
        refund_amount=Decimal("3000.0000"),
        status="processed",  # Duplicate financial execution!
        processed_at=datetime(2026, 11, 2, 10, 5, tzinfo=timezone.utc),
    )
    db_session.add_all([payment, r1, r2])
    db_session.commit()

    detector = RefundAnomalyDetector()
    findings = detector.detect(db_session, tenant_id)

    dup_findings = [f for f in findings if f.exception_type == LeakageExceptionType.DUPLICATE_REFUND]
    assert len(dup_findings) == 1
    f = dup_findings[0]
    assert f.leakage_amount == Decimal("3000.0000")
    assert f.recoverable_amount == Decimal("3000.0000")
    assert f.source_reference == "rfnd_DUP_999"
    assert len(f.evidence_items) == 2


def test_refund_anomaly_retry_record_not_flagged_as_duplicate(db_session: Session, seeded_entities: dict):
    """
    Distinguish legitimate retry records from actual duplicate financial transactions:
    1 failed attempt + 1 processed attempt is NOT a duplicate financial debit.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_RETRY_002",
        captured_amount=Decimal("5000.0000"),
        status="captured",
        captured_at=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("5000.0000"),
    )
    r1_failed = CanonicalRefund(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=3,
        gateway_refund_id="rfnd_RETRY_002",
        gateway_payment_id="pay_RETRY_002",
        refund_amount=Decimal("2000.0000"),
        status="failed",  # FAILED attempt
        processed_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )
    r2_success = CanonicalRefund(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=4,
        gateway_refund_id="rfnd_RETRY_002",
        gateway_payment_id="pay_RETRY_002",
        refund_amount=Decimal("2000.0000"),
        status="processed",  # SUCCESSFUL retry
        processed_at=datetime(2026, 11, 2, 10, 2, tzinfo=timezone.utc),
    )
    db_session.add_all([payment, r1_failed, r2_success])
    db_session.commit()

    detector = RefundAnomalyDetector()
    findings = detector.detect(db_session, tenant_id)

    dup_findings = [f for f in findings if f.exception_type == LeakageExceptionType.DUPLICATE_REFUND]
    assert len(dup_findings) == 0  # NOT a duplicate financial refund!


def test_refund_anomaly_excess_cumulative_refund(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Capture of ₹8,000
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=5,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_EXCESS_003",
        captured_amount=Decimal("8000.0000"),
        status="captured",
        captured_at=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("8000.0000"),
    )
    # 2 partial refunds totaling ₹9,500 (exceeding ₹8,000 capture by ₹1,500!)
    r1 = CanonicalRefund(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=5,
        gateway_refund_id="rfnd_PART_A",
        gateway_payment_id="pay_EXCESS_003",
        refund_amount=Decimal("5000.0000"),
        status="processed",
        processed_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )
    r2 = CanonicalRefund(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=6,
        gateway_refund_id="rfnd_PART_B",
        gateway_payment_id="pay_EXCESS_003",
        refund_amount=Decimal("4500.0000"),
        status="processed",
        processed_at=datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add_all([payment, r1, r2])
    db_session.commit()

    detector = RefundAnomalyDetector()
    findings = detector.detect(db_session, tenant_id)

    excess_findings = [f for f in findings if f.exception_type == LeakageExceptionType.EXCESS_REFUND]
    assert len(excess_findings) == 1
    f = excess_findings[0]
    assert f.expected_amount == Decimal("8000.0000")
    assert f.actual_amount == Decimal("9500.0000")
    assert f.leakage_amount == Decimal("1500.0000")
    assert f.recoverable_amount == Decimal("1500.0000")


def test_refund_anomaly_orphan_unauthorized_refund(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Processed refund referencing non-existent payment 'pay_GHOST_999'
    orphan_r = CanonicalRefund(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=7,
        gateway_refund_id="rfnd_ORPHAN_004",
        gateway_payment_id="pay_GHOST_999",
        refund_amount=Decimal("4000.0000"),
        status="processed",
        processed_at=datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add(orphan_r)
    db_session.commit()

    detector = RefundAnomalyDetector()
    findings = detector.detect(db_session, tenant_id)

    orphan_findings = [f for f in findings if f.exception_type == LeakageExceptionType.UNAUTHORIZED_REFUND]
    assert len(orphan_findings) == 1
    f = orphan_findings[0]
    assert f.leakage_amount == Decimal("4000.0000")
    assert f.recoverable_amount == Decimal("4000.0000")
    assert f.source_reference == "rfnd_ORPHAN_004"
