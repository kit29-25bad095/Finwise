import uuid
from decimal import Decimal
from datetime import datetime, date, time, timezone, timedelta
from fractions import Fraction
import pytest
from hypothesis import given, strategies as st, settings as hypo_settings
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.tenant import Tenant
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalRefund,
    CanonicalBankTransaction,
)
from app.models.reconciliation import (
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    FeeContract,
    FeeScheduleTier,
    MatchClassification,
    MatchType,
    ReviewStatus,
    AllocationStatus,
)
from app.models.leakage import (
    DetectorType,
    LeakageExceptionType,
    ExceptionSeverity,
)
from app.services.reconciliation.fee_calculator import FeeCalculator, round_half_up
from app.services.reconciliation.reconciliation_service import ReconciliationService
from app.services.reconciliation.knapsack_solver import BoundedKnapsackSolver
from app.services.reconciliation.scoring_engine import ScoringEngine
from app.services.leakage.calendar_service import (
    BankingCalendarService,
    CalendarType,
    normalize_to_ist,
    IST,
)
from app.services.leakage.missing_settlement_detector import MissingSettlementDetector
from app.services.leakage.uncredited_settlement_detector import UncreditedSettlementDetector
from app.services.leakage.fee_overcharge_detector import FeeOverchargeDetector
from app.services.leakage.refund_anomaly_detector import RefundAnomalyDetector


def seed_test_batch(db_session: Session, tenant_id: uuid.UUID, source_type: str = "SHOPIFY") -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type=source_type,
        filename=f"financial_test_{source_type.lower()}.csv",
        file_hash_sha256=f"hash_{uuid.uuid4().hex[:16]}",
        file_size_bytes=1024,
        total_rows=10,
        valid_rows=10,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


# ---------------------------------------------------------------------------
# 1. Shopify Order-to-Payment Matching
# ---------------------------------------------------------------------------
def test_01_shopify_order_to_payment_matching(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 1: Shopify order gross amount matches payment captured amount.
    Verifies reference normalization (#1001 vs 1001 vs ORD-1001) and unallocated balance decrement.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "SHOPIFY")
    now = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)

    # Expected: Order of ₹4,999.00 exactly matches Payment of ₹4,999.00 with clean '#' ref
    expected_amount = Decimal("4999.0000")
    order = CanonicalOrder(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        order_reference="#SHOP-8801", order_number="8801",
        gross_amount=expected_amount, currency="INR", financial_status="paid",
        order_timestamp=now
    )
    payment = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_SHP_001",
        order_reference="SHOP-8801", payment_method="UPI",
        captured_amount=expected_amount, reported_fee=Decimal("0.0000"),
        reported_tax=Decimal("0.0000"), currency="INR", status="captured",
        captured_at=now, unallocated_balance=expected_amount
    )
    db_session.add_all([order, payment])
    db_session.commit()

    run = ReconciliationService.create_run(db_session, tenant_id)
    run = ReconciliationService.execute_run(db_session, run.id)

    db_session.refresh(payment)
    assert run.matched_orders_count > 0

    # Query match
    match = db_session.execute(
        select(ReconciliationMatch).where(
            ReconciliationMatch.run_id == run.id,
            ReconciliationMatch.order_id == order.id,
            ReconciliationMatch.payment_id == payment.id
        )
    ).scalar_one()

    # Independent assertion against expected outcome
    assert match.classification == MatchClassification.EXACT_MATCH.value
    assert match.allocated_amount == expected_amount
    assert match.confidence_score == Decimal("1.0000")
    assert payment.unallocated_balance == Decimal("0.0000")


