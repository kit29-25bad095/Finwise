import uuid
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.canonical import CanonicalSettlement, CanonicalBankTransaction
from app.models.reconciliation import (
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    MatchClassification,
    MatchType,
    ReviewStatus,
)
from app.models.ingestion import IngestionBatch, IngestionStatus


def seed_ingestion_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="settlements.csv",
        file_hash_sha256="dummy_hash_" + str(uuid.uuid4())[:8],
        file_size_bytes=1000,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.commit()
    return batch


def test_pass_2_exact_utr_settlement_to_bank_match(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_ingestion_batch(db_session, tenant_id)

    utr_num = "HDFCR520261112001"
    now = datetime.now(timezone.utc)

    settlement = CanonicalSettlement(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        settlement_reference="SETL-20261112-01",
        utr_number=utr_num,
        gross_amount=Decimal("150000.0000"),
        total_fee=Decimal("3000.0000"),
        total_tax=Decimal("540.0000"),
        net_settlement_amount=Decimal("146460.0000"),
        unallocated_balance=Decimal("146460.0000"),
        status="settled",
        settled_at=now
    )
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        bank_name="HDFC",
        bank_reference="CHQ99001",
        extracted_utr=utr_num,
        raw_narration=f"CMS/RZP/NODAL/{utr_num}/SETL-20261112-01",
        transaction_date=now.date(),
        value_date=now.date(),
        credit_amount=Decimal("146460.0000"),
        debit_amount=Decimal("0.0000"),
        unallocated_balance=Decimal("146460.0000")
    )
    db_session.add_all([settlement, bank_tx])
    db_session.commit()

    response = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert response.status_code == 201
    run_id = response.json()["id"]

    matches_resp = client.get(f"/api/v1/reconciliation/runs/{run_id}/matches", headers=headers)
    matches = matches_resp.json()
    assert len(matches) == 1
    match = matches[0]
    assert match["match_type"] == MatchType.SETTLEMENT_TO_BANK.value
    assert match["classification"] == MatchClassification.EXACT_MATCH.value
    assert match["pass_number"] == 2
    assert Decimal(match["confidence_score"]) == Decimal("1.0000")
    assert Decimal(match["allocated_amount"]) == Decimal("146460.0000")

    # Check that balances were conserved and decremented to zero
    db_session.refresh(settlement)
    db_session.refresh(bank_tx)
    assert settlement.unallocated_balance == Decimal("0.0000")
    assert bank_tx.unallocated_balance == Decimal("0.0000")


