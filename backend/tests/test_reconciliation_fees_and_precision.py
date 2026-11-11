import uuid
from decimal import Decimal
from datetime import datetime, date, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.canonical import CanonicalOrder, CanonicalPayment
from app.models.reconciliation import (
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    FeeContract,
    FeeScheduleTier,
    MatchClassification,
    ReviewStatus,
)
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.services.reconciliation.fee_calculator import FeeCalculator, round_half_up


def test_six_stage_financial_rounding_precision():
    """
    Direct unit test verifying the 6-stage financial rounding architecture.
    """
    # Create mock payment of ₹1,42,80,500.00
    capture_amt = Decimal("14280500.0000")
    dummy_tenant_id = uuid.uuid4()
    payment = CanonicalPayment(
        tenant_id=dummy_tenant_id,
        batch_id=uuid.uuid4(),
        source_row_index=1,
        gateway_payment_id="pay_STAGE_TEST",
        payment_method="UPI",
        captured_amount=capture_amt,
        reported_fee=Decimal("0.0000"),
        reported_tax=Decimal("0.0000"),
        captured_at=datetime.now(timezone.utc),
        unallocated_balance=capture_amt
    )

    # 1.5% MDR + 18% GST contract
    contract = FeeContract(
        tenant_id=dummy_tenant_id,
        contract_name="Corporate Tier",
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000")
    )
    tier = FeeScheduleTier(
        contract_id=uuid.uuid4(),
        tenant_id=dummy_tenant_id,
        instrument_type="UPI",
        percentage_rate=Decimal("0.015000"),  # 1.5%
        fixed_fee_per_txn=Decimal("0.0000")
    )
    contract.tiers = [tier]

    res = FeeCalculator.calculate_payment_fees(payment, contract, fee_tolerance=Decimal("0.05"))

    # Stage 1: Nominal Capture Amount
    assert res.nominal_capture_amount == Decimal("14280500.0000")
    # Stage 2: Contractual MDR = 14280500 * 0.015 = 214207.5000
    assert res.unrounded_mdr == Decimal("214207.5000")
    # Stage 3: Base fee = 214207.5000
    assert res.base_fee == Decimal("214207.5000")
    # Stage 4: GST = 214207.5000 * 0.18 = 38557.3500
    assert res.calculated_tax == Decimal("38557.3500")
    # Stage 5: Expected Total Fee = 214207.5000 + 38557.3500 = 252764.8500
    assert res.expected_total_fee == Decimal("252764.8500")
    assert res.expected_total_fee_display == Decimal("252764.85")


def test_contract_fee_overcharge_detection_via_reconciliation(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id

    # 1. Create active FeeContract via API: 2.0% MDR + 18% GST for CREDIT cards
    contract_payload = {
        "gateway_name": "RAZORPAY",
        "contract_name": "Enterprise 2 Percent Plus GST",
        "start_date": "2026-01-01",
        "gst_rate": "0.180000",
        "chargeback_dispute_fee": "500.0000",
        "tiers": [
            {
                "instrument_type": "CREDIT",
                "percentage_rate": "0.020000",  # 2.0%
                "fixed_fee_per_txn": "0.0000"
            }
        ]
    }
    c_resp = client.post("/api/v1/reconciliation/contracts", headers=headers, json=contract_payload)
    assert c_resp.status_code == 201

    # 2. Seed Order and Payment
    # Payment = ₹10,000. Expected fee = ₹200 (MDR) + ₹36 (GST) = ₹236.00
    # BUT reported fee is ₹350.00! Overcharge of ₹114.00!
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="overcharge_test.csv",
        file_hash_sha256="hash_overcharge_01",
        file_size_bytes=500,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()

    now = datetime.now(timezone.utc)
    order = CanonicalOrder(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        order_reference="ORD-FEE-TEST-1",
        gross_amount=Decimal("10000.0000"),
        currency="INR",
        financial_status="paid",
        order_timestamp=now
    )
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_FEE_OVERCHARGE",
        order_reference="ORD-FEE-TEST-1",
        payment_method="CREDIT",
        captured_amount=Decimal("10000.0000"),
        reported_fee=Decimal("296.6100"),
        reported_tax=Decimal("53.3900"),  # Total reported = ₹350.00
        currency="INR",
        status="captured",
        captured_at=now,
        unallocated_balance=Decimal("10000.0000")
    )
    db_session.add_all([order, payment])
    db_session.commit()

    # 3. Trigger Run
    run_resp = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert run_resp.status_code == 201
    run_id = run_resp.json()["id"]

    # 4. Check Match details: Fee overcharge flagged
    matches = client.get(f"/api/v1/reconciliation/runs/{run_id}/matches", headers=headers).json()
    assert len(matches) == 1
    match = matches[0]
    assert Decimal(match["expected_fee"]) == Decimal("236.0000")
    assert Decimal(match["fee_discrepancy"]) == Decimal("114.0000")
    assert match["review_status"] == ReviewStatus.PENDING_REVIEW.value


def test_human_review_and_rbac_permissions(client: TestClient, db_session: Session, seeded_entities: dict):
    headers_admin = seeded_entities["headers_a_admin"]
    headers_auditor = seeded_entities["headers_a_auditor"]
    tenant_id = seeded_entities["tenant_a"].id

    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="SHOPIFY",
        filename="review_test.csv",
        file_hash_sha256="hash_review_01",
        file_size_bytes=500,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()

    # Order with slight price discrepancy requiring review
    now = datetime.now(timezone.utc)
    order = CanonicalOrder(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        order_reference="ORD-REVIEW-ME", gross_amount=Decimal("5000.0000"),
        currency="INR", financial_status="paid", order_timestamp=now
    )
    payment = CanonicalPayment(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", gateway_payment_id="pay_REVIEW_ME",
        order_reference="ORD-REVIEW-ME", payment_method="UPI",
        captured_amount=Decimal("4950.0000"), reported_fee=Decimal("0.0000"),
        reported_tax=Decimal("0.0000"), currency="INR", status="captured",
        captured_at=now, unallocated_balance=Decimal("4950.0000")
    )
    db_session.add_all([order, payment])
    db_session.commit()

    run_id = client.post("/api/v1/reconciliation/runs", headers=headers_admin, json={}).json()["id"]
    matches = client.get(f"/api/v1/reconciliation/runs/{run_id}/matches", headers=headers_admin).json()
    match_id = matches[0]["id"]

    # 1. AUDITOR attempts to review -> 403 Forbidden
    auditor_resp = client.post(
        f"/api/v1/reconciliation/matches/{match_id}/resolve",
        headers=headers_auditor,
        json={"action": "APPROVE", "notes": "Auditor approving without permission"}
    )
    assert auditor_resp.status_code == 403

    # 2. ADMIN reviews and approves -> 200 OK
    admin_resp = client.post(
        f"/api/v1/reconciliation/matches/{match_id}/resolve",
        headers=headers_admin,
        json={"action": "APPROVE", "notes": "Authorized discount accepted by CFO"}
    )
    assert admin_resp.status_code == 200
    resolved = admin_resp.json()
    assert resolved["review_status"] == ReviewStatus.APPROVED.value
    assert resolved["review_action"] == "APPROVE"
    assert resolved["review_notes"] == "Authorized discount accepted by CFO"