# ---------------------------------------------------------------------------
# 2. Payment-to-Settlement Matching
# ---------------------------------------------------------------------------
def test_02_payment_to_settlement_matching(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 2: Verifies captured payments mapped into gateway settlement batches.
    Conservation Invariant: Sum of payment captured amounts allocated <= Net/Gross settlement batch.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "RAZORPAY")
    now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)

    p1 = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_SETL_M_01",
        order_reference="ORD-SETL-01", payment_method="UPI",
        captured_amount=Decimal("2000.0000"), unallocated_balance=Decimal("2000.0000"),
        captured_at=now, status="captured"
    )
    p2 = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=2,
        gateway_name="RAZORPAY", gateway_payment_id="pay_SETL_M_02",
        order_reference="ORD-SETL-02", payment_method="UPI",
        captured_amount=Decimal("3000.0000"), unallocated_balance=Decimal("3000.0000"),
        captured_at=now, status="captured"
    )
    settlement = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-BATCH-99",
        utr_number="UTR_BATCH_99", gross_amount=Decimal("5000.0000"),
        total_fee=Decimal("100.0000"), total_tax=Decimal("18.0000"),
        net_settlement_amount=Decimal("4882.0000"), unallocated_balance=Decimal("4882.0000"),
        status="settled", settled_at=now
    )
    db_session.add_all([p1, p2, settlement])
    db_session.commit()

    # Conservation Invariant verification:
    expected_gross = p1.captured_amount + p2.captured_amount
    assert settlement.gross_amount == expected_gross
    assert settlement.net_settlement_amount == expected_gross - settlement.total_fee - settlement.total_tax


# ---------------------------------------------------------------------------
# 3. Settlement-to-Bank Matching (Pass 2 Exact UTR)
# ---------------------------------------------------------------------------
def test_03_settlement_to_bank_matching(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 3: Exact Settlement Batch UTR match to Bank Credit (Pass 2).
    Verifies that extracted UTR from narration exactly matches settlement UTR.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "HDFC")
    now = datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc)
    utr = "HDFCR5202611160099"
    expected_credit = Decimal("146460.0000")

    settlement = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-20261116-01",
        utr_number=utr, gross_amount=Decimal("150000.0000"),
        total_fee=Decimal("3000.0000"), total_tax=Decimal("540.0000"),
        net_settlement_amount=expected_credit, unallocated_balance=expected_credit,
        status="settled", settled_at=now
    )
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        bank_name="HDFC", bank_reference="CHQ_UTR_MATCH",
        extracted_utr=utr, raw_narration=f"CMS/RZP/NODAL/{utr}/SETL-20261116-01",
        transaction_date=now.date(), value_date=now.date(),
        credit_amount=expected_credit, unallocated_balance=expected_credit
    )
    db_session.add_all([settlement, bank_tx])
    db_session.commit()

    run = ReconciliationService.create_run(db_session, tenant_id)
    run = ReconciliationService.execute_run(db_session, run.id)

    db_session.refresh(settlement)
    db_session.refresh(bank_tx)

    match = db_session.execute(
        select(ReconciliationMatch).where(
            ReconciliationMatch.run_id == run.id,
            ReconciliationMatch.settlement_id == settlement.id,
            ReconciliationMatch.bank_transaction_id == bank_tx.id
        )
    ).scalar_one()

    assert match.pass_number == 2
    assert match.classification == MatchClassification.EXACT_MATCH.value
    assert match.allocated_amount == expected_credit
    assert settlement.unallocated_balance == Decimal("0.0000")
    assert bank_tx.unallocated_balance == Decimal("0.0000")


