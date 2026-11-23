import uuid
import datetime
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import List, Set

import pytest
from sqlalchemy import text, select, Engine
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    DetectionRunStatus,
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
)
from app.models.forensic import (
    ForensicInvestigation,
    ForensicClaimDraft,
    ForensicDispatchOutbox,
    InvestigationStatus,
    InvestigationConclusion,
    InvestigationConfidence,
    OutboxDispatchStatus,
    OutboxEventType,
)
from app.services.forensics.lease_manager import InvestigationLeaseManager
from app.services.forensics.outbox_service import TransactionalOutboxService
from app.services.forensics.orphan_reaper import OrphanInvestigationReaper
from app.services.forensics.exceptions import StaleLeaseError


def _cleanup_tenant(engine: Engine, tenant_id: uuid.UUID):
    """Safely cleans up all test records created under a specific test tenant."""
    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(
            text("DELETE FROM forensic_claim_drafts WHERE tenant_id = :t_id"),
            {"t_id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM forensic_dispatch_outbox WHERE tenant_id = :t_id"),
            {"t_id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM forensic_investigations WHERE tenant_id = :t_id"),
            {"t_id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM leakage_exceptions WHERE tenant_id = :t_id"),
            {"t_id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM leakage_detection_runs WHERE tenant_id = :t_id"),
            {"t_id": tenant_id},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE id = :t_id"),
            {"t_id": tenant_id},
        )
        tx.commit()


def _seed_test_hierarchy(engine: Engine):
    """Creates a fresh tenant, detection run, and leakage exception in finora_test."""
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    exception_id = uuid.uuid4()

    with Session(bind=engine) as session:
        tenant = Tenant(
            id=tenant_id,
            name="PG Lease Test Tenant",
            slug=f"pg-lease-{uuid.uuid4().hex[:8]}",
            default_currency="INR",
        )
        session.add(tenant)
        session.flush()

        run = LeakageDetectionRun(
            id=run_id,
            tenant_id=tenant_id,
            run_number=1,
            status=DetectionRunStatus.COMPLETED.value,
        )
        session.add(run)
        session.flush()

        exc = LeakageException(
            id=exception_id,
            tenant_id=tenant_id,
            detection_run_id=run_id,
            latest_detection_run_id=run_id,
            detector_type=DetectorType.FEE_OVERCHARGE.value,
            exception_type=LeakageExceptionType.FEE_OVERCHARGE.value,
            status=ExceptionStatus.OPEN.value,
            severity=ExceptionSeverity.MEDIUM.value,
            severity_reason="Integration test fee discrepancy",
            source_entity_type="canonical_payments",
            source_entity_id=uuid.uuid4(),
            source_reference=f"PAY-{uuid.uuid4().hex[:6]}",
            gateway_name="RAZORPAY",
            expected_amount=Decimal("20.0000"),
            actual_amount=Decimal("25.0000"),
            leakage_amount=Decimal("5.0000"),
            recoverable_amount=Decimal("5.0000"),
            currency="INR",
            explanation="Integration test explanation",
        )
        session.add(exc)
        session.flush()
        session.commit()

    return tenant_id, run_id, exception_id


def test_concurrent_worker_race_on_initial_claim(pg_engine: Engine):
    """
    Integration: 5 concurrent workers race to claim the same PENDING investigation.
    PostgreSQL 17 row locking ensures exactly 1 worker wins; 4 workers receive None.
    """
    tenant_id, run_id, exc_id = _seed_test_hierarchy(pg_engine)
    inv_id = uuid.uuid4()

    try:
        with Session(bind=pg_engine) as session:
            inv = ForensicInvestigation(
                id=inv_id,
                tenant_id=tenant_id,
                exception_id=exc_id,
                detection_run_id=run_id,
                status=InvestigationStatus.PENDING.value,
                attempt_count=0,
                evidence_bundle_fingerprint="a" * 64,
                evidence_bundle_snapshot={"facts": []},
            )
            session.add(inv)
            session.commit()

        # 5 workers race concurrently
        def _worker_claim(worker_idx: int):
            with Session(bind=pg_engine) as s:
                return InvestigationLeaseManager.claim_pending_investigation(
                    db=s,
                    investigation_id=inv_id,
                    worker_id=f"worker-{worker_idx}",
                    lease_duration_seconds=30,
                )

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_worker_claim, i) for i in range(5)]
            tokens = [f.result() for f in futures]

        successful_tokens = [t for t in tokens if t is not None]
        rejected_tokens = [t for t in tokens if t is None]

        assert len(successful_tokens) == 1, f"Expected exactly 1 winner, got: {successful_tokens}"
        assert len(rejected_tokens) == 4

        with Session(bind=pg_engine) as session:
            persisted_inv = session.get(ForensicInvestigation, inv_id)
            assert persisted_inv.status == InvestigationStatus.IN_PROGRESS.value
            assert persisted_inv.attempt_count == 1
            assert persisted_inv.lease_token == successful_tokens[0]

    finally:
        _cleanup_tenant(pg_engine, tenant_id)