def test_pass_3_collision_guard_blocks_auto_match(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_ingestion_batch(db_session, tenant_id)

    # 1 Settlement, but TWO Bank Transactions with identical ₹25,000 credit in the window
    # Neither has a UTR match. Engine MUST block auto-matching and flag AMBIGUOUS_MATCH!
    s_date = date(2026, 11, 10)
    settlement = CanonicalSettlement(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        settlement_reference="SETL-COLLIDE-01",
        utr_number=None,  # No UTR
        gross_amount=Decimal("25500.0000"),
        net_settlement_amount=Decimal("25000.0000"),
        unallocated_balance=Decimal("25000.0000"),
        status="settled",
        settled_at=datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
    )
    bank_tx_1 = CanonicalBankTransaction(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        bank_name="HDFC",
        bank_reference="REF_A_COLLIDE",
        raw_narration="RTGS CREDIT-NODAL CLEARING 1",
        transaction_date=date(2026, 11, 11),
        credit_amount=Decimal("25000.0000"),
        unallocated_balance=Decimal("25000.0000")
    )
    bank_tx_2 = CanonicalBankTransaction(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        bank_name="HDFC",
        bank_reference="REF_B_COLLIDE",
        raw_narration="RTGS CREDIT-NODAL CLEARING 2",
        transaction_date=date(2026, 11, 12),
        credit_amount=Decimal("25000.0000"),
        unallocated_balance=Decimal("25000.0000")
    )
    db_session.add_all([settlement, bank_tx_1, bank_tx_2])
    db_session.commit()

    response = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert response.status_code == 201
    run_id = response.json()["id"]

    run_data = client.get(f"/api/v1/reconciliation/runs/{run_id}", headers=headers).json()
    assert run_data["ambiguous_matches_count"] >= 1

    ambiguous_resp = client.get(f"/api/v1/reconciliation/runs/{run_id}/ambiguous", headers=headers)
    assert ambiguous_resp.status_code == 200
    ambiguous = ambiguous_resp.json()
    assert len(ambiguous) >= 1
    amb = ambiguous[0]
    assert amb["classification"] == MatchClassification.AMBIGUOUS_MATCH.value
    assert Decimal(amb["allocated_amount"]) == Decimal("0.0000")  # Zero auto-allocation!
    assert amb["review_status"] == ReviewStatus.PENDING_REVIEW.value


def test_pass_5_bounded_aggregation_exact_subset_found(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_ingestion_batch(db_session, tenant_id)

    # 3 settlement batches (nodal clearing aggregation):
    # ₹15,000 + ₹25,000 + ₹35,000 = ₹75,000
    # Single bank credit of ₹75,000
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    s1 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-AGG-1",
        gross_amount=Decimal("15000.0000"), net_settlement_amount=Decimal("15000.0000"),
        unallocated_balance=Decimal("15000.0000"), settled_at=now
    )
    s2 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=2,
        gateway_name="RAZORPAY", settlement_reference="SETL-AGG-2",
        gross_amount=Decimal("25000.0000"), net_settlement_amount=Decimal("25000.0000"),
        unallocated_balance=Decimal("25000.0000"), settled_at=now
    )
    s3 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=3,
        gateway_name="RAZORPAY", settlement_reference="SETL-AGG-3",
        gross_amount=Decimal("35000.0000"), net_settlement_amount=Decimal("35000.0000"),
        unallocated_balance=Decimal("35000.0000"), settled_at=now
    )
    bank_credit = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        bank_name="HDFC", bank_reference="BULK_NODAL_PAYOUT",
        raw_narration="RAZORPAY NODAL SETTLEMENT CONSOLIDATED",
        transaction_date=date(2026, 11, 11),
        credit_amount=Decimal("75000.0000"), unallocated_balance=Decimal("75000.0000")
    )
    db_session.add_all([s1, s2, s3, bank_credit])
    db_session.commit()

    response = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert response.status_code == 201
    run_id = response.json()["id"]

    matches = client.get(f"/api/v1/reconciliation/runs/{run_id}/matches?classification=AGGREGATED_MATCH", headers=headers).json()
    assert len(matches) == 1
    match = matches[0]
    assert match["classification"] == MatchClassification.AGGREGATED_MATCH.value
    assert match["pass_number"] == 5
    assert Decimal(match["allocated_amount"]) == Decimal("75000.0000")

    # Verify that individual allocations exist for all 3 settlement batches
    allocs = client.get(f"/api/v1/reconciliation/runs/{run_id}/allocations", headers=headers).json()
    assert len(allocs) == 3
    alloc_sums = sum(Decimal(a["allocated_amount"]) for a in allocs)
    assert alloc_sums == Decimal("75000.0000")

    # Balances must be fully consumed
    db_session.refresh(s1)
    db_session.refresh(s2)
    db_session.refresh(s3)
    db_session.refresh(bank_credit)
    assert s1.unallocated_balance == Decimal("0.0000")
    assert s2.unallocated_balance == Decimal("0.0000")
    assert s3.unallocated_balance == Decimal("0.0000")
    assert bank_credit.unallocated_balance == Decimal("0.0000")


def test_pass_5_unresolved_subset_bound_exceeded_never_forces_match(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_ingestion_batch(db_session, tenant_id)

    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    # Bank credit of ₹1,000,000 but only two small settlements of ₹500 and ₹700
    s1 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-TINY-1",
        gross_amount=Decimal("500.0000"), net_settlement_amount=Decimal("500.0000"),
        unallocated_balance=Decimal("500.0000"), settled_at=now
    )
    s2 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=2,
        gateway_name="RAZORPAY", settlement_reference="SETL-TINY-2",
        gross_amount=Decimal("700.0000"), net_settlement_amount=Decimal("700.0000"),
        unallocated_balance=Decimal("700.0000"), settled_at=now
    )
    huge_credit = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        bank_name="HDFC", bank_reference="HUGE_TX_001",
        raw_narration="RAZORPAY NODAL HUGE CREDIT",
        transaction_date=date(2026, 11, 11),
        credit_amount=Decimal("1000000.0000"), unallocated_balance=Decimal("1000000.0000")
    )
    db_session.add_all([s1, s2, huge_credit])
    db_session.commit()

    response = client.post("/api/v1/reconciliation/runs", headers=headers, json={})
    assert response.status_code == 201
    run_id = response.json()["id"]

    run_data = client.get(f"/api/v1/reconciliation/runs/{run_id}", headers=headers).json()
    assert run_data["unresolved_count"] >= 1

    unresolved_matches = client.get(
        f"/api/v1/reconciliation/runs/{run_id}/matches?classification=UNRESOLVED_SUBSET_BOUND_EXCEEDED",
        headers=headers
    ).json()
    assert len(unresolved_matches) == 1
    unres = unresolved_matches[0]
    assert Decimal(unres["allocated_amount"]) == Decimal("0.0000")
    assert unres["review_status"] == ReviewStatus.PENDING_REVIEW.value
    # Guarantee: huge credit unallocated balance remains untouched
    db_session.refresh(huge_credit)
    assert huge_credit.unallocated_balance == Decimal("1000000.0000")