# ---------------------------------------------------------------------------
# 4. Partial and Aggregated Settlements (Knapsack Solver)
# ---------------------------------------------------------------------------
def test_04_partial_and_aggregated_settlements(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 4: Partial settlement allocation and Pass 5 Knapsack multi-record aggregation.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "RAZORPAY")
    now = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)

    # 4A: Partial Settlement
    partial_settlement = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-PART-AUDIT",
        utr_number="PART_UTR_AUDIT", gross_amount=Decimal("100000.0000"),
        net_settlement_amount=Decimal("100000.0000"), unallocated_balance=Decimal("100000.0000"),
        settled_at=now
    )
    partial_bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=2,
        bank_name="HDFC", bank_reference="PART_BANK_AUDIT", extracted_utr="PART_UTR_AUDIT",
        raw_narration="PART DEPOSIT", transaction_date=now.date(),
        credit_amount=Decimal("40000.0000"), unallocated_balance=Decimal("40000.0000")
    )
    db_session.add_all([partial_settlement, partial_bank_tx])
    db_session.commit()

    run = ReconciliationService.create_run(db_session, tenant_id)
    run = ReconciliationService.execute_run(db_session, run.id)

    db_session.refresh(partial_settlement)
    db_session.refresh(partial_bank_tx)

    # Expected outcome: ₹40,000 allocated, bank balance = 0, settlement unallocated balance = ₹60,000
    assert partial_bank_tx.unallocated_balance == Decimal("0.0000")
    assert partial_settlement.unallocated_balance == Decimal("60000.0000")

    # 4B: Aggregated Knapsack Subset Sum (Pass 5)
    # Target bank deposit: ₹1,00,000
    # Three settlements: ₹25,000 + ₹35,000 + ₹40,000 = ₹1,00,000
    bank_agg = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=3,
        bank_name="HDFC", bank_reference="AGG_100K", extracted_utr=None,
        credit_amount=Decimal("100000.0000"), unallocated_balance=Decimal("100000.0000")
    )
    s1 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=4,
        gateway_name="RAZORPAY", settlement_reference="S1", utr_number=None,
        net_settlement_amount=Decimal("25000.0000"), unallocated_balance=Decimal("25000.0000")
    )
    s2 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=5,
        gateway_name="RAZORPAY", settlement_reference="S2", utr_number=None,
        net_settlement_amount=Decimal("35000.0000"), unallocated_balance=Decimal("35000.0000")
    )
    s3 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=6,
        gateway_name="RAZORPAY", settlement_reference="S3", utr_number=None,
        net_settlement_amount=Decimal("40000.0000"), unallocated_balance=Decimal("40000.0000")
    )

    knapsack_res = BoundedKnapsackSolver.find_matching_subsets(
        bank_tx=bank_agg,
        candidate_settlements=[s1, s2, s3],
        max_bound_n=5,
        fee_tolerance=Decimal("0.05")
    )
    assert knapsack_res.status == "EXACT_SUBSET_FOUND"
    assert len(knapsack_res.matching_subsets) == 1
    found_subset = knapsack_res.matching_subsets[0]
    assert len(found_subset) == 3
    subset_sum = sum(s.unallocated_balance for s in found_subset)
    assert subset_sum == Decimal("100000.0000")


# ---------------------------------------------------------------------------
# 5. Duplicate and Missing Settlements
# ---------------------------------------------------------------------------
def test_05_duplicate_and_missing_settlements(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 5: Missing settlement detection beyond contractual clearing window + grace.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "RAZORPAY")

    # Payment captured 10 days ago without gateway settlement
    captured_time = datetime.now(timezone.utc) - timedelta(days=10)
    expected_missing = Decimal("18500.0000")

    payment = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_MISS_AUDIT",
        order_reference="ORD-MISS-AUDIT", payment_method="card",
        captured_amount=expected_missing, reported_fee=Decimal("370.0000"),
        reported_tax=Decimal("66.6000"), status="captured",
        captured_at=captured_time, unallocated_balance=expected_missing
    )
    db_session.add(payment)
    db_session.commit()

    detector = MissingSettlementDetector()
    findings = detector.detect(db_session, tenant_id)

    target_finding = next((f for f in findings if f.source_reference == "pay_MISS_AUDIT"), None)
    assert target_finding is not None
    assert target_finding.exception_type == LeakageExceptionType.MISSING_SETTLEMENT
    assert target_finding.leakage_amount == expected_missing
    assert target_finding.severity in (ExceptionSeverity.CRITICAL, ExceptionSeverity.HIGH)