def test_concurrent_worker_race_on_expired_reclaim(pg_engine: Engine):
    """
    Integration: 5 concurrent workers race to reclaim an expired IN_PROGRESS investigation.
    PostgreSQL 17 ensures exactly 1 worker claims the new lease; 4 workers receive None.
    """
    tenant_id, run_id, exc_id = _seed_test_hierarchy(pg_engine)
    inv_id = uuid.uuid4()

    try:
        with Session(bind=pg_engine) as session:
            inv = ForensicInvestigation(
                id=inv_id,
                tenant_id=tenant_id,
                exception_id=exc_id,
                detection_run_id=run_id,
                status=InvestigationStatus.IN_PROGRESS.value,
                attempt_count=1,
                lease_token=uuid.uuid4(),
                lease_owner_id="old-crashed-worker",
                lease_expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10),
                evidence_bundle_fingerprint="b" * 64,
                evidence_bundle_snapshot={"facts": []},
            )
            session.add(inv)
            session.commit()

        # 5 workers race to reclaim expired lease
        def _worker_reclaim(worker_idx: int):
            with Session(bind=pg_engine) as s:
                return InvestigationLeaseManager.reclaim_expired_investigation(
                    db=s,
                    investigation_id=inv_id,
                    worker_id=f"reclaiming-worker-{worker_idx}",
                    lease_duration_seconds=30,
                )

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_worker_reclaim, i) for i in range(5)]
            tokens = [f.result() for f in futures]

        successful_tokens = [t for t in tokens if t is not None]
        rejected_tokens = [t for t in tokens if t is None]

        assert len(successful_tokens) == 1, f"Expected exactly 1 winner, got: {successful_tokens}"
        assert len(rejected_tokens) == 4

        with Session(bind=pg_engine) as session:
            persisted_inv = session.get(ForensicInvestigation, inv_id)
            assert persisted_inv.status == InvestigationStatus.IN_PROGRESS.value
            assert persisted_inv.attempt_count == 2
            assert persisted_inv.lease_token == successful_tokens[0]

    finally:
        _cleanup_tenant(pg_engine, tenant_id)


def test_concurrent_reapers_with_skip_locked(pg_engine: Engine):
    """
    Integration: 3 concurrent reapers process 10 expired investigations using SKIP LOCKED.
    Every investigation must be processed once with zero duplicate processing and zero deadlocks.
    """
    tenant_id, run_id, exc_id = _seed_test_hierarchy(pg_engine)
    inv_ids: List[uuid.UUID] = []

    try:
        with Session(bind=pg_engine) as session:
            for i in range(10):
                inv = ForensicInvestigation(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    exception_id=exc_id,
                    detection_run_id=run_id,
                    status=InvestigationStatus.IN_PROGRESS.value,
                    attempt_count=1,
                    lease_token=uuid.uuid4(),
                    lease_owner_id=f"crashed-worker-{i}",
                    lease_expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10),
                    evidence_bundle_fingerprint=uuid.uuid4().hex * 2,
                    evidence_bundle_snapshot={"facts": []},
                )
                session.add(inv)
                inv_ids.append(inv.id)
            session.commit()

        # 3 reapers run concurrently
        def _reaper_task(reaper_idx: int):
            with Session(bind=pg_engine) as s:
                res = OrphanInvestigationReaper.reap_orphaned_investigations(
                    db=s,
                    limit=10,
                )
                return res["scanned"]

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(_reaper_task, i) for i in range(3)]
            counts = [f.result() for f in futures]

        total_reaped = sum(counts)
        assert total_reaped == 10, f"Expected exactly 10 reaped investigations, got {total_reaped} (counts: {counts})"

        with Session(bind=pg_engine) as session:
            outbox_events = session.execute(
                select(ForensicDispatchOutbox).where(ForensicDispatchOutbox.tenant_id == tenant_id)
            ).scalars().all()
            assert len(outbox_events) == 10

    finally:
        _cleanup_tenant(pg_engine, tenant_id)


