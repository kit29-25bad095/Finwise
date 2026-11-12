import uuid
from decimal import Decimal
from datetime import datetime, date, timezone
import pytest
from sqlalchemy.orm import Session

from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalPayment
from app.models.reconciliation import FeeContract, FeeScheduleTier
from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity
from app.services.leakage.fee_overcharge_detector import FeeOverchargeDetector


def seed_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="payments_fee.csv",
        file_hash_sha256="dummyhash_fee",
        file_size_bytes=1024,
        total_rows=10,
        valid_rows=10,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


def test_fee_overcharge_detector_standard_overcharge(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # 1. Setup contract with 2% MDR and 18% GST on Credit Cards
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
        percentage_rate=Decimal("0.020000"),  # 2.0%
        fixed_fee_per_txn=Decimal("0.0000")
    )
    db_session.add(tier)
    db_session.flush()

    # Capture of ₹10,000 on CREDIT_STANDARD
    # Expected MDR: 10,000 * 0.02 = 200.0000
    # Expected GST: 200 * 0.18 = 36.0000
    # Expected total fee: 236.0000
    # Gateway reported fee of ₹300 + tax ₹54 = ₹354.0000 (Overcharge of ₹118.0000!)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_FEE_OVER_001",
        order_reference="ORD-FEE-001",
        payment_method="CREDIT_STANDARD",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("300.0000"),
        reported_tax=Decimal("54.0000"),
        status="captured",
        captured_at=datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id, parameters={"fee_overcharge_tolerance": "0.05"})

    assert len(findings) == 1
    f = findings[0]
    assert f.detector_type == DetectorType.FEE_OVERCHARGE
    assert f.exception_type == LeakageExceptionType.FEE_OVERCHARGE
    assert f.expected_amount == Decimal("236.0000")
    assert f.actual_amount == Decimal("354.0000")
    assert f.leakage_amount == Decimal("118.0000")
    assert f.recoverable_amount == Decimal("118.0000")
    assert f.severity == ExceptionSeverity.HIGH
    assert len(f.evidence_items) == 2