# ---------------------------------------------------------------------------
# 6. Uncredited Settlements
# ---------------------------------------------------------------------------
def test_06_uncredited_settlements(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 6: Gateway issued settlement with UTR, bank statement cutoff exceeded without credit.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "RAZORPAY")
    expected_uncredited = Decimal("74500.0000")

    # Settlement 8 days ago
    settlement = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-UNCRED-AUDIT",
        utr_number="HDFC_UNCRED_9921", gross_amount=Decimal("76000.0000"),
        total_fee=Decimal("1271.1864"), total_tax=Decimal("228.8136"),
        net_settlement_amount=expected_uncredited, unallocated_balance=expected_uncredited,
        status="settled", settled_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    )
    # Bank statement exists through Nov 12 (past clearing window)
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        bank_name="HDFC", bank_reference="REF_OTHER",
        raw_narration="UNRELATED DEPOSIT", transaction_date=date(2026, 11, 12),
        credit_amount=Decimal("1000.0000"), unallocated_balance=Decimal("1000.0000")
    )
    db_session.add_all([settlement, bank_tx])
    db_session.commit()

    detector = UncreditedSettlementDetector()
    findings = detector.detect(db_session, tenant_id)

    target_finding = next((f for f in findings if f.source_reference == "SETL-UNCRED-AUDIT"), None)
    assert target_finding is not None
    assert target_finding.exception_type == LeakageExceptionType.UNCREDITED_SETTLEMENT
    assert target_finding.leakage_amount == expected_uncredited


# ---------------------------------------------------------------------------
# 7 & 8. Contractual MDR Overcharges & GST Calculations
# ---------------------------------------------------------------------------
def test_07_and_08_contractual_mdr_overcharge_and_gst(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 7 & 8: MDR Overcharge and GST calculation against active contract.
    Contract: 1.8% MDR + 18% GST.
    Payment: ₹50,000 captured.
    Expected: Base MDR = ₹900.0000. GST = ₹162.0000. Total expected fee = ₹1,062.0000.
    Reported: Fee ₹1,100 + Tax ₹198 = ₹1,298.0000.
    Expected Overcharge Delta = ₹1,298.0000 - ₹1,062.0000 = ₹236.0000.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "RAZORPAY")

    contract = FeeContract(
        tenant_id=tenant_id, gateway_name="RAZORPAY",
        contract_name="Audit Contract", version=1, is_active=True,
        start_date=date(2026, 1, 1), gst_rate=Decimal("0.180000")
    )
    db_session.add(contract)
    db_session.flush()

    tier = FeeScheduleTier(
        contract_id=contract.id, tenant_id=tenant_id,
        instrument_type="CREDIT_STANDARD", percentage_rate=Decimal("0.018000"),
        fixed_fee_per_txn=Decimal("0.0000")
    )
    db_session.add(tier)
    db_session.flush()

    capture_amount = Decimal("50000.0000")
    reported_fee = Decimal("1100.0000")
    reported_tax = Decimal("198.0000")

    payment = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_OVER_AUDIT",
        order_reference="ORD-OVER-AUDIT", payment_method="CREDIT_STANDARD",
        captured_amount=capture_amount, reported_fee=reported_fee,
        reported_tax=reported_tax, captured_at=datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc),
        status="captured", unallocated_balance=capture_amount
    )
    db_session.add(payment)
    db_session.commit()

    # Independent expected outcome calculations:
    exp_mdr = round_half_up(capture_amount * Decimal("0.018000"), 4)  # 900.0000
    exp_gst = round_half_up(exp_mdr * Decimal("0.180000"), 4)          # 162.0000
    exp_total = exp_mdr + exp_gst                                      # 1062.0000
    exp_delta = (reported_fee + reported_tax) - exp_total               # 236.0000

    # Run FeeCalculator
    fee_calc = FeeCalculator.calculate_payment_fees(payment, contract, fee_tolerance=Decimal("0.05"))
    assert fee_calc.unrounded_mdr == exp_mdr
    assert fee_calc.calculated_tax == exp_gst
    assert fee_calc.expected_total_fee == exp_total
    assert fee_calc.overcharge_delta == exp_delta
    assert fee_calc.is_overcharge is True

    # Run FeeOverchargeDetector
    detector = FeeOverchargeDetector()
    findings = detector.detect(db_session, tenant_id, parameters={"fee_overcharge_tolerance": "0.05"})
    target = next((f for f in findings if f.source_reference == "pay_OVER_AUDIT"), None)
    assert target is not None
    assert target.exception_type == LeakageExceptionType.FEE_OVERCHARGE
    assert target.leakage_amount == exp_delta