def test_concurrent_outbox_publishers_with_skip_locked(pg_engine: Engine):
    """
    Integration: 3 concurrent publishers claim 10 pending outbox events using SKIP LOCKED.
    All 10 events must be claimed across the threads with disjoint event ID sets.
    """
    tenant_id, run_id, exc_id = _seed_test_hierarchy(pg_engine)
    event_ids: List[uuid.UUID] = []

    try:
        with Session(bind=pg_engine) as session:
            for i in range(10):
                inv = ForensicInvestigation(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    exception_id=exc_id,
                    detection_run_id=run_id,
                    status=InvestigationStatus.PENDING.value,
                    attempt_count=0,
                    evidence_bundle_fingerprint=uuid.uuid4().hex * 2,
                    evidence_bundle_snapshot={"facts": []},
                )
                session.add(inv)
                session.flush()

                evt = TransactionalOutboxService.create_initial_dispatch_intent(
                    db=session,
                    tenant_id=tenant_id,
                    investigation_id=inv.id,
                )
                session.flush()
                event_ids.append(evt.id)
            session.commit()

        # 3 publishers claim concurrently
        def _publisher_claim(pub_idx: int) -> List[uuid.UUID]:
            with Session(bind=pg_engine) as s:
                events = TransactionalOutboxService.claim_pending_outbox_events(
                    db=s,
                    limit=10,
                    publisher_id=f"pub-{pub_idx}",
                )
                return [e.id for e in events]

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(_publisher_claim, i) for i in range(3)]
            results = [f.result() for f in futures]

        total_claimed = sum(len(r) for r in results)
        assert total_claimed == 10, f"Expected 10 total claimed events, got: {total_claimed}"

        # Verify disjoint sets (no overlap)
        claimed_sets = [set(r) for r in results]
        all_claimed: Set[uuid.UUID] = set()
        for s in claimed_sets:
            assert len(all_claimed.intersection(s)) == 0, "Race condition: double claim detected!"
            all_claimed.update(s)

        assert all_claimed == set(event_ids)

    finally:
        _cleanup_tenant(pg_engine, tenant_id)