def test_fee_overcharge_detector_custom_tax_safeguard(db_session: Session, seeded_entities: dict):
    """
    CRITICAL FINANCIAL SAFEGUARD 1: Never assume 18% GST.
    Contract specifies custom SEZ / concessionary GST rate of 5.0% (0.050000).
    The engine must calculate tax using 5.0%, NOT 18%.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Concessionary 5% GST Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.050000"),  # 5% GST
    )
    db_session.add(contract)
    db_session.flush()

    tier = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="DEBIT",
        percentage_rate=Decimal("0.010000"),  # 1.0%
        fixed_fee_per_txn=Decimal("0.0000")
    )
    db_session.add(tier)
    db_session.flush()

    # Capture of ₹20,000 on DEBIT
    # Expected MDR: 20,000 * 0.01 = 200.0000
    # Expected GST at 5%: 200 * 0.05 = 10.0000 (If it wrongly used 18%, it would calculate 36.0000!)
    # Expected total fee: 210.0000
    # Gateway reported total of ₹250.0000 (Overcharge of ₹40.0000)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_GST5_002",
        payment_method="DEBIT",
        captured_amount=Decimal("20000.0000"),
        reported_fee=Decimal("230.0000"),
        reported_tax=Decimal("20.0000"),
        status="captured",
        captured_at=datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("20000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.expected_amount == Decimal("210.0000")
    assert f.actual_amount == Decimal("250.0000")
    assert f.leakage_amount == Decimal("40.0000")
    assert f.calculation_breakdown["contractual_gst_rate"] == "0.050000"
    assert f.calculation_breakdown["calculated_tax"] == "10.0000"


def test_fee_overcharge_detector_missing_contract_safeguard(db_session: Session, seeded_entities: dict):
    """
    CRITICAL FINANCIAL SAFEGUARD: If no contract is configured,
    engine must NOT invent fees; it must classify finding as CONTRACT_CONFIGURATION_MISSING.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # ZERO FeeContracts in DB
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=3,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_NOCONTRACT_003",
        payment_method="UPI",
        captured_amount=Decimal("5000.0000"),
        reported_fee=Decimal("100.0000"),
        reported_tax=Decimal("18.0000"),
        status="captured",
        captured_at=datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("5000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING
    assert f.actual_amount == Decimal("118.0000")
    assert "no active feecontract" in f.explanation.lower()


def test_fee_overcharge_detector_tolerance_drift_ignored(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Tolerance Test",
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
        percentage_rate=Decimal("0.000000"),  # 0%
        fixed_fee_per_txn=Decimal("0.0000")
    )
    db_session.add(tier)
    db_session.flush()

    # Reported fee of ₹0.03 (less than ₹0.05 tolerance)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=4,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_DRIFT_004",
        payment_method="UPI",
        captured_amount=Decimal("1000.0000"),
        reported_fee=Decimal("0.0300"),
        reported_tax=Decimal("0.0000"),
        status="captured",
        captured_at=datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("1000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id, parameters={"fee_overcharge_tolerance": "0.05"})

    assert len(findings) == 0  # Ignored as minor rounding drift


def test_historical_inactive_contract_selected_with_lineage_clamping(
    db_session: Session, seeded_entities: dict
):
    """
    Validates that historical superseded contracts (is_active=False) with open-ended
    predecessor dates are correctly clamped by successor start dates and selected
    for historical transactions without collision.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Contract v1: Historical (superseded), 1.5% MDR, start 2025-01-01, end_date=None
    c1 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Razorpay Historical 2025",
        version=1,
        is_active=False,
        start_date=date(2025, 1, 1),
        end_date=None,  # Open-ended in DB, clamped by v2
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(c1)
    db_session.flush()

    t1 = FeeScheduleTier(
        contract_id=c1.id,
        tenant_id=tenant_id,
        instrument_type="UPI",
        percentage_rate=Decimal("0.015000"),  # 1.5%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(t1)

    # Contract v2: Current Active Head, 2.0% MDR, start 2026-06-01, end_date=None
    c2 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Razorpay Active 2026",
        version=2,
        is_active=True,
        start_date=date(2026, 6, 1),
        end_date=None,
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(c2)
    db_session.flush()

    t2 = FeeScheduleTier(
        contract_id=c2.id,
        tenant_id=tenant_id,
        instrument_type="UPI",
        percentage_rate=Decimal("0.020000"),  # 2.0%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(t2)
    db_session.flush()

    # Payment in 2025: should be matched strictly against v1 (1.5% rate)
    p_2025 = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=10,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_HISTORICAL_2025",
        payment_method="UPI",
        captured_amount=Decimal("10000.0000"),
        # Expected fee under v1: 10000 * 0.015 = 150 + 27 GST = 177.0000
        # If charged ₹250 (fee: 200, tax: 50), overcharge is ₹73.0000
        reported_fee=Decimal("200.0000"),
        reported_tax=Decimal("50.0000"),
        status="captured",
        captured_at=datetime(2025, 10, 15, 10, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(p_2025)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.contract_id == c1.id
    assert f.contract_version == 1
    assert f.expected_amount == Decimal("177.0000")
    assert f.leakage_amount == Decimal("73.0000")


def test_duplicate_contract_versions_produce_lineage_ambiguity_zero_leakage(
    db_session: Session, seeded_entities: dict
):
    """
    Duplicate versions for the same tenant/gateway must produce an explicit
    FEE_CALCULATION_DISCREPANCY finding with zero calculated leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    c1 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Version 1 A",
        version=1,
        is_active=False,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    c2 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Version 1 B",
        version=1,  # Duplicate version 1!
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=11,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_DUP_VER_011",
        payment_method="UPI",
        captured_amount=Decimal("5000.0000"),
        reported_fee=Decimal("100.0000"),
        reported_tax=Decimal("18.0000"),
        status="captured",
        captured_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("5000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.FEE_CALCULATION_DISCREPANCY
    assert f.severity == ExceptionSeverity.HIGH
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.calculation_breakdown["lineage_status"] == "UNRESOLVED_LINEAGE_AMBIGUITY"


def test_conflicting_successor_effective_dates_produce_ambiguity_zero_leakage(
    db_session: Session, seeded_entities: dict
):
    """
    If predecessor explicit end_date collides with successor start_date,
    engine must emit ambiguity finding with zero calculated leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # v1 ends Jun 30, but v2 starts Jun 1 (overlap during June)
    c1 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Version 1",
        version=1,
        is_active=False,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        gst_rate=Decimal("0.180000"),
    )
    c2 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Version 2",
        version=2,
        is_active=True,
        start_date=date(2026, 6, 1),  # Starts before c1 ends
        end_date=None,
        gst_rate=Decimal("0.180000"),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=12,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_DATE_COLLIDE_012",
        payment_method="UPI",
        captured_amount=Decimal("5000.0000"),
        reported_fee=Decimal("100.0000"),
        reported_tax=Decimal("18.0000"),
        status="captured",
        captured_at=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("5000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.FEE_CALCULATION_DISCREPANCY
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")


def test_multiple_active_contracts_produce_ambiguity_zero_leakage(
    db_session: Session, seeded_entities: dict
):
    """
    Multiple simultaneously active contracts (is_active=True) for the same gateway
    must produce an explicit FEE_CALCULATION_DISCREPANCY finding with zero leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    c1 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Contract Alpha Active",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    c2 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Contract Beta Active",
        version=2,
        is_active=True,  # Second active contract
        start_date=date(2026, 6, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=13,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_MULTI_ACTIVE_013",
        payment_method="UPI",
        captured_amount=Decimal("5000.0000"),
        reported_fee=Decimal("100.0000"),
        reported_tax=Decimal("18.0000"),
        status="captured",
        captured_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("5000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.FEE_CALCULATION_DISCREPANCY
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")


def test_generic_card_without_card_type_produces_ambiguity_finding_zero_leakage(
    db_session: Session, seeded_entities: dict
):
    """
    If payment method is 'card' but card_type is missing/None, and contract
    distinguishes Debit vs Credit tiers, the engine cannot guess and must emit
    an ambiguity finding with zero calculated leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Dual Tier Card Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(contract)
    db_session.flush()

    t_debit = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="DEBIT",
        percentage_rate=Decimal("0.009000"),  # 0.9%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    t_credit = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.020000"),  # 2.0%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add_all([t_debit, t_credit])
    db_session.flush()

    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=14,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_CARD_AMBIG_014",
        payment_method="card",
        card_type=None,  # Missing! Cannot guess debit vs credit!
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("200.0000"),
        reported_tax=Decimal("36.0000"),
        status="captured",
        captured_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.FEE_CALCULATION_DISCREPANCY
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.calculation_breakdown["tier_status"] == "INSTRUMENT_AMBIGUOUS"


def test_strict_tier_matching_eliminates_arbitrary_tier_zero_fallback(
    db_session: Session, seeded_entities: dict
):
    """
    If a contract contains only UPI, but a Netbanking payment is processed,
    the engine must NOT arbitrarily apply the UPI tier. It must emit
    CONTRACT_CONFIGURATION_MISSING with zero leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="UPI Only Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(contract)
    db_session.flush()

    t_upi = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="UPI",
        percentage_rate=Decimal("0.000000"),  # 0%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(t_upi)
    db_session.flush()

    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=15,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_NETBANKING_UNCONFIG_015",
        payment_method="NETBANKING",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("150.0000"),
        reported_tax=Decimal("27.0000"),
        status="captured",
        captured_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.calculation_breakdown["tier_status"] == "TIER_NOT_FOUND"


# ---------------------------------------------------------------------------
# Group A1.1: Corporate Card Tier Resolution & Date Range Tests
# ---------------------------------------------------------------------------

def test_corporate_card_dedicated_tier_resolved(db_session: Session, seeded_entities: dict):
    """
    Test 1: Dedicated corporate tier exists.
    Transaction with card_type='corporate' must resolve to CREDIT_CORPORATE (2.5%),
    not standard credit (2.0%).
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Corporate & Consumer Card Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(contract)
    db_session.flush()

    t_consumer = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.020000"),  # 2.0%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    t_corp = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_CORPORATE",
        percentage_rate=Decimal("0.025000"),  # 2.5%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add_all([t_consumer, t_corp])
    db_session.flush()

    # Capture of ₹10,000 on Corporate Card
    # Expected MDR: 10,000 * 0.025 = 250.0000
    # Expected GST: 250 * 0.18 = 45.0000
    # Expected total fee: 295.0000
    # Gateway reported fee ₹350 + tax ₹63 = ₹413.0000 (Overcharge of ₹118.0000)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=16,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_CORP_DEDICATED_016",
        payment_method="card",
        card_type="corporate",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("350.0000"),
        reported_tax=Decimal("63.0000"),
        status="captured",
        captured_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.FEE_OVERCHARGE
    assert f.expected_amount == Decimal("295.0000")
    assert f.actual_amount == Decimal("413.0000")
    assert f.leakage_amount == Decimal("118.0000")
    assert f.recoverable_amount == Decimal("118.0000")
    assert f.calculation_breakdown["tier_instrument"] == "CREDIT_CORPORATE"


def test_corporate_card_tier_absent_fallback_prohibited(db_session: Session, seeded_entities: dict):
    """
    Test 2: Corporate tier absent, standard credit tier exists.
    Engine must NEVER silently fall back to CREDIT_STANDARD for corporate cards.
    Must emit CONTRACT_CONFIGURATION_MISSING with zero leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Consumer Only Card Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(contract)
    db_session.flush()

    t_consumer = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.020000"),  # 2.0%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(t_consumer)
    db_session.flush()

    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=17,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_CORP_NO_FALLBACK_017",
        payment_method="card",
        card_type="corporate",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("250.0000"),
        reported_tax=Decimal("45.0000"),
        status="captured",
        captured_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.calculation_breakdown["tier_status"] == "TIER_NOT_FOUND"


def test_corporate_card_explicit_inheritance_tier_supported(db_session: Session, seeded_entities: dict):
    """
    Test 3: Explicitly configured corporate inheritance.
    When contract explicitly defines CORPORATE_INHERIT_STANDARD, corporate cards
    may inherit the standard credit tier.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Inherited Corporate Card Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(contract)
    db_session.flush()

    t_consumer = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.020000"),  # 2.0%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    t_inherit = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CORPORATE_INHERIT_STANDARD",
        percentage_rate=Decimal("0.020000"),
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add_all([t_consumer, t_inherit])
    db_session.flush()

    # Capture of ₹10,000 on Corporate Card
    # Expected fee under inherited standard rate (2%): 200 + 36 = 236.0000
    # Reported fee ₹300 + tax ₹54 = ₹354.0000 (Overcharge of ₹118.0000)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=18,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_CORP_INHERIT_018",
        payment_method="card",
        card_type="corporate",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("300.0000"),
        reported_tax=Decimal("54.0000"),
        status="captured",
        captured_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.FEE_OVERCHARGE
    assert f.expected_amount == Decimal("236.0000")
    assert f.actual_amount == Decimal("354.0000")
    assert f.leakage_amount == Decimal("118.0000")
    assert f.recoverable_amount == Decimal("118.0000")


def test_corporate_card_insufficient_instrument_info(db_session: Session, seeded_entities: dict):
    """
    Test 4: Corporate transaction with insufficient instrument information.
    A) card_type='corporate' but payment_method is None.
    B) Contract has distinct corporate credit and corporate debit tiers, but method='card' (lacks credit/debit distinction).
    C) Contract has distinct domestic corporate and international corporate tiers, but card_network is None.
    All must emit INSTRUMENT_AMBIGUOUS with zero leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Multi Corporate Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(contract)
    db_session.flush()

    t_corp_credit = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_CORPORATE",
        percentage_rate=Decimal("0.025000"),
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    t_corp_debit = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="DEBIT_CORPORATE",
        percentage_rate=Decimal("0.015000"),
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    t_corp_intl = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CORPORATE_INTERNATIONAL",
        percentage_rate=Decimal("0.035000"),
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add_all([t_corp_credit, t_corp_debit, t_corp_intl])
    db_session.flush()

    # Case A: card_type='corporate', payment_method=None
    p_a = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=19,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_CORP_NO_METHOD_019",
        payment_method=None,
        card_type="corporate",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("250.0000"),
        reported_tax=Decimal("45.0000"),
        status="captured",
        captured_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    # Case B: card_type='corporate', payment_method='card', network='DOMESTIC'
    # Contract has separate CREDIT_CORPORATE and DEBIT_CORPORATE; cannot distinguish!
    p_b = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=20,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_CORP_AMBIG_CREDIT_DEBIT_020",
        payment_method="card",
        card_type="corporate",
        card_network="DOMESTIC",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("250.0000"),
        reported_tax=Decimal("45.0000"),
        status="captured",
        captured_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add_all([p_a, p_b])
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 2
    for f in findings:
        assert f.exception_type == LeakageExceptionType.FEE_CALCULATION_DISCREPANCY
        assert f.leakage_amount == Decimal("0.0000")
        assert f.recoverable_amount == Decimal("0.0000")
        assert f.calculation_breakdown["tier_status"] == "INSTRUMENT_AMBIGUOUS"


def test_contract_invalid_end_date_before_start_date_produces_ambiguity(
    db_session: Session, seeded_entities: dict
):
    """
    Contract Date-Range Test 1: End date earlier than start date (end_date < start_date).
    Resolver must reject as LINEAGE_AMBIGUITY and refuse to calculate leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Corrupt Date Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 5, 1),  # Invalid: end_date < start_date!
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
    db_session.flush()

    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=21,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_INVALID_DATES_021",
        payment_method="CREDIT_STANDARD",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("300.0000"),
        reported_tax=Decimal("54.0000"),
        status="captured",
        captured_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.FEE_CALCULATION_DISCREPANCY
    assert f.severity == ExceptionSeverity.HIGH
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.calculation_breakdown["lineage_status"] == "UNRESOLVED_LINEAGE_AMBIGUITY"
    assert "earlier than start_date" in f.calculation_breakdown["anomaly_reason"]


def test_contract_same_day_start_equals_end_date_valid(
    db_session: Session, seeded_entities: dict
):
    """
    Contract Date-Range Test 2: Start date equal to end date (start_date == end_date).
    A single-day flash contract is valid for that calendar day, but invalid for adjacent days.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="One Day Flash Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 3, 15),
        end_date=date(2026, 3, 15),  # Same day!
        gst_rate=Decimal("0.180000"),
    )
    db_session.add(contract)
    db_session.flush()

    tier = FeeScheduleTier(
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.015000"),  # Concessionary 1.5%
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(tier)
    db_session.flush()

    # Capture on the exact valid day: 2026-03-15
    # Expected fee: 10,000 * 0.015 = 150 + 27 = 177.0000
    # Reported fee ₹250 + tax ₹45 = ₹295.0000 (Overcharge of ₹118.0000)
    p_valid_day = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=22,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_SAME_DAY_VALID_022",
        payment_method="CREDIT_STANDARD",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("250.0000"),
        reported_tax=Decimal("45.0000"),
        status="captured",
        captured_at=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )

    # Capture on the following day: 2026-03-16 (Outside contract window!)
    p_next_day = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=23,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_SAME_DAY_EXPIRED_023",
        payment_method="CREDIT_STANDARD",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("250.0000"),
        reported_tax=Decimal("45.0000"),
        status="captured",
        captured_at=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add_all([p_valid_day, p_next_day])
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 2
    f_valid = next(f for f in findings if f.source_reference == "pay_SAME_DAY_VALID_022")
    f_expired = next(f for f in findings if f.source_reference == "pay_SAME_DAY_EXPIRED_023")

    # Valid day correctly resolves to contract and detects overcharge
    assert f_valid.exception_type == LeakageExceptionType.FEE_OVERCHARGE
    assert f_valid.expected_amount == Decimal("177.0000")
    assert f_valid.actual_amount == Decimal("295.0000")
    assert f_valid.leakage_amount == Decimal("118.0000")

    # Next day has no contract configured
    assert f_expired.exception_type == LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING
    assert f_expired.leakage_amount == Decimal("0.0000")


def test_valid_historical_contract_lineage_selection(
    db_session: Session, seeded_entities: dict
):
    """
    Contract Date-Range Test 3: Valid historical contract.
    Historical contract v1 (inactive) covers Q1 2026. Active contract v2 covers Q2 onwards.
    Payments in Q1 resolve to v1; payments in Q2 resolve to v2.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract_v1 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Q1 2026 Contract",
        version=1,
        is_active=False,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        gst_rate=Decimal("0.180000"),
    )
    contract_v2 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Q2 2026 Contract",
        version=2,
        is_active=True,
        start_date=date(2026, 4, 1),
        end_date=None,
        gst_rate=Decimal("0.180000"),
    )
    db_session.add_all([contract_v1, contract_v2])
    db_session.flush()

    tier_v1 = FeeScheduleTier(
        contract_id=contract_v1.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.025000"),  # 2.5% in Q1
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    tier_v2 = FeeScheduleTier(
        contract_id=contract_v2.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.018000"),  # 1.8% in Q2
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add_all([tier_v1, tier_v2])
    db_session.flush()

    # Q1 capture: 2026-02-15
    # Expected fee under v1 (2.5%): 250 + 45 = 295.0000
    p_q1 = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=24,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_HISTORICAL_Q1_024",
        payment_method="CREDIT_STANDARD",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("350.0000"),
        reported_tax=Decimal("63.0000"),
        status="captured",
        captured_at=datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )

    # Q2 capture: 2026-05-15
    # Expected fee under v2 (1.8%): 180 + 32.40 = 212.4000
    p_q2 = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=25,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_ACTIVE_Q2_025",
        payment_method="CREDIT_STANDARD",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("250.0000"),
        reported_tax=Decimal("45.0000"),
        status="captured",
        captured_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add_all([p_q1, p_q2])
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 2
    f_q1 = next(f for f in findings if f.source_reference == "pay_HISTORICAL_Q1_024")
    f_q2 = next(f for f in findings if f.source_reference == "pay_ACTIVE_Q2_025")

    assert f_q1.contract_id == contract_v1.id
    assert f_q1.expected_amount == Decimal("295.0000")
    assert f_q1.actual_amount == Decimal("413.0000")
    assert f_q1.leakage_amount == Decimal("118.0000")

    assert f_q2.contract_id == contract_v2.id
    assert f_q2.expected_amount == Decimal("212.4000")
    assert f_q2.actual_amount == Decimal("295.0000")
    assert f_q2.leakage_amount == Decimal("82.6000")


def test_invalid_contract_mixed_with_otherwise_valid_contract(
    db_session: Session, seeded_entities: dict
):
    """
    Contract Date-Range Test 4: Invalid contract mixed with an otherwise valid contract.
    Contract v1 is valid (2026-01-01 to 2026-03-31).
    Contract v2 has an invalid date range (start 2026-06-01, end 2026-05-01).
    Even a payment captured during v1's window cannot be safely processed;
    the corrupted contract in the tenant/gateway lineage forces LINEAGE_AMBIGUITY with zero leakage.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    contract_v1 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Valid Contract v1",
        version=1,
        is_active=False,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        gst_rate=Decimal("0.180000"),
    )
    contract_v2 = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Corrupt Contract v2",
        version=2,
        is_active=True,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 5, 1),  # Invalid!
        gst_rate=Decimal("0.180000"),
    )
    db_session.add_all([contract_v1, contract_v2])
    db_session.flush()

    tier_v1 = FeeScheduleTier(
        contract_id=contract_v1.id,
        tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD",
        percentage_rate=Decimal("0.020000"),
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add(tier_v1)
    db_session.flush()

    # Capture in Q1 (within v1 date range)
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=26,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_MIXED_INVALID_026",
        payment_method="CREDIT_STANDARD",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("300.0000"),
        reported_tax=Decimal("54.0000"),
        status="captured",
        captured_at=datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc),
        unallocated_balance=Decimal("10000.0000"),
    )
    db_session.add(payment)
    db_session.commit()

    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id)

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.FEE_CALCULATION_DISCREPANCY
    assert f.severity == ExceptionSeverity.HIGH
    assert f.leakage_amount == Decimal("0.0000")
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.calculation_breakdown["lineage_status"] == "UNRESOLVED_LINEAGE_AMBIGUITY"