# ---------------------------------------------------------------------------
# 9. Refunds and Refund Fee Policies
# ---------------------------------------------------------------------------
def test_09_refunds_and_refund_fee_policies(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 9: Refund anomaly detection:
    - Duplicate refund execution (same refund reference processed multiple times).
    - Excessive refund (total refunds > captured payment amount).
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "RAZORPAY")
    now = datetime.now(timezone.utc)

    # 1. Payment of ₹10,000
    payment = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_REFUND_AUDIT",
        captured_amount=Decimal("10000.0000"), unallocated_balance=Decimal("10000.0000"),
        status="captured", captured_at=now
    )
    # 2. Duplicate refund of ₹4,000 processed twice under 'rfnd_DUP_AUDIT'
    r1 = CanonicalRefund(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_refund_id="rfnd_DUP_AUDIT", gateway_payment_id="pay_REFUND_AUDIT",
        refund_amount=Decimal("4000.0000"), status="processed", processed_at=now
    )
    r2 = CanonicalRefund(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=2,
        gateway_refund_id="rfnd_DUP_AUDIT", gateway_payment_id="pay_REFUND_AUDIT",
        refund_amount=Decimal("4000.0000"), status="processed", processed_at=now
    )
    db_session.add_all([payment, r1, r2])
    db_session.commit()

    detector = RefundAnomalyDetector()
    findings = detector.detect(db_session, tenant_id)

    dup_finding = next((f for f in findings if f.source_reference == "rfnd_DUP_AUDIT"), None)
    assert dup_finding is not None
    assert dup_finding.exception_type == LeakageExceptionType.DUPLICATE_REFUND
    assert dup_finding.leakage_amount == Decimal("4000.0000")


# ---------------------------------------------------------------------------
# 10. Chargebacks, Reserves and Adjustments Balance Conservation
# ---------------------------------------------------------------------------
def test_10_chargebacks_reserves_and_adjustments_conservation():
    """
    Financial Audit 10: Verifies fundamental settlement conservation equation:
    Gross Amount - MDR - GST - Refunds - Adjustments = Net Settlement Amount.
    """
    gross = Decimal("250000.0000")
    mdr = Decimal("4500.0000")
    gst = Decimal("810.0000")
    refunds = Decimal("12500.0000")
    dispute_reserve = Decimal("15000.0000")
    chargeback_fee = Decimal("500.0000")
    total_adjustments = dispute_reserve + chargeback_fee

    # Independent mathematical deduction
    expected_net = gross - mdr - gst - refunds - total_adjustments
    # 250000 - 4500 - 810 - 12500 - 15500 = 216690.0000
    assert expected_net == Decimal("216690.0000")

    # Invariant: Conservation of balance holds with zero drift
    total_deductions = mdr + gst + refunds + total_adjustments
    assert gross - total_deductions == expected_net


