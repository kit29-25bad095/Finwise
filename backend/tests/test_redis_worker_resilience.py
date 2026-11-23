import uuid
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.leakage import LeakageException, ExceptionStatus, ExceptionSeverity
from app.models.forensic import ForensicInvestigation, InvestigationStatus, InvestigationConclusion, InvestigationConfidence
from app.core.security import get_password_hash, create_access_token
from app.core.rbac import Role
from app.workers.queue import get_redis_client, reset_redis_client_cache, WorkerDispatcher, enqueue_job
from app.workers.forensic_tasks import process_forensic_investigation_job
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.services.forensics.llm_adapter import MockLLMAdapter
from app.services.forensics.evidence_validator import generate_evidence_fingerprint


from tests.test_phase5_1_production_hardening import _seed_test_investigation_and_exception


def _seed_test_user_and_token(db: Session, tenant_id: uuid.UUID):
    pwd_hash = get_password_hash("Pass1234!")
    user = User(email=f"admin-{uuid.uuid4().hex[:6]}@resilience.com", hashed_password=pwd_hash, full_name="Resilience Admin")
    db.add(user)
    db.flush()
    db.add(TenantMembership(tenant_id=tenant_id, user_id=user.id, role=Role.ADMIN.value))
    db.commit()
    db.refresh(user)
    token = create_access_token(subject=str(user.id), tenant_id=str(tenant_id), role=Role.ADMIN.value)
    return user, token


# ==============================================================================
# Scenario A: Redis Unavailable
# ==============================================================================
def test_scenario_a_redis_unavailable_api_graceful_rejection(client: TestClient, db_session: Session):
    """
    Scenario A: When Redis is unavailable and sync fallback is disabled (production behavior),
    attempting to enqueue an investigation fails cleanly with HTTP 503 and marks the DB record FAILED.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    user, token = _seed_test_user_and_token(db_session, tenant.id)

    # Force redis failure by raising on dispatch
    with patch("app.api.v1.forensic.enqueue_job", side_effect=RuntimeError("Redis connection refused on port 6379")):
        response = client.post(
            f"/api/v1/forensics/exceptions/{exc.id}/investigations",
            json={},
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Background worker queue is currently unavailable."

    # Verify database state is consistent: marked FAILED, not falsely left in PENDING or COMPLETED
    stmt = select(ForensicInvestigation).where(ForensicInvestigation.exception_id == exc.id)
    inv = db_session.execute(stmt).scalar_one_or_none()
    assert inv is not None
    assert inv.status == InvestigationStatus.FAILED.value
    assert "Background worker queue dispatch failure" in inv.error_message


def test_scenario_a_production_mode_strictly_rejects_silent_sync():
    """
    Scenario A: Verify that in production mode, WorkerDispatcher never silently executes jobs synchronously.
    """
    with patch("app.workers.queue.get_redis_client", return_value=None):
        with patch("app.workers.queue.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "production"
            mock_settings.WORKER_FALLBACK_SYNC = False

            with pytest.raises(RuntimeError) as exc_info:
                WorkerDispatcher.dispatch_job(lambda: "should_not_run")
            assert "synchronous fallback is strictly prohibited" in str(exc_info.value)


# ==============================================================================
# Scenario B: Normal Queue Processing
# ==============================================================================
def test_scenario_b_normal_worker_processing(db_session: Session):
    """
    Scenario B: Enqueue an investigation, execute the background worker task,
    and verify successful terminal state transitions (PENDING -> IN_PROGRESS -> COMPLETED).
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    user, _ = _seed_test_user_and_token(db_session, tenant.id)
    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        user_id=user.id
    )
    assert inv.status == InvestigationStatus.PENDING.value

    # Execute worker task using Mock adapter (zero live Gemini quota)
    with patch("app.services.forensics.investigation_service.get_llm_adapter", return_value=MockLLMAdapter()):
        result = process_forensic_investigation_job(str(inv.id))

    assert result["status"] == InvestigationStatus.COMPLETED.value
    assert result["investigation_id"] == str(inv.id)

    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.COMPLETED.value
    assert inv.conclusion in [c.value for c in InvestigationConclusion]
    assert inv.summary is not None
    assert inv.investigation_result is not None


