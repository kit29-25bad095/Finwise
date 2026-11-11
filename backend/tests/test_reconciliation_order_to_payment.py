import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
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
    MatchType,
    ReviewStatus,
)
from app.models.ingestion import IngestionBatch, IngestionStatus


def seed_ingestion_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="SHOPIFY",
        filename="orders.csv",
        file_hash_sha256="dummy_hash_" + str(uuid.uuid4())[:8],
        file_size_bytes=1000,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.commit()
    return batch


def test_exact_order_to_payment_matching(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_ingestion_batch(db_session, tenant_id)

    # 1. Seed Order and Payment with identical reference & amount
    now = datetime.now(timezone.utc)
    order = CanonicalOrder(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        order_reference="ORD-5501",
        order_number="5501",
        gross_amount=Decimal("3499.0000"),
        currency="INR",
        financial_status="paid",
        order_timestamp=now
    )
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_K1001A",
        order_reference="ORD-5501",
        payment_method="UPI",
        captured_amount=Decimal("3499.0000"),
        reported_fee=Decimal("0.0000"),
        reported_tax=Decimal("0.0000"),
        currency="INR",
        status="captured",
        captured_at=now,
        unallocated_balance=Decimal("3499.0000")
    )
    db_session.add_all([order, payment])
    db_session.commit()

    # 2. Trigger Reconciliation Run
    response = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert response.status_code == 201
    run_id = response.json()["id"]

    # 3. Verify Run Metrics
    run_resp = client.get(f"/api/v1/reconciliation/runs/{run_id}", headers=headers)
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["matched_orders_count"] == 1
    assert run_data["matched_payments_count"] == 1
    assert run_data["unmatched_orders_count"] == 0

    # 4. Verify Match Classification
    matches_resp = client.get(f"/api/v1/reconciliation/runs/{run_id}/matches", headers=headers)
    assert matches_resp.status_code == 200
    matches = matches_resp.json()
    assert len(matches) == 1
    match = matches[0]
    assert match["match_type"] == MatchType.ORDER_TO_PAYMENT.value
    assert match["classification"] == MatchClassification.EXACT_MATCH.value
    assert match["pass_number"] == 1
    assert Decimal(match["confidence_score"]) == Decimal("1.0000")
    assert Decimal(match["allocated_amount"]) == Decimal("3499.0000")
    assert Decimal(match["discrepancy_amount"]) == Decimal("0.0000")

    # 5. Verify Double-Entry Allocation Ledger
    allocs_resp = client.get(f"/api/v1/reconciliation/runs/{run_id}/allocations", headers=headers)
    assert allocs_resp.status_code == 200
    allocs = allocs_resp.json()
    assert len(allocs) == 1
    assert Decimal(allocs[0]["allocated_amount"]) == Decimal("3499.0000")
    assert allocs[0]["source_entity_type"] == "canonical_orders"
    assert allocs[0]["target_entity_type"] == "canonical_payments"


def test_partial_payment_matching_with_discrepancy(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_ingestion_batch(db_session, tenant_id)

    # Order of ₹10,000, but payment received is only ₹4,000 (partial/installment)
    now = datetime.now(timezone.utc)
    order = CanonicalOrder(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        order_reference="ORD-PARTIAL-88",
        order_number="88",
        gross_amount=Decimal("10000.0000"),
        currency="INR",
        financial_status="partially_paid",
        order_timestamp=now
    )
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_PARTIAL_01",
        order_reference="ORD-PARTIAL-88",
        payment_method="UPI",
        captured_amount=Decimal("4000.0000"),
        reported_fee=Decimal("0.0000"),
        reported_tax=Decimal("0.0000"),
        currency="INR",
        status="captured",
        captured_at=now,
        unallocated_balance=Decimal("4000.0000")
    )
    db_session.add_all([order, payment])
    db_session.commit()

    # Trigger run
    response = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert response.status_code == 201
    run_id = response.json()["id"]

    matches_resp = client.get(f"/api/v1/reconciliation/runs/{run_id}/matches", headers=headers)
    matches = matches_resp.json()
    assert len(matches) == 1
    match = matches[0]
    assert match["classification"] == MatchClassification.PARTIAL_MATCH.value
    assert Decimal(match["source_amount"]) == Decimal("10000.0000")
    assert Decimal(match["target_amount"]) == Decimal("4000.0000")
    assert Decimal(match["allocated_amount"]) == Decimal("4000.0000")
    assert Decimal(match["discrepancy_amount"]) == Decimal("6000.0000")
    assert match["review_status"] == ReviewStatus.PENDING_REVIEW.value


def test_unmatched_order_and_unmatched_payment_visibility(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_ingestion_batch(db_session, tenant_id)

    now = datetime.now(timezone.utc)
    # Order with no matching payment
    orphan_order = CanonicalOrder(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        order_reference="ORD-ORPHAN-99",
        gross_amount=Decimal("2500.0000"),
        currency="INR",
        financial_status="pending",
        order_timestamp=now
    )
    # Payment with no matching order
    orphan_payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_ORPHAN_99",
        order_reference="UNKNOWN-REF-X",
        payment_method="UPI",
        captured_amount=Decimal("1200.0000"),
        currency="INR",
        status="captured",
        captured_at=now,
        unallocated_balance=Decimal("1200.0000")
    )
    db_session.add_all([orphan_order, orphan_payment])
    db_session.commit()

    response = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert response.status_code == 201
    run_id = response.json()["id"]

    # Verify unmatched endpoint
    unmatched_resp = client.get(f"/api/v1/reconciliation/runs/{run_id}/unmatched", headers=headers)
    assert unmatched_resp.status_code == 200
    unmatched = unmatched_resp.json()
    assert len(unmatched["unmatched_orders"]) == 1
    assert unmatched["unmatched_orders"][0]["order_reference"] == "ORD-ORPHAN-99"
    assert len(unmatched["unmatched_payments"]) == 1
    assert unmatched["unmatched_payments"][0]["gateway_payment_id"] == "pay_ORPHAN_99"