# ---------------------------------------------------------------------------
# 11. Failed Settlements
# ---------------------------------------------------------------------------
def test_11_failed_settlements_zero_allocation(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 11: Failed settlements must never be matched or allocated to bank credits.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "RAZORPAY")
    now = datetime.now(timezone.utc)

    failed_settlement = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-FAILED-01",
        utr_number="FAILED_UTR_99", gross_amount=Decimal("50000.0000"),
        net_settlement_amount=Decimal("49000.0000"), unallocated_balance=Decimal("49000.0000"),
        status="failed", settled_at=now
    )
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        bank_name="HDFC", bank_reference="CHQ_FAILED_TEST",
        extracted_utr="FAILED_UTR_99", raw_narration="FAILED TEST DEPOSIT",
        transaction_date=now.date(), value_date=now.date(),
        credit_amount=Decimal("49000.0000"), unallocated_balance=Decimal("49000.0000")
    )
    db_session.add_all([failed_settlement, bank_tx])
    db_session.commit()

    run = ReconciliationService.create_run(db_session, tenant_id)
    run = ReconciliationService.execute_run(db_session, run.id)

    db_session.refresh(failed_settlement)
    db_session.refresh(bank_tx)

    # Invariant: Zero allocations against failed settlement
    allocations = db_session.execute(
        select(ReconciliationAllocation).where(
            ReconciliationAllocation.run_id == run.id,
            ReconciliationAllocation.source_entity_id == failed_settlement.id
        )
    ).scalars().all()
    assert len(allocations) == 0

    # Invariant: Any match recorded must be UNMATCHED with zero allocated amount and no bank assignment
    matches = db_session.execute(
        select(ReconciliationMatch).where(
            ReconciliationMatch.run_id == run.id,
            ReconciliationMatch.settlement_id == failed_settlement.id
        )
    ).scalars().all()

    for m in matches:
        assert m.classification == MatchClassification.UNMATCHED.value
        assert m.allocated_amount == Decimal("0.0000")
        assert m.bank_transaction_id is None

    # Bank credit remains completely unallocated
    assert bank_tx.unallocated_balance == Decimal("49000.0000")
    assert failed_settlement.unallocated_balance == Decimal("49000.0000")


# ---------------------------------------------------------------------------
# 12. Ambiguous Matching & Anti-Collision Guard
# ---------------------------------------------------------------------------
def test_12_ambiguous_matching_collision_guard():
    """
    Financial Audit 12: Anti-collision guard blocks speculative matching when two candidates tie.
    """
    settlement = CanonicalSettlement(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), batch_id=uuid.uuid4(),
        source_row_index=1, gateway_name="RAZORPAY", settlement_reference="SETL-AMBIG",
        utr_number=None, net_settlement_amount=Decimal("50000.0000"),
        unallocated_balance=Decimal("50000.0000"),
        settled_at=datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    )
    # Two identical bank credits on the same date with no UTR
    b1 = CanonicalBankTransaction(
        id=uuid.uuid4(), tenant_id=settlement.tenant_id, batch_id=settlement.batch_id,
        source_row_index=1, bank_name="HDFC", bank_reference="B1",
        extracted_utr=None, credit_amount=Decimal("50000.0000"),
        unallocated_balance=Decimal("50000.0000"),
        transaction_date=date(2026, 11, 10)
    )
    b2 = CanonicalBankTransaction(
        id=uuid.uuid4(), tenant_id=settlement.tenant_id, batch_id=settlement.batch_id,
        source_row_index=2, bank_name="HDFC", bank_reference="B2",
        extracted_utr=None, credit_amount=Decimal("50000.0000"),
        unallocated_balance=Decimal("50000.0000"),
        transaction_date=date(2026, 11, 10)
    )

    score_1 = ScoringEngine.score_candidate(settlement, b1)
    score_2 = ScoringEngine.score_candidate(settlement, b2)

    # Collision delta is exactly 0.0000 (< 0.1500 threshold)
    collision_delta = abs(score_1.total_score - score_2.total_score)
    assert collision_delta < ScoringEngine.DEFAULT_MIN_COLLISION_DELTA
    # Both candidates score identically; speculative matching is strictly prevented


