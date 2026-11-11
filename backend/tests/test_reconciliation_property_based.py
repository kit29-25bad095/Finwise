import uuid
from decimal import Decimal
from datetime import datetime, date, timezone
import pytest
from hypothesis import given, strategies as st, settings
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.canonical import CanonicalOrder, CanonicalPayment, CanonicalSettlement, CanonicalBankTransaction
from app.models.reconciliation import (
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    FeeContract,
    FeeScheduleTier,
    MatchClassification,
    AllocationStatus,
)
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.services.reconciliation.fee_calculator import FeeCalculator, round_half_up


@given(
    capture_amount=st.decimals(min_value=Decimal("1.0000"), max_value=Decimal("10000000.0000"), places=4),
    mdr_rate=st.decimals(min_value=Decimal("0.000000"), max_value=Decimal("0.050000"), places=6),
    gst_rate=st.decimals(min_value=Decimal("0.000000"), max_value=Decimal("0.280000"), places=6)
)
@settings(max_examples=50)
def test_hypothesis_fee_staged_rounding_properties(capture_amount: Decimal, mdr_rate: Decimal, gst_rate: Decimal):
    """
    Property: Fee calculation must be mathematically conservative and deterministic.
    For any valid monetary amount and rate, expected_total_fee >= 0 and never causes float errors.
    """
    dummy_tenant_id = uuid.uuid4()
    payment = CanonicalPayment(
        tenant_id=dummy_tenant_id,
        batch_id=uuid.uuid4(),
        source_row_index=1,
        gateway_payment_id="pay_PROP_TEST",
        payment_method="CARD",
        captured_amount=capture_amount,
        reported_fee=Decimal("0.0000"),
        reported_tax=Decimal("0.0000"),
        captured_at=datetime.now(timezone.utc),
        unallocated_balance=capture_amount
    )
    contract = FeeContract(
        tenant_id=dummy_tenant_id,
        contract_name="Hypothesis Contract",
        start_date=date(2026, 1, 1),
        gst_rate=gst_rate
    )
    contract.tiers = [
        FeeScheduleTier(
            contract_id=uuid.uuid4(),
            tenant_id=dummy_tenant_id,
            instrument_type="CARD",
            percentage_rate=mdr_rate,
            fixed_fee_per_txn=Decimal("0.0000")
        )
    ]

    res = FeeCalculator.calculate_payment_fees(payment, contract, fee_tolerance=Decimal("0.05"))

    assert res.nominal_capture_amount == capture_amount
    assert res.base_fee >= Decimal("0.0000")
    assert res.calculated_tax >= Decimal("0.0000")
    assert res.expected_total_fee >= Decimal("0.0000")
    assert res.expected_total_fee == res.base_fee + res.calculated_tax
    assert isinstance(res.expected_total_fee, Decimal)


def test_tenant_isolation_on_reconciliation(client: TestClient, db_session: Session, seeded_entities: dict):
    """
    Security Property: Tenant A's reconciliation run must NEVER match or allocate
    Tenant B's orders, payments, settlements, or bank transactions.
    """
    headers_a = seeded_entities["headers_a_admin"]
    headers_b = seeded_entities["headers_b_admin"]
    tenant_a_id = seeded_entities["tenant_a"].id
    tenant_b_id = seeded_entities["tenant_b"].id

    batch_a = IngestionBatch(tenant_id=tenant_a_id, source_type="SHOPIFY", filename="a.csv", file_hash_sha256="hash_a", file_size_bytes=100, status=IngestionStatus.COMPLETED)
    batch_b = IngestionBatch(tenant_id=tenant_b_id, source_type="RAZORPAY", filename="b.csv", file_hash_sha256="hash_b", file_size_bytes=100, status=IngestionStatus.COMPLETED)
    db_session.add_all([batch_a, batch_b])
    db_session.flush()

    now = datetime.now(timezone.utc)
    # Tenant A has an Order with reference "SHARED-REF-100"
    order_a = CanonicalOrder(
        tenant_id=tenant_a_id, batch_id=batch_a.id, source_row_index=1,
        order_reference="SHARED-REF-100", gross_amount=Decimal("5000.0000"),
        currency="INR", financial_status="paid", order_timestamp=now
    )
    # Tenant B has a Payment with the IDENTICAL reference "SHARED-REF-100"
    payment_b = CanonicalPayment(
        tenant_id=tenant_b_id, batch_id=batch_b.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_FOREIGN_TENANT_B",
        order_reference="SHARED-REF-100", payment_method="UPI",
        captured_amount=Decimal("5000.0000"), currency="INR", status="captured",
        captured_at=now, unallocated_balance=Decimal("5000.0000")
    )
    db_session.add_all([order_a, payment_b])
    db_session.commit()

    # Trigger run for Tenant A
    run_a_id = client.post("/api/v1/reconciliation/runs", headers=headers_a, json={}).json()["id"]

    # Verify that Tenant A's run DID NOT match payment_b!
    matches_a = client.get(f"/api/v1/reconciliation/runs/{run_a_id}/matches", headers=headers_a).json()
    assert len(matches_a) == 1
    # Order A must be classified as UNMATCHED because payment_b belongs to Tenant B
    assert matches_a[0]["classification"] == MatchClassification.UNMATCHED.value
    assert matches_a[0]["order_id"] == str(order_a.id)

    # Cross-tenant access check: Tenant B cannot view Tenant A's reconciliation run
    unauthorized_view = client.get(f"/api/v1/reconciliation/runs/{run_a_id}", headers=headers_b)
    assert unauthorized_view.status_code == 404


def test_idempotent_reruns_and_immutable_run_history(client: TestClient, db_session: Session, seeded_entities: dict):
    """
    Architectural Mandate: Re-running reconciliation creates a new run (Run N+1),
    supersedes Run N allocations, and never corrupts historical data.
    """
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id

    batch = IngestionBatch(tenant_id=tenant_id, source_type="SHOPIFY", filename="run_test.csv", file_hash_sha256="hash_rerun_01", file_size_bytes=500, status=IngestionStatus.COMPLETED)
    db_session.add(batch)
    db_session.flush()

    now = datetime.now(timezone.utc)
    order = CanonicalOrder(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        order_reference="ORD-RERUN-1", gross_amount=Decimal("1500.0000"),
        currency="INR", financial_status="paid", order_timestamp=now
    )
    payment = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_RERUN_1",
        order_reference="ORD-RERUN-1", payment_method="UPI",
        captured_amount=Decimal("1500.0000"), currency="INR", status="captured",
        captured_at=now, unallocated_balance=Decimal("1500.0000")
    )
    db_session.add_all([order, payment])
    db_session.commit()

    # 1. Run 1
    run_1_resp = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert run_1_resp.status_code == 201
    run_1 = run_1_resp.json()
    assert run_1["run_number"] == 1
    assert run_1["is_active"] == True

    # 2. Run 2 (Rerun)
    run_2_resp = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert run_2_resp.status_code == 201
    run_2 = run_2_resp.json()
    assert run_2["run_number"] == 2
    assert run_2["is_active"] == True

    # 3. Check Run 1 is now superseded (is_active = False)
    run_1_refreshed = client.get(f"/api/v1/reconciliation/runs/{run_1['id']}", headers=headers).json()
    assert run_1_refreshed["is_active"] == False

    # 4. Verify immutable history: Both runs still exist
    all_runs = client.get("/api/v1/reconciliation/runs", headers=headers).json()
    assert len(all_runs) == 2