# ==============================================================================
# Scenario C: Duplicate Delivery Protection (Idempotency)
# ==============================================================================
def test_scenario_c_duplicate_job_delivery_idempotency(db_session: Session):
    """
    Scenario C: When an investigation job is delivered multiple times (at-least-once delivery),
    subsequent executions must detect the terminal state and exit safely without re-processing.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    user, _ = _seed_test_user_and_token(db_session, tenant.id)
    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        user_id=user.id
    )

    mock_adapter = MockLLMAdapter()
    with patch("app.services.forensics.investigation_service.get_llm_adapter", return_value=mock_adapter):
        # 1st delivery
        res1 = process_forensic_investigation_job(str(inv.id))
        assert res1["status"] == InvestigationStatus.COMPLETED.value

        db_session.refresh(inv)
        original_summary = inv.summary
        original_updated_at = inv.updated_at

        # 2nd delivery (duplicate event)
        res2 = process_forensic_investigation_job(str(inv.id))
        assert res2["status"] == InvestigationStatus.COMPLETED.value

        db_session.refresh(inv)
        # Verify content was NOT regenerated or overwritten
        assert inv.summary == original_summary
        assert inv.status == InvestigationStatus.COMPLETED.value


# ==============================================================================
# Scenario D: Worker Interruption & Recovery
# ==============================================================================
def test_scenario_d_worker_interruption_leaves_in_progress_state(db_session: Session):
    """
    Scenario D: When a worker is interrupted midway through execution (e.g., process termination),
    the investigation row reflects IN_PROGRESS in the database due to atomic claim commit.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    user, _ = _seed_test_user_and_token(db_session, tenant.id)
    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        user_id=user.id
    )

    class WorkerKilledException(BaseException):
        pass

    # Simulate worker killed mid-inference
    with patch("app.services.forensics.investigation_service.ForensicPromptBuilder.build_user_prompt", side_effect=WorkerKilledException("Process killed by SIGKILL")):
        with pytest.raises(WorkerKilledException):
            ForensicInvestigationService.execute_investigation(db_session, inv.id)

    db_session.refresh(inv)
    # The atomic claim committed before the crash, so status is IN_PROGRESS
    assert inv.status == InvestigationStatus.IN_PROGRESS.value

    # Test restart behavior: In current implementation, re-executing an IN_PROGRESS investigation
    # detects another worker and skips re-execution unless force_refresh or timeout recovery is used
    inv_after_restart = ForensicInvestigationService.execute_investigation(db_session, inv.id)
    assert inv_after_restart.status == InvestigationStatus.IN_PROGRESS.value


# ==============================================================================
# Scenario E: Gemini Timeout Resilience
# ==============================================================================
def test_scenario_e_gemini_timeout_bounded_failure(db_session: Session):
    """
    Scenario E: When Gemini LLM times out across all retries, the worker safely transitions
    the investigation to FAILED status with error details, without hanging indefinitely.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    user, _ = _seed_test_user_and_token(db_session, tenant.id)
    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        user_id=user.id
    )

    timing_out_adapter = MockLLMAdapter(simulate_timeout=True)
    with patch("app.services.forensics.investigation_service.get_llm_adapter", return_value=timing_out_adapter):
        result = process_forensic_investigation_job(str(inv.id))

    assert result["status"] == InvestigationStatus.FAILED.value
    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.FAILED.value
    assert inv.conclusion == InvestigationConclusion.INCONCLUSIVE.value
    assert inv.confidence == InvestigationConfidence.LOW.value
    assert "AI Provider failure" in inv.error_message


# ==============================================================================
# Scenario F: Database Failure During Persistence
# ==============================================================================
def test_scenario_f_database_failure_rollback(db_session: Session):
    """
    Scenario F: When a database error occurs during investigation persistence,
    the transaction is rolled back and partial inconsistent records are not committed.
    """
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db_session)
    user, _ = _seed_test_user_and_token(db_session, tenant.id)
    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
        user_id=user.id
    )

    # Simulate database operational failure on final commit
    original_commit = db_session.commit
    commit_count = 0

    def mock_commit():
        nonlocal commit_count
        commit_count += 1
        # Allow the first atomic claim commit (PENDING -> IN_PROGRESS), but fail on the final result commit
        if commit_count > 1:
            raise OperationalError("Simulated DB connection drop during commit", params={}, orig=Exception("DB down"))
        original_commit()

    with patch.object(db_session, "commit", side_effect=mock_commit):
        with pytest.raises(OperationalError):
            ForensicInvestigationService.execute_investigation(db_session, inv.id, adapter=MockLLMAdapter())

    # Verify session rollback
    db_session.rollback()
    db_session.refresh(inv)
    # The investigation must not contain completed summary results
    assert inv.status != InvestigationStatus.COMPLETED.value


# ==============================================================================
# Scenario G: Redis Recovery and Reconnection
# ==============================================================================
def test_scenario_g_redis_recovery_reconnection():
    """
    Scenario G: Verify that if Redis is initially down and subsequently recovers,
    the application cache can reconnect and enqueue new jobs without restarting the app.
    """
    reset_redis_client_cache()

    # 1. Simulate Redis down initially
    with patch("redis.from_url", side_effect=Exception("Connection refused")):
        client1 = get_redis_client(force_reconnect=True)
        assert client1 is None

    # 2. Simulate Redis restored
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    with patch("redis.from_url", return_value=mock_redis):
        # Force reconnection check or cache reset
        reset_redis_client_cache()
        client2 = get_redis_client(force_reconnect=True)
        assert client2 is not None
        assert client2.ping() is True

    reset_redis_client_cache()