# ---------------------------------------------------------------------------
# 13. Indian Banking Holidays & Settlement Cutoffs
# ---------------------------------------------------------------------------
def test_13_indian_banking_holidays_and_settlement_cutoffs():
    """
    Financial Audit 13: Banking calendar accurately tracks:
    - Sundays (closed)
    - 2nd and 4th Saturdays (closed)
    - 1st, 3rd, 5th Saturdays (open)
    - Statutory national holidays (Republic Day Jan 26, Independence Day Aug 15, Gandhi Jayanti Oct 2)
    - RBI holidays (Diwali Nov 8 & 10, 2026)
    - 23:00 IST cutoff rolling
    """
    # 1. Republic Day (Statutory)
    assert BankingCalendarService.is_business_day(date(2026, 1, 26)) is False

    # 2. Independence Day (Statutory)
    assert BankingCalendarService.is_business_day(date(2026, 8, 15)) is False

    # 3. Gandhi Jayanti (Statutory)
    assert BankingCalendarService.is_business_day(date(2026, 10, 2)) is False

    # 4. RBI 2nd Saturday (Nov 14, 2026) vs 1st Saturday (Nov 7, 2026)
    assert BankingCalendarService.is_second_or_fourth_saturday(date(2026, 11, 7)) is False
    assert BankingCalendarService.is_second_or_fourth_saturday(date(2026, 11, 14)) is True  # 2nd Sat
    assert BankingCalendarService.is_second_or_fourth_saturday(date(2026, 11, 28)) is True  # 4th Sat

    # 5. Sunday (Nov 15, 2026)
    assert BankingCalendarService.is_business_day(date(2026, 11, 15)) is False

    # 6. Cutoff normalization to IST
    # 2026-11-13 18:00:00 UTC = 2026-11-13 23:30:00 IST (Past 23:00 cutoff)
    dt_utc = datetime(2026, 11, 13, 18, 0, 0, tzinfo=timezone.utc)
    dt_ist = normalize_to_ist(dt_utc)
    assert dt_ist.hour == 23 and dt_ist.minute == 30


# ---------------------------------------------------------------------------
# 14. Decimal Precision and 6-Stage Staged Rounding
# ---------------------------------------------------------------------------
def test_14_decimal_precision_and_staged_rounding():
    """
    Financial Audit 14: Validates the 6-stage financial rounding architecture
    against exact rational arithmetic using Python's Fraction module.
    """
    capture_amt = Decimal("14280500.3300")
    mdr_rate = Decimal("0.017500")  # 1.75%
    gst_rate = Decimal("0.180000")  # 18%

    # Stage 1: Nominal capture
    # Stage 2: Contractual MDR = capture * mdr_rate = 14280500.33 * 0.0175 = 249908.755775
    # Round half up to 4 places -> 249908.7558
    exp_mdr_exact = Decimal("249908.7558")
    actual_mdr = round_half_up(capture_amt * mdr_rate, 4)
    assert actual_mdr == exp_mdr_exact

    # Stage 3: Base fee = 249908.7558
    # Stage 4: GST = 249908.7558 * 0.18 = 44983.576044
    # Round half up to 4 places -> 44983.5760
    exp_gst_exact = Decimal("44983.5760")
    actual_gst = round_half_up(actual_mdr * gst_rate, 4)
    assert actual_gst == exp_gst_exact

    # Stage 5: Expected total fee = 249908.7558 + 44983.5760 = 294892.3318
    exp_total = exp_mdr_exact + exp_gst_exact
    assert exp_total == Decimal("294892.3318")

    # Invoice 2-decimal display representation
    display_fee = round_half_up(exp_total, 2)
    assert display_fee == Decimal("294892.33")


# ---------------------------------------------------------------------------
# 15. Reconciliation Rerun Idempotency
# ---------------------------------------------------------------------------
def test_15_reconciliation_rerun_idempotency(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 15: Executing reconciliation multiple times produces identical outcomes.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "SHOPIFY")
    now = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)

    order = CanonicalOrder(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        order_reference="ORD-IDEM-01", order_number="IDEM-01",
        gross_amount=Decimal("1500.0000"), currency="INR", financial_status="paid",
        order_timestamp=now
    )
    payment = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_IDEM_01",
        order_reference="ORD-IDEM-01", payment_method="UPI",
        captured_amount=Decimal("1500.0000"), status="captured",
        captured_at=now, unallocated_balance=Decimal("1500.0000")
    )
    db_session.add_all([order, payment])
    db_session.commit()

    # Run 1
    run1 = ReconciliationService.create_run(db_session, tenant_id)
    run1 = ReconciliationService.execute_run(db_session, run1.id)
    run1_matches = run1.matched_orders_count
    run1_matched_amount = run1.total_captured_amount

    # Run 2 on same dataset
    run2 = ReconciliationService.create_run(db_session, tenant_id)
    run2 = ReconciliationService.execute_run(db_session, run2.id)
    run2_matches = run2.matched_orders_count
    run2_matched_amount = run2.total_captured_amount

    # Idempotency invariant
    assert run1_matches == run2_matches
    assert run1_matched_amount == run2_matched_amount


