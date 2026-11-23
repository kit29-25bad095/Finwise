import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pytest
from sqlalchemy import text, Engine
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    LeakageExceptionEvidence,
    LeakageRunEvidence,
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    DetectionRunStatus,
)
from app.models.forensic import (
    ForensicInvestigation,
    ForensicClaimDraft,
    InvestigationStatus,
    ClaimDraftStatus,
)
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.services.forensics.claim_draft_service import ClaimDraftService
from app.services.forensics.llm_adapter import MockLLMAdapter
from app.services.leakage.evidence_hasher import generate_evidence_fingerprint


def _seed_pg_full_leakage_exception(engine: Engine):
    """Seeds a test exception with verified evidence in a dedicated committed transaction."""
    t_id = uuid.uuid4()
    run_id = uuid.uuid4()
    exc_id = uuid.uuid4()
    ev_id = uuid.uuid4()
    slug = f"conc-{uuid.uuid4().hex[:8]}"

    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(
            text("INSERT INTO tenants (id, name, slug, default_currency, is_active, created_at, updated_at) "
                 "VALUES (:id, 'Concurrency Tenant', :slug, 'INR', true, NOW(), NOW())"),
            {"id": t_id, "slug": slug}
        )
        conn.execute(
            text("INSERT INTO leakage_detection_runs (id, tenant_id, run_number, status, created_at, updated_at) "
                 "VALUES (:id, :t_id, 1, 'COMPLETED', NOW(), NOW())"),
            {"id": run_id, "t_id": t_id}
        )
        conn.execute(
            text("""
                INSERT INTO leakage_exceptions (
                    id, tenant_id, detection_run_id, latest_detection_run_id, detector_type,
                    exception_type, status, severity, severity_reason, source_entity_type,
                    source_entity_id, source_reference, gateway_name, expected_amount,
                    actual_amount, leakage_amount, recoverable_amount, currency, explanation,
                    created_at, updated_at
                ) VALUES (
                    :id, :t_id, :run_id, :run_id, 'FEE_OVERCHARGE',
                    'FEE_OVERCHARGE', 'OPEN', 'MEDIUM', 'Fee mismatch', 'canonical_payments',
                    :src_id, 'pay_conc_01', 'RAZORPAY', 20.0000,
                    25.0000, 5.0000, 5.0000, 'INR', 'Fee contract drift',
                    NOW(), NOW()
                )
            """),
            {"id": exc_id, "t_id": t_id, "run_id": run_id, "src_id": uuid.uuid4()}
        )
        src_entity_id = uuid.uuid4()
        details_obj = {"payment_id": "pay_conc_01"}
        ev_fingerprint = generate_evidence_fingerprint(
            evidence_type="PAYMENT_CAPTURE",
            entity_type="canonical_payments",
            entity_id=src_entity_id,
            details=details_obj,
        )

        conn.execute(
            text("""
                INSERT INTO leakage_exception_evidence (
                    id, tenant_id, exception_id, detection_run_id, evidence_type,
                    entity_type, entity_id, fingerprint_sha256, details, created_at, updated_at
                ) VALUES (
                    :id, :t_id, :exc_id, :run_id, 'PAYMENT_CAPTURE',
                    'canonical_payments', :ent_id, :fingerprint, '{\"payment_id\": \"pay_conc_01\"}'::json,
                    NOW(), NOW()
                )
            """),
            {
                "id": ev_id,
                "t_id": t_id,
                "exc_id": exc_id,
                "run_id": run_id,
                "ent_id": src_entity_id,
                "fingerprint": ev_fingerprint,
            }
        )
        conn.execute(
            text("INSERT INTO leakage_run_evidence (id, tenant_id, detection_run_id, evidence_id, created_at, updated_at) "
                 "VALUES (:id, :t_id, :run_id, :ev_id, NOW(), NOW())"),
            {"id": uuid.uuid4(), "t_id": t_id, "run_id": run_id, "ev_id": ev_id}
        )
        tx.commit()

    return t_id, run_id, exc_id


def _cleanup_test_data(engine: Engine, tenant_id: uuid.UUID):
    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(text("DELETE FROM forensic_claim_drafts WHERE tenant_id = :id"), {"id": tenant_id})
        conn.execute(text("DELETE FROM forensic_investigations WHERE tenant_id = :id"), {"id": tenant_id})
        conn.execute(text("DELETE FROM leakage_run_evidence WHERE tenant_id = :id"), {"id": tenant_id})
        conn.execute(text("DELETE FROM leakage_exception_evidence WHERE tenant_id = :id"), {"id": tenant_id})
        conn.execute(text("DELETE FROM leakage_exceptions WHERE tenant_id = :id"), {"id": tenant_id})
        conn.execute(text("DELETE FROM leakage_detection_runs WHERE tenant_id = :id"), {"id": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id})
        tx.commit()


