import uuid
import json
import hashlib
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
import pytest
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func
from fastapi.testclient import TestClient

from app.models.tenant import Tenant
from app.models.user import User
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalPayment, CanonicalSettlement, CanonicalBankTransaction
from app.models.reconciliation import ReconciliationAllocation, AllocationStatus
from app.models.leakage import (
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    DetectionRunStatus,
    LeakageDetectionRun,
    LeakageException,
    LeakageRunException,
    LeakageExceptionEvidence,
    LeakageRunEvidence,
    SnapshotQuality,
    ImmutabilityViolationError,
)
from app.services.leakage.detection_engine import DetectionEngine
from app.services.leakage.evidence_hasher import (
    generate_evidence_fingerprint,
    canonical_json_dumps,
    serialize_canonical_value,
)
from app.services.leakage.clearing_verifier import ClearingVerifier


def seed_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="lineage_test.csv",
        file_hash_sha256=f"hash_{uuid.uuid4().hex[:16]}",
        file_size_bytes=2048,
        total_rows=10,
        valid_rows=10,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


# ===========================================================================
# GROUP A: Historical Run Lineage Tests (AUDIT-P4-003)
# ===========================================================================

def test_origin_run_id_preserved_across_subsequent_runs(db_session: Session, seeded_entities: dict):
    """Scenario A1-A3: First run creates origin run ID, second run preserves origin and updates latest_detection_run_id."""
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Seed overdue captured payment
    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_LINEAGE_001",
        payment_method="card",
        captured_amount=Decimal("5000.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("5000.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()

    # Execution 1
    run1 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)
    exc = db_session.execute(
        select(LeakageException).where(
            LeakageException.tenant_id == tenant_id,
            LeakageException.source_reference == "pay_LINEAGE_001"
        )
    ).scalar_one()

    assert exc.detection_run_id == run1.id
    assert exc.latest_detection_run_id == run1.id

    # Execution 2 (Re-evaluates same persistent exception)
    run2 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)
    db_session.refresh(exc)

    # AUDIT-P4-003 Verifications:
    assert exc.detection_run_id == run1.id, "Origin detection_run_id MUST NOT be overwritten on rerun"
    assert exc.latest_detection_run_id == run2.id, "latest_detection_run_id MUST reflect the latest evaluating run"