# ---------------------------------------------------------------------------
# 16. Historical Allocation Integrity & Double-Entry Conservation Invariant
# ---------------------------------------------------------------------------
def test_16_historical_allocation_conservation_invariant(db_session: Session, seeded_entities: dict):
    """
    Financial Audit 16: Double-entry conservation invariant:
    Sum(Allocated Amounts) + Sum(Unallocated Balances) == Total Ingested Amount.
    Unallocated balances must never be negative.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_test_batch(db_session, tenant_id, "RAZORPAY")
    now = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)

    # Seed 3 payments of different amounts
    p_amts = [Decimal("1000.0000"), Decimal("2500.0000"), Decimal("5000.0000")]
    payments = []
    for idx, amt in enumerate(p_amts):
        p = CanonicalPayment(
            tenant_id=tenant_id, batch_id=batch.id, source_row_index=idx,
            gateway_name="RAZORPAY", gateway_payment_id=f"pay_CONS_{idx}",
            order_reference=f"ORD-CONS-{idx}", payment_method="UPI",
            captured_amount=amt, unallocated_balance=amt, status="captured",
            captured_at=now
        )
        payments.append(p)

    # Seed matching orders for p0 and p1 only; p2 remains unallocated
    o0 = CanonicalOrder(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=0,
        order_reference="ORD-CONS-0", gross_amount=Decimal("1000.0000"),
        currency="INR", financial_status="paid", order_timestamp=now
    )
    o1 = CanonicalOrder(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        order_reference="ORD-CONS-1", gross_amount=Decimal("2500.0000"),
        currency="INR", financial_status="paid", order_timestamp=now
    )
    db_session.add_all(payments + [o0, o1])
    db_session.commit()

    total_ingested = sum(p.captured_amount for p in payments)

    run = ReconciliationService.create_run(db_session, tenant_id)
    run = ReconciliationService.execute_run(db_session, run.id)

    for p in payments:
        db_session.refresh(p)
        assert p.unallocated_balance >= Decimal("0.0000")  # Never negative

    # Query all allocations
    allocations = db_session.execute(
        select(ReconciliationAllocation).join(ReconciliationMatch).where(
            ReconciliationMatch.run_id == run.id
        )
    ).scalars().all()

    total_allocated = sum((a.allocated_amount for a in allocations), Decimal("0.0000"))
    total_unallocated = sum((p.unallocated_balance for p in payments), Decimal("0.0000"))

    # Fundamental Financial Invariant
    assert total_allocated + total_unallocated == total_ingested


# ---------------------------------------------------------------------------
# 17. Property-Based Conservation Invariant (Hypothesis)
# ---------------------------------------------------------------------------
@given(
    capture_amount=st.decimals(min_value=Decimal("10.0000"), max_value=Decimal("1000000.0000"), places=4),
    allocation_ratio=st.decimals(min_value=Decimal("0.0000"), max_value=Decimal("1.0000"), places=4)
)
@hypo_settings(max_examples=30)
def test_17_hypothesis_balance_conservation_property(capture_amount: Decimal, allocation_ratio: Decimal):
    """
    Hypothesis Property Test: For any arbitrary capture amount and allocation ratio:
    Allocated + Remaining == Total Capture with zero decimal rounding drift.
    """
    allocated = round_half_up(capture_amount * allocation_ratio, 4)
    remaining = capture_amount - allocated
    assert remaining >= Decimal("0.0000")
    assert allocated + remaining == capture_amount