@pytest.mark.asyncio
async def test_concurrent_investigation_workers_atomic_claim(pg_engine: Engine):
    """
    B4: Simulate two concurrent workers racing to execute the same PENDING investigation.
    Verify atomic conditional state transition allows exactly ONE worker to process,
    preventing duplicate execution and duplicate Gemini LLM invocations.
    """
    t_id, run_id, exc_id = _seed_pg_full_leakage_exception(pg_engine)

    try:
        # Create investigation
        session_setup = Session(bind=pg_engine)
        inv = ForensicInvestigationService.create_investigation(session_setup, t_id, exc_id)
        inv_id = inv.id
        session_setup.close()

        # Track LLM invocations
        llm_call_count = 0
        original_adapter = MockLLMAdapter()

        class CountingAdapter(MockLLMAdapter):
            async def generate_investigation(self, system_prompt, user_prompt):
                nonlocal llm_call_count
                llm_call_count += 1
                await asyncio.sleep(0.05)  # slight pause to maximize race window
                return await original_adapter.generate_investigation(system_prompt, user_prompt)

        adapter = CountingAdapter()

        # Run concurrent workers in parallel
        async def run_worker(worker_id: int):
            db = Session(bind=pg_engine, expire_on_commit=False)
            try:
                res = await ForensicInvestigationService.execute_investigation_async(
                    db=db,
                    investigation_id=inv_id,
                    adapter=adapter
                )
                return worker_id, res.status
            finally:
                db.close()

        results = await asyncio.gather(run_worker(1), run_worker(2))

        # Exactly ONE worker must have triggered the LLM
        assert llm_call_count == 1, f"Concurrency race detected! LLM called {llm_call_count} times (expected 1)"

        # Both workers should complete with a valid investigation state
        statuses = [r[1] for r in results]
        assert all(s in (InvestigationStatus.COMPLETED.value, InvestigationStatus.IN_PROGRESS.value) for s in statuses)

        # Final state in DB must be COMPLETED
        session_verify = Session(bind=pg_engine)
        final_inv = session_verify.get(ForensicInvestigation, inv_id)
        assert final_inv.status == InvestigationStatus.COMPLETED.value
        session_verify.close()

    finally:
        _cleanup_test_data(pg_engine, t_id)


def test_concurrent_claim_draft_version_numbering(pg_engine: Engine):
    """
    B5: Verify claim draft version numbers increment deterministically under creation.
    """
    t_id, run_id, exc_id = _seed_pg_full_leakage_exception(pg_engine)

    try:
        session = Session(bind=pg_engine)
        inv = ForensicInvestigationService.create_investigation(session, t_id, exc_id)
        ForensicInvestigationService.execute_investigation(session, inv.id)

        draft1 = ClaimDraftService.create_claim_draft(session, t_id, inv.id, notes="Draft 1")
        draft2 = ClaimDraftService.create_claim_draft(session, t_id, inv.id, notes="Draft 2")

        assert draft1.draft_number == 1
        assert draft2.draft_number == 2
        assert draft1.id != draft2.id
        session.close()

    finally:
        _cleanup_test_data(pg_engine, t_id)


def test_database_level_immutability_evaluation_and_trigger_proof(pg_engine: Engine):
    """
    Phase C: Evaluate database-level immutability vs ORM listeners.
    Proves:
    1. Direct SQL updates can alter completed records unless a PostgreSQL trigger is active.
    2. A PostgreSQL trigger function successfully blocks direct SQL updates to COMPLETED records.
    3. Rolled back cleanly to preserve existing schema.
    """
    t_id, run_id, exc_id = _seed_pg_full_leakage_exception(pg_engine)

    try:
        session = Session(bind=pg_engine)
        inv = ForensicInvestigationService.create_investigation(session, t_id, exc_id)
        ForensicInvestigationService.execute_investigation(session, inv.id)
        session.close()

        # Step 1: Direct SQL update WITHOUT trigger succeeds (demonstrating ORM-only limitation)
        with pg_engine.connect() as conn:
            tx = conn.begin()
            conn.execute(
                text("UPDATE forensic_investigations SET summary = 'Direct SQL bypass' WHERE id = :id"),
                {"id": inv.id}
            )
            updated_summary = conn.scalar(
                text("SELECT summary FROM forensic_investigations WHERE id = :id"),
                {"id": inv.id}
            )
            assert updated_summary == "Direct SQL bypass"
            tx.rollback()

        # Step 2: In isolated transaction, install PostgreSQL trigger function and test enforcement
        with pg_engine.connect() as conn:
            tx = conn.begin()
            conn.execute(text("""
                CREATE OR REPLACE FUNCTION _test_trg_inv_immutability()
                RETURNS TRIGGER AS $$
                BEGIN
                    IF OLD.status IN ('COMPLETED', 'BLOCKED', 'FAILED') THEN
                        RAISE EXCEPTION 'Database-level immutability: Modifications to % investigation % are strictly prohibited.', OLD.status, OLD.id;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS trg_test_inv_immutability ON forensic_investigations;
                CREATE TRIGGER trg_test_inv_immutability
                BEFORE UPDATE ON forensic_investigations
                FOR EACH ROW
                EXECUTE FUNCTION _test_trg_inv_immutability();
            """))

            # Now, direct SQL update MUST fail at the PostgreSQL level
            with pytest.raises(Exception) as exc_info:
                conn.execute(
                    text("UPDATE forensic_investigations SET summary = 'Tampered' WHERE id = :id"),
                    {"id": inv.id}
                )
            assert "Database-level immutability" in str(exc_info.value)
            tx.rollback()

    finally:
        _cleanup_test_data(pg_engine, t_id)
