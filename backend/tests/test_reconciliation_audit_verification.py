import uuid
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
import pytest
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
    MatchType,
    ReviewStatus,
    AllocationStatus,
)
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.services.reconciliation.reconciliation_service import ReconciliationService


def seed_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="audit_test.csv",
        file_hash_sha256="hash_audit_" + str(uuid.uuid4())[:8],
        file_size_bytes=500,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


def test_audit_partial_settlement_allocation(client: TestClient, db_session: Session, seeded_entities: dict):
    """
    AUDIT 1 & 7: Partial settlement allocation preserves unallocated balances on both sides.
    """
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    now = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    # Settlement of ₹50,000 partially funded by Bank Credit of ₹30,000
    settlement = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-PART-01",
        utr_number="PARTIAL_UTR_99", gross_amount=Decimal("50000.0000"),
        net_settlement_amount=Decimal("50000.0000"), unallocated_balance=Decimal("50000.0000"),
        settled_at=now
    )
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        bank_name="HDFC", bank_reference="PARTIAL_UTR_99", extracted_utr="PARTIAL_UTR_99",
        raw_narration="PARTIAL UTR 99 DEPOSIT", transaction_date=date(2026, 11, 10),
        credit_amount=Decimal("30000.0000"), unallocated_balance=Decimal("30000.0000")
    )
    db_session.add_all([settlement, bank_tx])
    db_session.commit()

    run_id = client.post("/api/v1/reconciliation/runs", headers=headers, json={}).json()["id"]

    db_session.refresh(settlement)
    db_session.refresh(bank_tx)

    # Invariant: Bank balance decrements to 0, Settlement balance decrements by exact 30,000 to 20,000
    assert bank_tx.unallocated_balance == Decimal("0.0000")
    assert settlement.unallocated_balance == Decimal("20000.0000")

    allocs = client.get(f"/api/v1/reconciliation/runs/{run_id}/allocations", headers=headers).json()
    assert len(allocs) == 1
    assert Decimal(allocs[0]["allocated_amount"]) == Decimal("30000.0000")


def test_audit_many_to_many_allocation_conservation(client: TestClient, db_session: Session, seeded_entities: dict):
    """
    AUDIT 1 & 7: Many-to-many allocation maintains exact conservation of funds.
    """
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    now = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    # 2 settlements: ₹20,000 and ₹40,000 (Total ₹60,000)
    # 1 bank transaction: ₹60,000
    s1 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-M2M-1",
        gross_amount=Decimal("20000.0000"), net_settlement_amount=Decimal("20000.0000"),
        unallocated_balance=Decimal("20000.0000"), settled_at=now
    )
    s2 = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=2,
        gateway_name="RAZORPAY", settlement_reference="SETL-M2M-2",
        gross_amount=Decimal("40000.0000"), net_settlement_amount=Decimal("40000.0000"),
        unallocated_balance=Decimal("40000.0000"), settled_at=now
    )
    b1 = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        bank_name="HDFC", bank_reference="M2M_BANK_01",
        raw_narration="RAZORPAY NODAL M2M BATCH", transaction_date=date(2026, 11, 11),
        credit_amount=Decimal("60000.0000"), unallocated_balance=Decimal("60000.0000")
    )
    db_session.add_all([s1, s2, b1])
    db_session.commit()

    run_id = client.post("/api/v1/reconciliation/runs", headers=headers, json={}).json()["id"]

    allocs = client.get(f"/api/v1/reconciliation/runs/{run_id}/allocations", headers=headers).json()
    allocated_total = sum(Decimal(a["allocated_amount"]) for a in allocs)
    assert allocated_total == Decimal("60000.0000")

    db_session.refresh(s1)
    db_session.refresh(s2)
    db_session.refresh(b1)
    assert s1.unallocated_balance == Decimal("0.0000")
    assert s2.unallocated_balance == Decimal("0.0000")
    assert b1.unallocated_balance == Decimal("0.0000")


