import uuid
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
import pytest
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.tenant import Tenant
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalPayment, CanonicalSettlement, CanonicalBankTransaction
from app.models.reconciliation import FeeContract, FeeScheduleTier
from app.models.leakage import (
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    DetectionRunStatus,
    LeakageDetectionRun,
    LeakageException,
)
from app.services.leakage.detection_engine import DetectionEngine


def seed_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="transactions.csv",
        file_hash_sha256=f"hash_{uuid.uuid4().hex[:16]}",
        file_size_bytes=2048,
        total_rows=20,
        valid_rows=20,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


def test_detection_engine_full_run_with_multiple_detectors(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    # 1. Setup contract: 2% fee, 18% GST on credit cards
    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Standard Card Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(contract)
    db_session.flush()

    tier = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.020000"),
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(tier)

    # 2. Payment with fee overcharge: expected fee ₹200 + tax ₹36 = ₹236. Reported fee ₹350 + tax ₹63 = ₹413
    p1 = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_ENGINE_OVERCHARGE",
        order_reference="ORD-ENG-1",
        payment_method="card",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("350.0000"),
        reported_tax=Decimal("63.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=1),
        unallocated_balance=Decimal("0.0000"),
        raw_source_data={"card_type": "credit"},
    )

    # 3. Old captured payment unsettled: ₹15,000 (past T+2)
    p2 = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_ENGINE_UNSETTLED",
        order_reference="ORD-ENG-2",
        payment_method="card",
        captured_amount=Decimal("15000.0000"),
        reported_fee=Decimal("300.0000"),
        reported_tax=Decimal("54.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("15000.0000"),
        raw_source_data={"card_type": "credit"},
    )
    db_session.add_all([p1, p2])
    db_session.commit()

    # Execute full engine run
    engine = DetectionEngine()
    run = engine.run_detection(
        db=db_session,
        tenant_id=tenant_id,
        triggered_by_user_id=admin_id,
        parameters={"grace_period_days": 1}
    )

    assert run.status == DetectionRunStatus.COMPLETED
    assert run.is_active is True
    assert run.run_number == 1
    assert run.exceptions_count >= 2
    assert run.total_leakage_amount > Decimal("0.0000")
    assert run.total_potential_recovery > Decimal("0.0000")

    # Verify exceptions stored in database
    exceptions = db_session.execute(
        select(LeakageException).where(LeakageException.tenant_id == tenant_id)
    ).scalars().all()

    assert len(exceptions) == run.exceptions_count
    types = {e.exception_type for e in exceptions}
    assert LeakageExceptionType.FEE_OVERCHARGE in types
    assert LeakageExceptionType.MISSING_SETTLEMENT in types


def test_detection_engine_idempotency_rerun_preserves_review_status(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Setup payment with missing settlement
    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_IDEMP_001",
        payment_method="card",
        captured_amount=Decimal("25000.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=12),
        unallocated_balance=Decimal("25000.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()

    # Run 1
    run1 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)
    assert run1.run_number == 1
    assert run1.is_active is True

    # Get exception and submit review to UNDER_REVIEW
    exc = db_session.execute(
        select(LeakageException).where(
            LeakageException.tenant_id == tenant_id,
            LeakageException.source_reference == "pay_IDEMP_001"
        )
    ).scalar_one()
    assert exc.status == ExceptionStatus.OPEN.value

    updated_exc = engine.review_exception(
        db=db_session,
        exception_id=exc.id,
        tenant_id=tenant_id,
        reviewer_id=admin_id,
        action="REVIEW",
        notes="Contacted Razorpay nodal desk regarding delayed capture payout."
    )
    assert updated_exc.status == ExceptionStatus.UNDER_REVIEW.value

    # Run 2 (Rerun on unchanged data)
    run2 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)
    assert run2.run_number == 2
    assert run2.is_active is True

    # Run 1 should be deactivated
    db_session.refresh(run1)
    assert run1.is_active is False

    # Check total exception count in DB: MUST NOT DUPLICATE!
    all_exceptions = db_session.execute(
        select(LeakageException).where(LeakageException.tenant_id == tenant_id)
    ).scalars().all()
    assert len(all_exceptions) == 1

    # Exception status MUST still be UNDER_REVIEW (preserved from human review!)
    reloaded_exc = all_exceptions[0]
    assert reloaded_exc.status == ExceptionStatus.UNDER_REVIEW.value
    # Group A2: Origin run ID is preserved; latest run ID is updated
    assert reloaded_exc.detection_run_id == run1.id
    assert reloaded_exc.latest_detection_run_id == run2.id


def test_detection_engine_prohibits_auto_resolve_without_clearing_proof(db_session: Session, seeded_entities: dict):
    """
    AUDIT-P4-006 & Group A2 Policy: MISSING_SETTLEMENT cannot automatically resolve
    even if unallocated_balance reaches zero. It must remain OPEN with
    ABSENT_WITHOUT_CLEARING_EVIDENCE until verified by human review.
    """
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Capture 10 days ago, initially unsettled
    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_RESOLVE_001",
        payment_method="card",
        captured_amount=Decimal("8000.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("8000.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()
    run1 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    exc = db_session.execute(
        select(LeakageException).where(
            LeakageException.tenant_id == tenant_id,
            LeakageException.source_reference == "pay_RESOLVE_001"
        )
    ).scalar_one()
    assert exc.status == ExceptionStatus.OPEN.value
    assert exc.detection_run_id == run1.id

    # Simulated order allocation: unallocated balance becomes 0
    p.unallocated_balance = Decimal("0.0000")
    db_session.add(p)
    db_session.commit()

    # Rerun detection: detector no longer reports it, but auto-resolution is prohibited
    run2 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    db_session.refresh(exc)
    # MUST REMAIN OPEN: payment unallocated balance is not settlement proof!
    assert exc.status == ExceptionStatus.OPEN.value
    assert exc.detection_run_id == run1.id
    assert exc.latest_detection_run_id == run2.id
    assert exc.calculation_breakdown.get("run_evaluation_status") == "ABSENT_WITHOUT_CLEARING_EVIDENCE"

    # Authorized human review confirms then resolves the exception
    engine.review_exception(
        db=db_session,
        exception_id=exc.id,
        tenant_id=tenant_id,
        reviewer_id=admin_id,
        action="CONFIRM",
        notes="Confirmed exception before manual clearing verification."
    )
    resolved_exc = engine.review_exception(
        db=db_session,
        exception_id=exc.id,
        tenant_id=tenant_id,
        reviewer_id=admin_id,
        action="RESOLVE",
        notes="Verified payment cleared via external bank credit advice."
    )
    assert resolved_exc.status == ExceptionStatus.RESOLVED.value
    assert "cleared" in resolved_exc.resolution_notes.lower()


def test_detection_engine_tenant_isolation(db_session: Session, seeded_entities: dict):
    tenant_a_id = seeded_entities["tenant_a"].id
    tenant_b_id = seeded_entities["tenant_b"].id
    admin_a_id = seeded_entities["admin_a"].id
    admin_b_id = seeded_entities["admin_b"].id

    batch_a = seed_batch(db_session, tenant_a_id)

    # Seed an unsettled capture ONLY for Tenant A
    p_a = CanonicalPayment(
        tenant_id=tenant_a_id,
        batch_id=batch_a.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_TENANT_A_LEAK",
        payment_method="upi",
        captured_amount=Decimal("12000.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("12000.0000"),
    )
    db_session.add(p_a)
    db_session.commit()

    engine = DetectionEngine()
    run_a = engine.run_detection(db=db_session, tenant_id=tenant_a_id, triggered_by_user_id=admin_a_id)
    assert run_a.exceptions_count >= 1

    # Now run detection for Tenant B
    run_b = engine.run_detection(db=db_session, tenant_id=tenant_b_id, triggered_by_user_id=admin_b_id)
    assert run_b.exceptions_count == 0
    assert run_b.total_leakage_amount == Decimal("0.0000")

    # Verify Tenant B has no exceptions in database
    b_exceptions = db_session.execute(
        select(LeakageException).where(LeakageException.tenant_id == tenant_b_id)
    ).scalars().all()
    assert len(b_exceptions) == 0
