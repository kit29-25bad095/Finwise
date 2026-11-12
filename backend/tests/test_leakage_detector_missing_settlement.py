import uuid
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
import pytest
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalPayment
from app.models.reconciliation import FeeContract, FeeScheduleTier
from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity
from app.services.leakage.missing_settlement_detector import MissingSettlementDetector
from app.services.leakage.calendar_service import BankingCalendarService


def seed_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="payments.csv",
        file_hash_sha256="dummyhash_missing_settlement",
        file_size_bytes=1024,
        total_rows=10,
        valid_rows=10,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


def test_missing_settlement_detector_fully_missing(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Capture 10 days ago (past T+2 due date + 1 day grace)
    captured_time = datetime.now(timezone.utc) - timedelta(days=10)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_MISSING_001",
        order_reference="ORD-001",
        payment_method="card",
        captured_amount=Decimal("15000.0000"),
        reported_fee=Decimal("300.0000"),
        reported_tax=Decimal("54.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("15000.0000"),  # 100% unsettled
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.detector_type == DetectorType.MISSING_SETTLEMENT
    assert f.exception_type == LeakageExceptionType.MISSING_SETTLEMENT
    assert f.leakage_amount == Decimal("15000.0000")
    assert f.source_reference == "pay_MISSING_001"
    assert f.severity in (ExceptionSeverity.CRITICAL, ExceptionSeverity.HIGH)
    assert len(f.evidence_items) == 1
    assert f.evidence_items[0].evidence_type == "PAYMENT_CAPTURE"


def test_missing_settlement_detector_partially_missing(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    captured_time = datetime.now(timezone.utc) - timedelta(days=8)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_PARTIAL_002",
        order_reference="ORD-002",
        payment_method="upi",
        captured_amount=Decimal("10000.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("4000.0000"),  # Partially settled: ₹6000 settled, ₹4000 remaining
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.PARTIALLY_MISSING_SETTLEMENT
    assert f.leakage_amount == Decimal("4000.0000")
    assert f.actual_amount == Decimal("6000.0000")
    assert f.expected_amount == Decimal("10000.0000")


def test_missing_settlement_detector_settlement_overdue_within_grace(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Capture yesterday at 10:00 AM UTC with T+1 turnaround.
    # As of today, it is past T+1 due date, but within 2-day grace period
    captured_time = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)  # Monday
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=3,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_OVERDUE_003",
        order_reference="ORD-003",
        payment_method="upi",
        captured_amount=Decimal("5000.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("5000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    # Wednesday 2026-11-04: past Tuesday 2026-11-03 due date, but within grace period
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"as_of_date": date(2026, 11, 4), "grace_period_days": 2, "settlement_delays": {"upi": 1}}
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.SETTLEMENT_OVERDUE


def test_missing_settlement_detector_fresh_capture_not_flagged(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Capture today
    now = datetime.now(timezone.utc)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=4,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_FRESH_004",
        captured_amount=Decimal("2000.0000"),
        status="captured",
        captured_at=now,
        unallocated_balance=Decimal("2000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 0


def test_unknown_settlement_turnaround_produces_configuration_finding_zero_leakage(
    db_session: Session, seeded_entities: dict
):
    """
    CASE D: If settlement turnaround SLA (T+N) is unconfigured for an instrument,
    do NOT calculate an overdue finding using an invented T+2 value.
    Emit CONTRACT_CONFIGURATION_MISSING with zero leakage and zero recovery.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    captured_time = datetime.now(timezone.utc) - timedelta(days=10)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=6,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_UNKNOWN_SLA_006",
        order_reference="ORD-SLA-006",
        payment_method="CRYPTO_TOKEN",  # Unconfigured method without SLA
        captured_amount=Decimal("25000.0000"),
        reported_fee=Decimal("0.0000"),
        reported_tax=Decimal("0.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("25000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"settlement_delays": {"upi": 1, "card": 2}}  # No entry for CRYPTO_TOKEN
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING
    assert f.severity == ExceptionSeverity.MEDIUM
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.actual_amount == Decimal("25000.0000")
    assert f.calculation_breakdown["sla_status"] == "UNCONFIGURED_SLA"


def test_unverified_fee_contract_does_not_deduct_invented_fees(
    db_session: Session, seeded_entities: dict
):
    """
    CASE B: If contract or tier cannot be verified, engine must NOT deduct
    an unverified 2% fallback fee. Preserves gross exposure with recovery = 0.0000.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Overdue payment (10 days ago) under gateway without any configured contract
    captured_time = datetime.now(timezone.utc) - timedelta(days=10)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=7,
        gateway_name="UNKNOWN_GW",
        gateway_payment_id="pay_NO_FEE_CONTRACT_007",
        order_reference="ORD-007",
        payment_method="card",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("200.0000"),
        reported_tax=Decimal("36.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"settlement_delays": {"card": 2}}
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type in (
        LeakageExceptionType.MISSING_SETTLEMENT,
        LeakageExceptionType.SETTLEMENT_OVERDUE,
    )
    assert f.leakage_amount == Decimal("10000.0000")  # Gross exposure
    assert f.recoverable_amount == Decimal("0.0000")  # Unverified recovery held at 0
    assert (
        f.calculation_breakdown["contractual_fee_deduction"]["status"]
        == "UNVERIFIED_CONTRACT_FEE_OMITTED"
    )
    assert (
        f.calculation_breakdown["contractual_fee_deduction"]["deduction_amount"]
        == "0.0000"
    )


def test_verified_contract_deducts_contractual_fee_from_overdue_settlement(
    db_session: Session, seeded_entities: dict
):
    """
    CASE A: When contract and tier are authenticated, contractual fee is deducted accurately.
    10,000 capture @ 2% MDR + 18% GST = ₹236 fee deduction -> ₹9764 verified recoverable.
    """
    from app.models.reconciliation import FeeContract, FeeScheduleTier

    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Verified Razorpay SLA Contract",
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
        instrument_type="UPI",
        percentage_rate=Decimal("0.020000"),  # 2.0%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(tier)
    db_session.flush()

    captured_time = datetime.now(timezone.utc) - timedelta(days=8)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=8,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_VERIFIED_SLA_008",
        order_reference="ORD-008",
        payment_method="UPI",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("200.0000"),
        reported_tax=Decimal("36.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"settlement_delays": {"upi": 1}}
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.leakage_amount == Decimal("10000.0000")
    # Expected fee: 10,000 * 0.02 = 200 + 36 GST = 236. Net recoverable = 10,000 - 236 = 9764.0000
    assert f.recoverable_amount == Decimal("9764.0000")
    assert (
        f.calculation_breakdown["contractual_fee_deduction"]["status"]
        == "VERIFIED_CONTRACT_APPLIED"
    )
    assert (
        f.calculation_breakdown["contractual_fee_deduction"]["deduction_amount"]
        == "236.0000"
    )
  # Not overdue!


def test_missing_settlement_detector_failed_payment_excluded(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    captured_time = datetime.now(timezone.utc) - timedelta(days=10)
    failed_payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=5,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_FAILED_005",
        captured_amount=Decimal("0.0000"),
        status="failed",  # Non-captured
        captured_at=captured_time,
        unallocated_balance=Decimal("0.0000"),
    )
    db_session.add(failed_payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 0


def test_unknown_settlement_turnaround_produces_configuration_finding_zero_leakage(
    db_session: Session, seeded_entities: dict
):
    """
    CASE D: If settlement turnaround SLA (T+N) is unconfigured for an instrument,
    do NOT calculate an overdue finding using an invented T+2 value.
    Emit CONTRACT_CONFIGURATION_MISSING with zero leakage and zero recovery.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    captured_time = datetime.now(timezone.utc) - timedelta(days=10)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=6,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_UNKNOWN_SLA_006",
        order_reference="ORD-SLA-006",
        payment_method="CRYPTO_TOKEN",  # Unconfigured method without SLA
        captured_amount=Decimal("25000.0000"),
        reported_fee=Decimal("0.0000"),
        reported_tax=Decimal("0.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("25000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"settlement_delays": {"upi": 1, "card": 2}}  # No entry for CRYPTO_TOKEN
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING
    assert f.severity == ExceptionSeverity.MEDIUM
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.actual_amount == Decimal("25000.0000")
    assert f.calculation_breakdown["sla_status"] == "UNCONFIGURED_SLA"


def test_unverified_fee_contract_does_not_deduct_invented_fees(
    db_session: Session, seeded_entities: dict
):
    """
    CASE B: If contract or tier cannot be verified, engine must NOT deduct
    an unverified 2% fallback fee. Preserves gross exposure with recovery = 0.0000.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Overdue payment (10 days ago) under gateway without any configured contract
    captured_time = datetime.now(timezone.utc) - timedelta(days=10)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=7,
        gateway_name="UNKNOWN_GW",
        gateway_payment_id="pay_NO_FEE_CONTRACT_007",
        order_reference="ORD-007",
        payment_method="card",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("200.0000"),
        reported_tax=Decimal("36.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"settlement_delays": {"card": 2}}
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type in (
        LeakageExceptionType.MISSING_SETTLEMENT,
        LeakageExceptionType.SETTLEMENT_OVERDUE,
    )
    assert f.leakage_amount == Decimal("10000.0000")  # Gross exposure
    assert f.recoverable_amount == Decimal("0.0000")  # Unverified recovery held at 0
    assert (
        f.calculation_breakdown["contractual_fee_deduction"]["status"]
        == "UNVERIFIED_CONTRACT_FEE_OMITTED"
    )
    assert (
        f.calculation_breakdown["contractual_fee_deduction"]["deduction_amount"]
        == "0.0000"
    )


def test_verified_contract_deducts_contractual_fee_from_overdue_settlement(
    db_session: Session, seeded_entities: dict
):
    """
    CASE A: When contract and tier are authenticated, contractual fee is deducted accurately.
    10,000 capture @ 2% MDR + 18% GST = ₹236 fee deduction -> ₹9764 verified recoverable.
    """
    from app.models.reconciliation import FeeContract, FeeScheduleTier

    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Verified Razorpay SLA Contract",
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
        instrument_type="UPI",
        percentage_rate=Decimal("0.020000"),  # 2.0%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(tier)
    db_session.flush()

    captured_time = datetime.now(timezone.utc) - timedelta(days=8)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=8,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_VERIFIED_SLA_008",
        order_reference="ORD-008",
        payment_method="UPI",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("200.0000"),
        reported_tax=Decimal("36.0000"),
        status="captured",
        captured_at=captured_time,
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"settlement_delays": {"upi": 1}}
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.leakage_amount == Decimal("10000.0000")
    # Expected fee: 10,000 * 0.02 = 200 + 36 GST = 236. Net recoverable = 10,000 - 236 = 9764.0000
    assert f.recoverable_amount == Decimal("9764.0000")
    assert (
        f.calculation_breakdown["contractual_fee_deduction"]["status"]
        == "VERIFIED_CONTRACT_APPLIED"
    )
    assert (
        f.calculation_breakdown["contractual_fee_deduction"]["deduction_amount"]
        == "236.0000"
    )