def test_stale_worker_write_rejection_and_rollback_in_postgres(pg_engine: Engine):
    """
    Integration: Verifies that a stale worker with an outdated lease_token cannot persist
    findings or claim drafts into PostgreSQL 17, and transaction rollback leaves 0 records.
    """
    tenant_id, run_id, exc_id = _seed_test_hierarchy(pg_engine)
    inv_id = uuid.uuid4()

    try:
        # Worker 1 acquires lease
        with Session(bind=pg_engine) as session:
            inv = ForensicInvestigation(
                id=inv_id,
                tenant_id=tenant_id,
                exception_id=exc_id,
                detection_run_id=run_id,
                status=InvestigationStatus.PENDING.value,
                attempt_count=0,
                evidence_bundle_fingerprint="c" * 64,
                evidence_bundle_snapshot={"facts": []},
            )
            session.add(inv)
            session.commit()

        with Session(bind=pg_engine) as session:
            token_1 = InvestigationLeaseManager.claim_pending_investigation(
                db=session,
                investigation_id=inv_id,
                worker_id="worker-1",
            )
            assert token_1 is not None

        # Lease expires and Worker 2 reclaims it
        with Session(bind=pg_engine) as session:
            persisted = session.get(ForensicInvestigation, inv_id)
            persisted.lease_expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=5)
            session.commit()

        with Session(bind=pg_engine) as session:
            token_2 = InvestigationLeaseManager.reclaim_expired_investigation(
                db=session,
                investigation_id=inv_id,
                worker_id="worker-2",
            )
            assert token_2 is not None
            assert token_2 != token_1

        # Now Worker 1 wakes up and attempts to persist using stale token_1
        draft_payload = {
            "tenant_id": tenant_id,
            "exception_id": exc_id,
            "detection_run_id": run_id,
            "dispute_amount": Decimal("2500.00"),
            "target_entity": "RAZORPAY",
            "target_reference": "ref-123",
            "claim_summary": "Stale draft summary",
            "supporting_facts": ["fact1"],
            "evidence_references": ["ev1"],
        }

        with Session(bind=pg_engine) as session:
            with pytest.raises(StaleLeaseError) as exc_info:
                InvestigationLeaseManager.validate_and_persist_completed_investigation(
                    db=session,
                    investigation_id=inv_id,
                    worker_lease_token=token_1,  # Stale token
                    conclusion=InvestigationConclusion.SUPPORTED,
                    confidence=InvestigationConfidence.HIGH,
                    summary="Stale summary",
                    investigation_result={"facts": ["stale_data"]},
                    model_provider="mock",
                    model_name="mock-model",
                    claim_draft_data=draft_payload,
                )

            assert "Fencing validation failed" in str(exc_info.value)

        # Confirm 0 drafts persisted in PostgreSQL 17
        with Session(bind=pg_engine) as session:
            drafts_count = session.scalar(
                text("SELECT count(*) FROM forensic_claim_drafts WHERE investigation_id = :id"),
                {"id": inv_id},
            )
            assert drafts_count == 0, f"Expected 0 drafts, got: {drafts_count}"

            # Verify investigation state remains IN_PROGRESS under Worker 2
            current_inv = session.get(ForensicInvestigation, inv_id)
            assert current_inv.status == InvestigationStatus.IN_PROGRESS.value
            assert current_inv.lease_token == token_2

    finally:
        _cleanup_tenant(pg_engine, tenant_id)


def test_reaper_transitions_exhausted_investigations_in_postgres(pg_engine: Engine):
    """
    Integration: Verifies that when an orphaned investigation has reached maximum attempts (3),
    the reaper in PostgreSQL 17 transitions it to FAILED and creates no outbox dispatch event.
    """
    tenant_id, run_id, exc_id = _seed_test_hierarchy(pg_engine)
    inv_id = uuid.uuid4()

    try:
        with Session(bind=pg_engine) as session:
            inv = ForensicInvestigation(
                id=inv_id,
                tenant_id=tenant_id,
                exception_id=exc_id,
                detection_run_id=run_id,
                status=InvestigationStatus.IN_PROGRESS.value,
                attempt_count=3,  # Max attempts reached
                lease_token=uuid.uuid4(),
                lease_owner_id="crashed-worker-3",
                lease_expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10),
                evidence_bundle_fingerprint="d" * 64,
                evidence_bundle_snapshot={"facts": []},
            )
            session.add(inv)
            session.commit()

        with Session(bind=pg_engine) as session:
            res = OrphanInvestigationReaper.reap_orphaned_investigations(
                db=session,
                limit=10,
            )
            assert res["scanned"] == 1
            assert res["exhausted_failed"] == 1

        with Session(bind=pg_engine) as session:
            persisted = session.get(ForensicInvestigation, inv_id)
            assert persisted.status == InvestigationStatus.FAILED.value
            assert persisted.conclusion == InvestigationConclusion.INCONCLUSIVE.value
            assert persisted.confidence == InvestigationConfidence.LOW.value
            assert "exhausted" in persisted.error_message

            # Verify no outbox event was generated
            outbox_count = session.scalar(
                text("SELECT count(*) FROM forensic_dispatch_outbox WHERE investigation_id = :id"),
                {"id": inv_id},
            )
            assert outbox_count == 0

    finally:
        _cleanup_tenant(pg_engine, tenant_id)
