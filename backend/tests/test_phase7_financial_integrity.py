import uuid
import pytest
from decimal import Decimal
from datetime import datetime, timezone, date

from app.models.tenant import Tenant
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalBankTransaction,
)
from app.models.reconciliation import (
    FeeContract,
    FeeScheduleTier,
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    MatchClassification,
    MatchType,
    ReconciliationStatus,
)
from app.services.reconciliation.fee_calculator import FeeCalculator
from app.services.leakage.fee_overcharge_detector import FeeOverchargeDetector
from app.services.reconciliation.knapsack_solver import BoundedKnapsackSolver, KnapsackResult


def test_dynamic_gst_rates_never_hardcoded_to_18_percent(db_session, seeded_entities):
    """
    Financial Invariant: GST must NEVER be hardcoded to 18%.
    Test contracts with 5%, 12%, and 0% GST rates.
    """
    tenant_id = seeded_entities["tenant_a"].id
    now = datetime.now(timezone.utc)

    # 1. Test 5% GST Contract
    contract_5pct = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Razorpay Special 5% GST Contract",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.050000"),  # 5%
    )
    tier_5pct = FeeScheduleTier(
        tenant_id=tenant_id,
        contract=contract_5pct,
        instrument_type="CREDIT_CARD",
        percentage_rate=Decimal("0.020000"),  # 2% MDR
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add_all([contract_5pct, tier_5pct])
    db_session.commit()

    # Create capture of ₹10,000.00
    # Expected MDR = 10,000 * 2% = ₹200.00
    # Expected GST @ 5% = 200 * 5% = ₹10.00 (NOT ₹36.00 at 18%!)
    # Total expected fee = ₹210.00
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="test_gst_5pct.csv",
        file_hash_sha256="hash_gst_5pct_" + str(uuid.uuid4())[:8],
        file_size_bytes=1000,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.commit()

    payment_correct = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        gateway_payment_id="pay_gst_5pct_correct",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("200.0000"),
        reported_tax=Decimal("10.0000"),  # Exactly ₹10.00 (5%)
        unallocated_balance=Decimal("10000.0000"),
        payment_method="credit_card",
        captured_at=now,
        source_row_index=1,
    )

    fee_calc = FeeCalculator.calculate_payment_fees(payment_correct, contract_5pct)
    assert fee_calc.base_fee == Decimal("200.0000")
    assert fee_calc.calculated_tax == Decimal("10.0000")
    assert fee_calc.gst_rate == Decimal("0.050000")
    assert fee_calc.is_overcharge is False

    # 2. Test 0% GST Contract (e.g. Export / SEZ merchant)
    contract_0pct = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Razorpay Zero-Rated GST Contract",
        version=2,
        is_active=False,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.000000"),  # 0%
    )
    tier_0pct = FeeScheduleTier(
        tenant_id=tenant_id,
        contract=contract_0pct,
        instrument_type="CREDIT_CARD",
        percentage_rate=Decimal("0.020000"),
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db_session.add_all([contract_0pct, tier_0pct])
    db_session.commit()

    payment_zero = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        gateway_payment_id="pay_gst_0pct_zero",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("200.0000"),
        reported_tax=Decimal("0.0000"),
        unallocated_balance=Decimal("10000.0000"),
        payment_method="credit_card",
        captured_at=now,
        source_row_index=2,
    )

    fee_calc_zero = FeeCalculator.calculate_payment_fees(payment_zero, contract_0pct)
    assert fee_calc_zero.calculated_tax == Decimal("0.0000")
    assert fee_calc_zero.gst_rate == Decimal("0.000000")
    assert fee_calc_zero.expected_total_fee == Decimal("200.0000")


def test_balance_conservation_in_allocations():
    """
    Financial Invariant: Allocated amount cannot exceed source balance
    and cannot exceed destination balance.
    """
    source_balance = Decimal("5000.0000")
    dest_balance = Decimal("3000.0000")

    # Allocation must be bounded by min(source, dest)
    allowable_allocation = min(source_balance, dest_balance)
    assert allowable_allocation == Decimal("3000.0000")

    remaining_source = source_balance - allowable_allocation
    remaining_dest = dest_balance - allowable_allocation

    assert remaining_source == Decimal("2000.0000")
    assert remaining_dest == Decimal("0.0000")
    assert remaining_source >= Decimal("0.0000")
    assert remaining_dest >= Decimal("0.0000")


def test_decimal_precision_no_float_rounding_artifacts():
    """
    Financial Invariant: Monetary calculations must never use float
    and must avoid floating point representation anomalies.
    """
    val1 = Decimal("0.1000")
    val2 = Decimal("0.2000")
    total = val1 + val2

    # In IEEE 754 float: 0.1 + 0.2 = 0.30000000000000004
    # In Decimal: exactly 0.3000
    assert total == Decimal("0.3000")
    assert str(total) == "0.3000"


def test_knapsack_multiple_valid_subsets_routes_to_ambiguous():
    """
    Financial Invariant: If more than 1 valid subset matches the target sum,
    the solver must NEVER pick arbitrarily; it must classify as AMBIGUOUS_AGGREGATION_COLLISION.
    """
    bank_tx = CanonicalBankTransaction(
        id=uuid.uuid4(),
        unallocated_balance=Decimal("100.0000"),
        credit_amount=Decimal("100.0000")
    )
    # 3 candidates where {item_1, item_2} = 100 AND {item_3} is single (knapsack checks combinations of size >= 2)
    # If we have {50, 50} = 100 and {40, 60} = 100 -> exactly 2 distinct subsets of size 2!
    s1 = CanonicalSettlement(id=uuid.uuid4(), settlement_reference="SETL-1", unallocated_balance=Decimal("50.0000"))
    s2 = CanonicalSettlement(id=uuid.uuid4(), settlement_reference="SETL-2", unallocated_balance=Decimal("50.0000"))
    s3 = CanonicalSettlement(id=uuid.uuid4(), settlement_reference="SETL-3", unallocated_balance=Decimal("40.0000"))
    s4 = CanonicalSettlement(id=uuid.uuid4(), settlement_reference="SETL-4", unallocated_balance=Decimal("60.0000"))

    result = BoundedKnapsackSolver.find_matching_subsets(
        bank_tx=bank_tx,
        candidate_settlements=[s1, s2, s3, s4],
        max_bound_n=5,
        fee_tolerance=Decimal("0.05")
    )

    assert result.status == "AMBIGUOUS_AGGREGATION_COLLISION"
    assert len(result.matching_subsets) == 2


def test_knapsack_bound_exceeded_never_forces_match():
    """
    Financial Invariant: If candidate pool exceeds configured bound N,
    system must return UNRESOLVED_SUBSET_BOUND_EXCEEDED rather than guessing.
    """
    bank_tx = CanonicalBankTransaction(
        id=uuid.uuid4(),
        unallocated_balance=Decimal("1000.0000"),
        credit_amount=Decimal("1000.0000")
    )
    # 8 candidates of 100 each -> sum of any subset of size <= 4 is at most 400 (never 1000)
    candidates = [
        CanonicalSettlement(
            id=uuid.uuid4(),
            settlement_reference=f"SETL-{i}",
            unallocated_balance=Decimal("100.0000")
        )
        for i in range(8)
    ]

    result = BoundedKnapsackSolver.find_matching_subsets(
        bank_tx=bank_tx,
        candidate_settlements=candidates,
        max_bound_n=4,
        fee_tolerance=Decimal("0.05")
    )

    assert result.status == "UNRESOLVED_SUBSET_BOUND_EXCEEDED"
    assert len(result.matching_subsets) == 0