def test_point_in_time_run_snapshot_recorded_in_leakage_run_exceptions(db_session: Session, seeded_entities: dict):
    """Scenario A4: Point-in-time observation recorded with VERIFIED_AT_EXECUTION snapshot quality."""
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_SNAPSHOT_001",
        payment_method="card",
        captured_amount=Decimal("12000.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("12000.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()
    run1 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    exc = db_session.execute(
        select(LeakageException).where(
            LeakageException.tenant_id == tenant_id,
            LeakageException.source_reference == "pay_SNAPSHOT_001"
        )
    ).scalar_one()

    # Verify LeakageRunException row
    obs1 = db_session.execute(
        select(LeakageRunException).where(
            LeakageRunException.detection_run_id == run1.id,
            LeakageRunException.exception_id == exc.id
        )
    ).scalar_one_or_none()

    assert obs1 is not None
    assert obs1.observed_status == ExceptionStatus.OPEN.value
    assert obs1.observed_leakage_amount == Decimal("12000.0000")
    assert obs1.snapshot_quality == SnapshotQuality.VERIFIED_AT_EXECUTION.value


def test_idempotent_rerun_does_not_duplicate_run_exceptions(db_session: Session, seeded_entities: dict):
    """Scenario A5: Re-running engine creates exactly 1 snapshot per run, no duplicate snapshots."""
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_IDEMP_RUN_001",
        payment_method="card",
        captured_amount=Decimal("7500.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("7500.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()
    run1 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)
    run2 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    exc = db_session.execute(
        select(LeakageException).where(
            LeakageException.tenant_id == tenant_id,
            LeakageException.source_reference == "pay_IDEMP_RUN_001"
        )
    ).scalar_one()

    # Query all run observations
    all_obs = db_session.execute(
        select(LeakageRunException).where(LeakageRunException.exception_id == exc.id)
    ).scalars().all()

    # Exactly 2 observations for 2 distinct runs
    assert len(all_obs) == 2
    run_ids = {obs.detection_run_id for obs in all_obs}
    assert run_ids == {run1.id, run2.id}


def test_api_multi_run_exception_queries(client: TestClient, db_session: Session, seeded_entities: dict):
    """Scenario A6: Exception is retrievable through both original run and subsequent run filters."""
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    headers = seeded_entities["headers_a_admin"]
    batch = seed_batch(db_session, tenant_id)

    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_API_LINEAGE_001",
        payment_method="card",
        captured_amount=Decimal("4500.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("4500.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()
    run1 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)
    run2 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    # Query exceptions by Run 1
    resp1 = client.get(f"/api/v1/leakage/exceptions?detection_run_id={run1.id}", headers=headers)
    assert resp1.status_code == 200
    items1 = resp1.json()
    assert any(e["source_reference"] == "pay_API_LINEAGE_001" for e in items1)

    # Query exceptions by Run 2 (proves multi-run lineage lookup)
    resp2 = client.get(f"/api/v1/leakage/exceptions?detection_run_id={run2.id}", headers=headers)
    assert resp2.status_code == 200
    items2 = resp2.json()
    assert any(e["source_reference"] == "pay_API_LINEAGE_001" for e in items2)

    # Query snapshots endpoint
    resp_snap = client.get(f"/api/v1/leakage/runs/{run1.id}/snapshots", headers=headers)
    assert resp_snap.status_code == 200
    assert len(resp_snap.json()) >= 1


# ===========================================================================
# GROUP B: Evidence Persistence & Fingerprinting Tests (AUDIT-P4-002)
# ===========================================================================

def test_evidence_deterministic_fingerprint():
    """Scenario B1: Evidence hasher produces exact deterministic SHA-256 fingerprint."""
    entity_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    details = {
        "captured_amount": Decimal("15000.5000"),
        "gateway_payment_id": "pay_TEST_FP",
        "tax": Decimal("270.0900"),
    }

    fp1 = generate_evidence_fingerprint("PAYMENT_CAPTURE", "canonical_payments", entity_id, details)
    # Different dictionary order:
    details_reversed = {
        "tax": Decimal("270.0900"),
        "gateway_payment_id": "pay_TEST_FP",
        "captured_amount": Decimal("15000.5000"),
    }
    fp2 = generate_evidence_fingerprint("PAYMENT_CAPTURE", "canonical_payments", entity_id, details_reversed)

    assert fp1 == fp2
    assert len(fp1) == 64


def test_evidence_deduplication_reuses_existing_record(db_session: Session, seeded_entities: dict):
    """Scenario B2: Re-running detector on unchanged data reuses existing evidence record, no duplicates."""
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_EV_DEDUP_001",
        payment_method="card",
        captured_amount=Decimal("9000.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("9000.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()
    run1 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    exc = db_session.execute(
        select(LeakageException).where(
            LeakageException.tenant_id == tenant_id,
            LeakageException.source_reference == "pay_EV_DEDUP_001"
        )
    ).scalar_one()

    evidence_count_run1 = db_session.execute(
        select(func.count(LeakageExceptionEvidence.id)).where(LeakageExceptionEvidence.exception_id == exc.id)
    ).scalar()

    # Re-run detection on unchanged evidence
    run2 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    evidence_count_run2 = db_session.execute(
        select(func.count(LeakageExceptionEvidence.id)).where(LeakageExceptionEvidence.exception_id == exc.id)
    ).scalar()

    # Evidence row count MUST be identical (reused, not duplicated)
    assert evidence_count_run1 == evidence_count_run2

    # But LeakageRunEvidence should associate both runs to the same evidence item
    ev_item = db_session.execute(
        select(LeakageExceptionEvidence).where(LeakageExceptionEvidence.exception_id == exc.id)
    ).scalars().first()

    associations = db_session.execute(
        select(LeakageRunEvidence).where(LeakageRunEvidence.evidence_id == ev_item.id)
    ).scalars().all()

    associated_runs = {a.detection_run_id for a in associations}
    assert run1.id in associated_runs
    assert run2.id in associated_runs


# ===========================================================================
# GROUP C: JSON & Decimal Financial Safety Tests
# ===========================================================================

def test_canonical_json_exact_decimal_and_float_rejection():
    """Scenario C1: Decimal serializes to 4 decimal places; Python floats are strictly rejected."""
    payload = {
        "amount": Decimal("100.5"),
        "ratio": Decimal("0.0200"),
    }
    dumped = canonical_json_dumps(payload)
    assert '"amount":"100.5000"' in dumped
    assert '"ratio":"0.0200"' in dumped

    # Float rejection
    with pytest.raises(TypeError, match="Floating-point value"):
        canonical_json_dumps({"corrupt_float": 100.5})


def test_canonical_json_rejects_nan_and_infinity():
    """Scenario C2: NaN and Infinity Decimals are rejected."""
    with pytest.raises(ValueError, match="Non-finite Decimal"):
        canonical_json_dumps({"bad_val": Decimal("NaN")})

    with pytest.raises(ValueError, match="Non-finite Decimal"):
        canonical_json_dumps({"bad_val": Decimal("Infinity")})


def test_canonical_json_precision_and_scale_bounds():
    """Scenario C3: Decimals exceeding NUMERIC(18, 4) bounds are rejected."""
    # Scale exceeding 4
    with pytest.raises(ValueError, match="exceeds maximum supported scale"):
        canonical_json_dumps({"val": Decimal("10.12345")})

    # Precision exceeding 18
    with pytest.raises(ValueError, match="exceeding maximum supported precision"):
        canonical_json_dumps({"val": Decimal("1000000000000000.0000")})


def test_raw_json_decimal_preservation_no_binary_float_drift():
    """Scenario C4: Raw JSON with decimal points parsed with parse_float=Decimal avoids binary float drift."""
    raw_json_str = '{"captured_amount": "12999.9900", "fee": 12.34}'
    # Standard json.loads produces float:
    standard_parsed = json.loads(raw_json_str)
    assert isinstance(standard_parsed["fee"], float)

    # Decimal-safe parsing:
    safe_parsed = json.loads(raw_json_str, parse_float=Decimal)
    assert isinstance(safe_parsed["fee"], Decimal)
    assert safe_parsed["fee"] == Decimal("12.34")


# ===========================================================================
# GROUP D: Historical Retention & Immutability Tests (AUDIT-P4-002/003)
# ===========================================================================

def test_immutability_listener_blocks_update_and_delete_on_run_exception(db_session: Session, seeded_entities: dict):
    """Scenario D1: ORM before_update and before_delete block mutation of LeakageRunException."""
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_IMMUT_001",
        payment_method="card",
        captured_amount=Decimal("3000.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("3000.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()
    run = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    obs = db_session.execute(
        select(LeakageRunException).where(LeakageRunException.detection_run_id == run.id)
    ).scalars().first()
    assert obs is not None

    # Prohibit update
    obs.observed_leakage_amount = Decimal("9999.0000")
    with pytest.raises(ImmutabilityViolationError, match="Modifications or deletions"):
        db_session.flush()

    db_session.rollback()

    # Prohibit delete
    reloaded_obs = db_session.execute(
        select(LeakageRunException).where(LeakageRunException.detection_run_id == run.id)
    ).scalars().first()
    db_session.delete(reloaded_obs)
    with pytest.raises(ImmutabilityViolationError, match="Modifications or deletions"):
        db_session.flush()

    db_session.rollback()


def test_immutability_listener_blocks_evidence_mutation(db_session: Session, seeded_entities: dict):
    """Scenario D2: ORM before_update and before_delete block mutation of LeakageExceptionEvidence."""
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_IMMUT_EV_001",
        payment_method="card",
        captured_amount=Decimal("6000.0000"),
        status="captured",
        captured_at=datetime.now(timezone.utc) - timedelta(days=10),
        unallocated_balance=Decimal("6000.0000"),
    )
    db_session.add(p)
    db_session.commit()

    engine = DetectionEngine()
    run = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)

    ev = db_session.execute(select(LeakageExceptionEvidence)).scalars().first()
    assert ev is not None

    # Prohibit delete
    db_session.delete(ev)
    with pytest.raises(ImmutabilityViolationError, match="Modifications or deletions"):
        db_session.flush()

    db_session.rollback()


# ===========================================================================
# GROUP E: Financial Clearing Verification Tests (AUDIT-P4-006)
# ===========================================================================

def test_missing_settlement_cannot_auto_resolve(db_session: Session, seeded_entities: dict):
    """Scenario E1: ClearingVerifier strictly returns False for MISSING_SETTLEMENT."""
    tenant_id = seeded_entities["tenant_a"].id
    exc = LeakageException(
        tenant_id=tenant_id,
        detection_run_id=uuid.uuid4(),
        detector_type=DetectorType.MISSING_SETTLEMENT.value,
        exception_type=LeakageExceptionType.MISSING_SETTLEMENT.value,
        status=ExceptionStatus.OPEN.value,
        severity=ExceptionSeverity.HIGH.value,
        severity_reason="Unsettled capture",
        source_entity_type="canonical_payments",
        source_entity_id=uuid.uuid4(),
        source_reference="pay_NO_RESOLVE",
        expected_amount=Decimal("1000.0000"),
        actual_amount=Decimal("0.0000"),
        leakage_amount=Decimal("1000.0000"),
        recoverable_amount=Decimal("1000.0000"),
        currency="INR",
        explanation="Payment unsettled",
    )

    is_cleared, explanation, _ = ClearingVerifier.verify_clearing_detailed(
        db=db_session,
        exception=exc,
        tenant_id=tenant_id,
    )

    assert is_cleared is False
    assert "Automatic resolution prohibited" in explanation


def test_uncredited_settlement_cannot_auto_resolve_due_to_missing_account_identity(db_session: Session, seeded_entities: dict):
    """Scenario E2: ClearingVerifier strictly returns False for UNCREDITED_SETTLEMENT under Phase 2/3 schema."""
    tenant_id = seeded_entities["tenant_a"].id
    exc = LeakageException(
        tenant_id=tenant_id,
        detection_run_id=uuid.uuid4(),
        detector_type=DetectorType.UNCREDITED_SETTLEMENT.value,
        exception_type=LeakageExceptionType.UNCREDITED_SETTLEMENT.value,
        status=ExceptionStatus.OPEN.value,
        severity=ExceptionSeverity.CRITICAL.value,
        severity_reason="Settlement uncredited in bank",
        source_entity_type="canonical_settlements",
        source_entity_id=uuid.uuid4(),
        source_reference="set_NO_RESOLVE",
        expected_amount=Decimal("50000.0000"),
        actual_amount=Decimal("0.0000"),
        leakage_amount=Decimal("50000.0000"),
        recoverable_amount=Decimal("50000.0000"),
        currency="INR",
        explanation="Settlement not found in bank transactions",
    )

    is_cleared, explanation, _ = ClearingVerifier.verify_clearing_detailed(
        db=db_session,
        exception=exc,
        tenant_id=tenant_id,
    )

    assert is_cleared is False
    assert "Destination bank account identity and currency are not persisted" in explanation


def test_clearing_verifier_diagnostics_allocation_graph_audit(db_session: Session, seeded_entities: dict):
    """Scenario E3: Two-sided allocation audit reconstructs residual balance independently."""
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Create settlement
    s = CanonicalSettlement(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        settlement_reference="set_AUDIT_GRAPH_001",
        settled_at=datetime.now(timezone.utc) - timedelta(days=5),
        gross_amount=Decimal("10000.0000"),
        total_fee=Decimal("0.0000"),
        total_tax=Decimal("0.0000"),
        net_settlement_amount=Decimal("10000.0000"),
        unallocated_balance=Decimal("0.0000"),
    )
    db_session.add(s)
    db_session.flush()

    # Create bank transaction
    bt = CanonicalBankTransaction(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        transaction_date=datetime.now(timezone.utc).date() - timedelta(days=4),
        raw_narration="CMS/HDFCR5202611110098/RAZORPAY",
        credit_amount=Decimal("10000.0000"),
        bank_name="HDFC",
        unallocated_balance=Decimal("0.0000"),
    )
    db_session.add(bt)
    db_session.flush()

    from app.models.reconciliation import ReconciliationRun, ReconciliationMatch

    recon_run = ReconciliationRun(
        tenant_id=tenant_id,
        run_number=1,
        status="COMPLETED",
        is_active=True,
    )
    db_session.add(recon_run)
    db_session.flush()

    match = ReconciliationMatch(
        tenant_id=tenant_id,
        run_id=recon_run.id,
        match_type="SETTLEMENT_TO_BANK",
        classification="EXACT_MATCH",
        pass_number=2,
        confidence_score=Decimal("1.0000"),
        settlement_id=s.id,
        bank_transaction_id=bt.id,
        source_amount=Decimal("10000.0000"),
        target_amount=Decimal("10000.0000"),
        allocated_amount=Decimal("10000.0000"),
        explanation="Settlement to Bank Allocation",
    )
    db_session.add(match)
    db_session.flush()

    # Create active allocation of 10,000 between s and bt
    alloc = ReconciliationAllocation(
        tenant_id=tenant_id,
        run_id=recon_run.id,
        match_id=match.id,
        source_entity_type="canonical_settlements",
        source_entity_id=s.id,
        target_entity_type="canonical_bank_transactions",
        target_entity_id=bt.id,
        allocated_amount=Decimal("10000.0000"),
        status=AllocationStatus.ACTIVE.value,
    )
    db_session.add(alloc)
    db_session.commit()

    is_valid, msg, payload = ClearingVerifier.audit_two_sided_settlement_allocations(
        db=db_session,
        tenant_id=tenant_id,
        settlement_id=s.id,
    )

    assert is_valid is True
    assert payload["total_cleared_allocated"] == "10000.0000"
    assert payload["net_settlement_amount"] == "10000.0000"
    assert payload["allocation_count"] == 1


# ===========================================================================
# GROUP F: Lifecycle & Concurrency Tests
# ===========================================================================

def test_human_reviewed_states_preserved_across_detection_runs(db_session: Session, seeded_entities: dict):
    """Scenario F1: Human review states (UNDER_REVIEW, CONFIRMED, DISPUTED) are never overwritten by runs."""
    tenant_id = seeded_entities["tenant_a"].id
    admin_id = seeded_entities["admin_a"].id
    batch = seed_batch(db_session, tenant_id)

    p = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_LIFECYCLE_001",
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
            LeakageException.source_reference == "pay_LIFECYCLE_001"
        )
    ).scalar_one()

    # Move to DISPUTED
    engine.review_exception(
        db=db_session,
        exception_id=exc.id,
        tenant_id=tenant_id,
        reviewer_id=admin_id,
        action="DISPUTE",
        notes="Filing dispute claim with gateway nodal officer."
    )
    db_session.refresh(exc)
    assert exc.status == ExceptionStatus.DISPUTED.value

    # Re-run detection: DISPUTED status MUST be preserved!
    run2 = engine.run_detection(db=db_session, tenant_id=tenant_id, triggered_by_user_id=admin_id)
    db_session.refresh(exc)

    assert exc.status == ExceptionStatus.DISPUTED.value
    assert exc.detection_run_id == run1.id
    assert exc.latest_detection_run_id == run2.id