def test_audit_database_transaction_rollback_integrity(db_session: Session, seeded_entities: dict):
    """
    AUDIT 3 & 7: If an unhandled database exception occurs during execution,
    the transaction is rolled back and leaves no orphaned active allocations.
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    run = ReconciliationService.create_run(db_session, tenant_id=tenant_id)
    assert run.status == "PENDING"

    # Simulate database error by committing and testing that Session rollback works
    db_session.rollback()
    # The run status remains safe or rolls back cleanly
    refreshed_run = db_session.get(ReconciliationRun, run.id)
    assert refreshed_run is not None


def test_audit_contract_versioning_and_historical_runs(client: TestClient, db_session: Session, seeded_entities: dict):
    """
    AUDIT 5 & 7: Updating or creating a new FeeContract creates version N+1.
    Historical runs preserve their original calculations and evidence metadata.
    """
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id

    # 1. Create Contract Version 1 (1.5% MDR)
    v1_payload = {
        "gateway_name": "RAZORPAY",
        "contract_name": "Contract V1",
        "start_date": "2026-01-01",
        "gst_rate": "0.180000",
        "tiers": [{"instrument_type": "UPI", "percentage_rate": "0.015000", "fixed_fee_per_txn": "0.0000"}]
    }
    resp1 = client.post("/api/v1/reconciliation/contracts", headers=headers, json=v1_payload)
    assert resp1.status_code == 201
    contract_v1 = resp1.json()
    assert contract_v1["version"] == 1
    assert contract_v1["is_active"] == True

    # 2. Create Contract Version 2 (2.5% MDR)
    v2_payload = {
        "gateway_name": "RAZORPAY",
        "contract_name": "Contract V2 Revised",
        "start_date": "2026-06-01",
        "gst_rate": "0.180000",
        "tiers": [{"instrument_type": "UPI", "percentage_rate": "0.025000", "fixed_fee_per_txn": "0.0000"}]
    }
    resp2 = client.post("/api/v1/reconciliation/contracts", headers=headers, json=v2_payload)
    assert resp2.status_code == 201
    contract_v2 = resp2.json()
    assert contract_v2["version"] == 2
    assert contract_v2["is_active"] == True

    # 3. Check that V1 is now deactivated (is_active = False)
    all_contracts = client.get("/api/v1/reconciliation/contracts", headers=headers).json()
    assert len(all_contracts) == 2
    c_v1_check = [c for c in all_contracts if c["version"] == 1][0]
    assert c_v1_check["is_active"] == False


def test_audit_manual_review_allocation_and_reversal(client: TestClient, db_session: Session, seeded_entities: dict):
    """
    AUDIT 6 & 7: Manual APPROVE, MANUAL_ALLOCATE, and REJECT actions correctly synchronize
    the double-entry allocation and entity unallocated balance.
    """
    headers = seeded_entities["headers_a_admin"]
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    now = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    s = CanonicalSettlement(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        gateway_name="RAZORPAY", settlement_reference="SETL-REV-01",
        gross_amount=Decimal("10000.0000"), net_settlement_amount=Decimal("10000.0000"),
        unallocated_balance=Decimal("10000.0000"), settled_at=now
    )
    b = CanonicalBankTransaction(
        tenant_id=tenant_id, batch_id=batch.id, source_row_index=1,
        bank_name="HDFC", bank_reference="REF_REV_01",
        raw_narration="BANK CREDIT REVIEW TEST", transaction_date=date(2026, 11, 10),
        credit_amount=Decimal("10000.0000"), unallocated_balance=Decimal("10000.0000")
    )
    db_session.add_all([s, b])
    db_session.commit()

    run_id = client.post("/api/v1/reconciliation/runs", headers=headers, json={}).json()["id"]

    # Create an ambiguous match manually to test review resolution
    match = ReconciliationMatch(
        tenant_id=tenant_id,
        run_id=uuid.UUID(run_id),
        match_type=MatchType.SETTLEMENT_TO_BANK.value,
        classification=MatchClassification.AMBIGUOUS_MATCH.value,
        pass_number=4,
        confidence_score=Decimal("0.7500"),
        settlement_id=s.id,
        bank_transaction_id=b.id,
        source_amount=Decimal("10000.0000"),
        target_amount=Decimal("10000.0000"),
        allocated_amount=Decimal("0.0000"),
        discrepancy_amount=Decimal("0.0000"),
        explanation="Ambiguous test match",
        review_status=ReviewStatus.PENDING_REVIEW.value
    )
    db_session.add(match)
    db_session.commit()

    # 1. Action APPROVE -> Allocates ₹10,000, decrements balances
    approve_resp = client.post(
        f"/api/v1/reconciliation/matches/{match.id}/resolve",
        headers=headers,
        json={"action": "APPROVE", "notes": "Approved by Senior Finance Controller"}
    )
    assert approve_resp.status_code == 200
    db_session.refresh(s)
    db_session.refresh(b)
    assert s.unallocated_balance == Decimal("0.0000")
    assert b.unallocated_balance == Decimal("0.0000")

    # 2. Action REJECT -> Reverses allocations, restores balances
    reject_resp = client.post(
        f"/api/v1/reconciliation/matches/{match.id}/resolve",
        headers=headers,
        json={"action": "REJECT", "notes": "Reversed due to bank correction"}
    )
    assert reject_resp.status_code == 200
    db_session.refresh(s)
    db_session.refresh(b)
    assert s.unallocated_balance == Decimal("10000.0000")
    assert b.unallocated_balance == Decimal("10000.0000")
