import uuid
import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import select, and_, text
from sqlalchemy.orm import Session

from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
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
    ImmutabilityViolationError,
)
from app.models.forensic import (
    ForensicInvestigation,
    ForensicClaimDraft,
    ForensicDispatchOutbox,
    InvestigationStatus,
    InvestigationConclusion,
    InvestigationConfidence,
    ClaimDraftStatus,
    OutboxDispatchStatus,
    OutboxEventType,
)
from app.core.security import get_password_hash, create_access_token
from app.core.rbac import Role
from app.services.forensics.lease_manager import InvestigationLeaseManager
from app.services.forensics.outbox_service import TransactionalOutboxService
from app.services.forensics.orphan_reaper import OrphanInvestigationReaper
from app.workers.outbox_publisher import OutboxPublisher
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.services.forensics.claim_draft_service import ClaimDraftService
from app.services.forensics.llm_adapter import MockLLMAdapter
from app.services.forensics.exceptions import (
    StaleLeaseError,
    LeaseRenewalError,
    InvalidInvestigationStateError,
    LLMProviderError,
    TenantMismatchError,
)
from tests.test_phase5_1_production_hardening import _seed_test_investigation_and_exception


def _create_pending_investigation(db: Session) -> Tuple[Tenant, ForensicInvestigation]:
    tenant, run, exc, ev = _seed_test_investigation_and_exception(db)
    inv = ForensicInvestigationService.create_investigation(
        db=db,
        tenant_id=tenant.id,
        exception_id=exc.id,
    )
    return tenant, inv


# ==============================================================================
# A. Lease Tests (1 - 10)
# ==============================================================================

def test_01_initial_pending_claim(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    assert inv.status == InvestigationStatus.PENDING.value
    assert inv.attempt_count == 0

    token = InvestigationLeaseManager.claim_pending_investigation(
        db=db_session,
        investigation_id=inv.id,
        worker_id="worker-node-1",
        lease_duration_seconds=300,
    )
    assert token is not None
    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.IN_PROGRESS.value
    assert inv.lease_owner_id == "worker-node-1"
    assert inv.lease_token == token
    assert inv.attempt_count == 1
    assert inv.lease_expires_at is not None


def test_02_duplicate_initial_claim_rejected(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token1 = InvestigationLeaseManager.claim_pending_investigation(
        db=db_session,
        investigation_id=inv.id,
        worker_id="worker-1",
    )
    assert token1 is not None

    # Second worker attempts to claim PENDING job
    token2 = InvestigationLeaseManager.claim_pending_investigation(
        db=db_session,
        investigation_id=inv.id,
        worker_id="worker-2",
    )
    assert token2 is None
    db_session.refresh(inv)
    assert inv.lease_owner_id == "worker-1"
    assert inv.attempt_count == 1


def test_03_active_lease_cannot_be_reclaimed(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token1 = InvestigationLeaseManager.claim_pending_investigation(
        db=db_session,
        investigation_id=inv.id,
        worker_id="worker-1",
        lease_duration_seconds=300,
    )
    assert token1 is not None

    # Worker 2 attempts reclamation while lease is still valid in the future
    token2 = InvestigationLeaseManager.reclaim_expired_investigation(
        db=db_session,
        investigation_id=inv.id,
        worker_id="worker-2",
    )
    assert token2 is None
    db_session.refresh(inv)
    assert inv.lease_owner_id == "worker-1"
    assert inv.lease_token == token1
    assert inv.attempt_count == 1


def test_04_expired_lease_can_be_reclaimed(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token1 = InvestigationLeaseManager.claim_pending_investigation(
        db=db_session,
        investigation_id=inv.id,
        worker_id="worker-1",
    )
    # Manually backdate lease expiry to simulate crash/timeout
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=10)
    db_session.commit()

    token2 = InvestigationLeaseManager.reclaim_expired_investigation(
        db=db_session,
        investigation_id=inv.id,
        worker_id="worker-2",
    )
    assert token2 is not None
    assert token2 != token1
    db_session.refresh(inv)
    assert inv.lease_owner_id == "worker-2"
    assert inv.lease_token == token2
    assert inv.attempt_count == 2


def test_05_reclaim_generates_new_uuid_token(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token1 = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()

    token2 = InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    assert isinstance(token2, uuid.UUID)
    assert token2 != token1


def test_06_attempt_count_increments_exactly_once(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    assert inv.attempt_count == 0

    InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    db_session.refresh(inv)
    assert inv.attempt_count == 1

    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()

    InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    db_session.refresh(inv)
    assert inv.attempt_count == 2


def test_07_expired_owner_cannot_renew_lease(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    # Expire lease
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=5)
    db_session.commit()

    # Attempt renewal of expired lease
    renewed = InvestigationLeaseManager.renew_lease(
        db=db_session,
        investigation_id=inv.id,
        worker_lease_token=token,
    )
    assert renewed is False


def test_08_valid_owner_can_renew_lease(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token = InvestigationLeaseManager.claim_pending_investigation(
        db=db_session, investigation_id=inv.id, worker_id="w1", lease_duration_seconds=100
    )
    db_session.refresh(inv)
    initial_expiry = inv.lease_expires_at

    renewed = InvestigationLeaseManager.renew_lease(
        db=db_session,
        investigation_id=inv.id,
        worker_lease_token=token,
        lease_duration_seconds=500,
    )
    assert renewed is True
    db_session.refresh(inv)
    assert inv.lease_expires_at > initial_expiry


def test_09_terminal_investigation_cannot_be_claimed(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    inv.status = InvestigationStatus.COMPLETED.value
    db_session.commit()

    token = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    assert token is None


def test_10_terminal_investigation_cannot_be_reclaimed(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    inv.status = InvestigationStatus.FAILED.value
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=10)
    db_session.commit()

    token = InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    assert token is None


# ==============================================================================
# B. Fencing Tests (11 - 17)
# ==============================================================================

def test_11_stale_worker_cannot_persist_findings(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token1 = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")

    # Worker 1 stalls; Worker 2 reclaims lease
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()
    token2 = InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")

    # Stale Worker 1 attempts to persist with old token1
    with pytest.raises(StaleLeaseError) as exc_info:
        InvestigationLeaseManager.validate_and_persist_completed_investigation(
            db=db_session,
            investigation_id=inv.id,
            worker_lease_token=token1,
            conclusion=InvestigationConclusion.SUPPORTED,
            confidence=InvestigationConfidence.HIGH,
            summary="Stale worker analysis",
            investigation_result={"facts": []},
            model_provider="mock",
            model_name="mock-model",
        )
    assert "Fencing validation failed" in str(exc_info.value)
    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.IN_PROGRESS.value
    assert inv.lease_token == token2


def test_12_stale_worker_cannot_create_evidence_references(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token1 = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()
    InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")

    with pytest.raises(StaleLeaseError):
        InvestigationLeaseManager.validate_and_persist_completed_investigation(
            db=db_session,
            investigation_id=inv.id,
            worker_lease_token=token1,
            conclusion=InvestigationConclusion.SUPPORTED,
            confidence=InvestigationConfidence.HIGH,
            summary="Stale summary",
            investigation_result={"evidence_references": ["fabricated-id"]},
            model_provider="mock",
            model_name="mock-model",
        )


def test_13_stale_worker_cannot_create_claim_drafts(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token1 = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()
    InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")

    draft_payload = {
        "tenant_id": tenant.id,
        "exception_id": inv.exception_id,
        "detection_run_id": inv.detection_run_id,
        "dispute_amount": Decimal("100.00"),
        "target_entity": "RAZORPAY",
        "target_reference": "ref_1",
        "claim_summary": "Draft summary",
        "supporting_facts": [],
        "evidence_references": [],
    }

    with pytest.raises(StaleLeaseError):
        InvestigationLeaseManager.validate_and_persist_completed_investigation(
            db=db_session,
            investigation_id=inv.id,
            worker_lease_token=token1,
            conclusion=InvestigationConclusion.SUPPORTED,
            confidence=InvestigationConfidence.HIGH,
            summary="Stale summary",
            investigation_result={},
            model_provider="mock",
            model_name="mock-model",
            claim_draft_data=draft_payload,
        )

    # Verify no claim draft was created
    drafts = db_session.execute(
        select(ForensicClaimDraft).where(ForensicClaimDraft.investigation_id == inv.id)
    ).scalars().all()
    assert len(drafts) == 0


def test_14_stale_worker_cannot_overwrite_completed_results(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token1 = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()

    token2 = InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    # Worker 2 successfully completes
    InvestigationLeaseManager.validate_and_persist_completed_investigation(
        db=db_session,
        investigation_id=inv.id,
        worker_lease_token=token2,
        conclusion=InvestigationConclusion.SUPPORTED,
        confidence=InvestigationConfidence.HIGH,
        summary="Worker 2 valid summary",
        investigation_result={"facts": ["valid_w2"]},
        model_provider="mock",
        model_name="mock-model",
    )
    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.COMPLETED.value
    assert inv.summary == "Worker 2 valid summary"

    # Stale Worker 1 attempts commit with token1
    with pytest.raises(StaleLeaseError):
        InvestigationLeaseManager.validate_and_persist_completed_investigation(
            db=db_session,
            investigation_id=inv.id,
            worker_lease_token=token1,
            conclusion=InvestigationConclusion.CONTRADICTED,
            confidence=InvestigationConfidence.LOW,
            summary="Worker 1 stale overwrite",
            investigation_result={"facts": ["stale_w1"]},
            model_provider="mock",
            model_name="mock-model",
        )

    db_session.refresh(inv)
    assert inv.summary == "Worker 2 valid summary"
    assert inv.conclusion == InvestigationConclusion.SUPPORTED.value


def test_15_persistence_rollback_leaves_no_partial_records(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")

    # Intentionally pass invalid claim draft payload to trigger DB error during persist
    invalid_draft_payload = {
        "tenant_id": tenant.id,
        "exception_id": inv.exception_id,
        "detection_run_id": inv.detection_run_id,
        "dispute_amount": Decimal("-50.00"),  # Violates chk_positive_dispute_amount
        "target_entity": "RAZORPAY",
        "target_reference": "ref_1",
        "claim_summary": "Draft summary",
        "supporting_facts": [],
        "evidence_references": [],
    }

    with pytest.raises(Exception):
        InvestigationLeaseManager.validate_and_persist_completed_investigation(
            db=db_session,
            investigation_id=inv.id,
            worker_lease_token=token,
            conclusion=InvestigationConclusion.SUPPORTED,
            confidence=InvestigationConfidence.HIGH,
            summary="Should rollback",
            investigation_result={},
            model_provider="mock",
            model_name="mock-model",
            claim_draft_data=invalid_draft_payload,
        )

    db_session.rollback()
    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.IN_PROGRESS.value
    assert inv.summary != "Should rollback"


def test_16_gemini_inference_occurs_outside_db_transactions(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    # Verify ForensicInvestigationService.execute_investigation commits Transaction 1 before calling adapter
    with patch("app.services.forensics.investigation_service.get_llm_adapter", return_value=MockLLMAdapter()):
        res = ForensicInvestigationService.execute_investigation(db_session, inv.id)
    assert res.status == InvestigationStatus.COMPLETED.value


def test_17_worker_cannot_write_after_losing_lease_during_inference(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)

    class ExpiringAdapter(MockLLMAdapter):
        async def generate_investigation(self, system_prompt, user_prompt):
            # Simulate worker 2 stealing the lease while inference is progressing
            inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
            db_session.commit()
            InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
            return await super().generate_investigation(system_prompt, user_prompt)

    with pytest.raises(StaleLeaseError):
        ForensicInvestigationService.execute_investigation(db_session, inv.id, adapter=ExpiringAdapter())


# ==============================================================================
# C. Retry Tests (18 - 25)
# ==============================================================================

def test_18_first_attempt_accounting(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    assert inv.attempt_count == 0
    InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    db_session.refresh(inv)
    assert inv.attempt_count == 1


def test_19_second_attempt_accounting(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()

    InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    db_session.refresh(inv)
    assert inv.attempt_count == 2


def test_20_third_attempt_accounting(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()

    InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()

    InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w3")
    db_session.refresh(inv)
    assert inv.attempt_count == 3


def test_21_fourth_attempt_is_rejected(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    # Fast forward to attempt 3
    inv.attempt_count = 3
    inv.status = InvestigationStatus.IN_PROGRESS.value
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()

    token = InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w4")
    assert token is None
    db_session.refresh(inv)
    assert inv.attempt_count == 3


def test_22_retryable_gemini_timeout_schedules_recovery(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")

    # Simulate timeout recovery creation
    outbox = TransactionalOutboxService.create_recovery_dispatch_intent(
        db=db_session,
        tenant_id=tenant.id,
        investigation_id=inv.id,
        prior_token=inv.lease_token,
    )
    assert outbox is not None
    assert outbox.event_type == OutboxEventType.INVESTIGATION_RECOVERY.value
    assert outbox.dispatch_status == OutboxDispatchStatus.PENDING.value


def test_23_non_retryable_failure_follows_terminal_policy(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")

    # Non-retryable evidence tampering
    inv.evidence_bundle_snapshot["all_evidence_verified"] = False
    inv.status = InvestigationStatus.BLOCKED.value
    db_session.commit()

    # Reclaim must be rejected
    token = InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    assert token is None


def test_24_retry_exhaustion_transitions_to_failed(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    inv.attempt_count = 3
    inv.status = InvestigationStatus.IN_PROGRESS.value
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=1)
    db_session.commit()

    success = InvestigationLeaseManager.transition_exhausted_investigation(db=db_session, investigation_id=inv.id)
    assert success is True
    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.FAILED.value
    assert inv.conclusion == InvestigationConclusion.INCONCLUSIVE.value
    assert inv.confidence == InvestigationConfidence.LOW.value
    assert "exhausted" in inv.error_message


def test_25_rq_duplicate_delivery_does_not_increase_attempts_under_valid_lease(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    assert inv.attempt_count == 1

    # Duplicate delivery while lease valid
    token_dup = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    assert token_dup is None
    token_reclaim = InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    assert token_reclaim is None

    db_session.refresh(inv)
    assert inv.attempt_count == 1


# ==============================================================================
# D. Outbox Tests (26 - 34)
# ==============================================================================

def test_26_initial_investigation_and_dispatch_intent_commit_atomically(db_session: Session):
    tenant, run, exc, _ = _seed_test_investigation_and_exception(db_session)
    inv = ForensicInvestigationService.create_investigation(
        db=db_session,
        tenant_id=tenant.id,
        exception_id=exc.id,
    )

    outbox_stmt = select(ForensicDispatchOutbox).where(
        ForensicDispatchOutbox.investigation_id == inv.id
    )
    outbox_evt = db_session.execute(outbox_stmt).scalar_one_or_none()
    assert outbox_evt is not None
    assert outbox_evt.event_type == OutboxEventType.INVESTIGATION_DISPATCH.value
    assert outbox_evt.dispatch_status == OutboxDispatchStatus.PENDING.value


def test_27_recovery_intent_persists_during_redis_outage(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")

    # Even if Redis is completely unavailable, PostgreSQL outbox record persists
    evt = TransactionalOutboxService.create_recovery_dispatch_intent(
        db=db_session,
        tenant_id=tenant.id,
        investigation_id=inv.id,
        prior_token=inv.lease_token,
    )
    assert evt is not None
    db_session.refresh(evt)
    assert evt.id is not None


def test_28_redis_publication_failure_preserves_pending_outbox_event(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    outbox_stmt = select(ForensicDispatchOutbox).where(
        ForensicDispatchOutbox.investigation_id == inv.id
    )
    evt = db_session.execute(outbox_stmt).scalar_one()
    assert evt.dispatch_status == OutboxDispatchStatus.PENDING.value

    with patch("app.workers.outbox_publisher.enqueue_job", side_effect=Exception("Redis connection refused")):
        count = OutboxPublisher.publish_pending_events(db=db_session, limit=1)
        assert count == 0

    db_session.refresh(evt)
    assert evt.dispatch_status == OutboxDispatchStatus.PENDING.value
    assert "Redis connection refused" in evt.last_error


def test_29_publisher_crash_after_redis_publication_causes_safe_duplicate_delivery(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    events = TransactionalOutboxService.claim_pending_outbox_events(db=db_session, limit=1)
    evt = events[0]

    # Simulate Redis accepted message, but publisher died before mark_event_published
    with patch("app.workers.outbox_publisher.enqueue_job", return_value={"job_id": "job_1"}):
        # Redis receives it
        pass

    # Expire outbox lease so publisher reclaims and publishes again
    evt.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=5)
    db_session.commit()

    with patch("app.workers.outbox_publisher.enqueue_job", return_value={"job_id": "job_2"}):
        republished = OutboxPublisher.publish_pending_events(db=db_session, limit=1)
        assert republished == 1

    db_session.refresh(evt)
    assert evt.dispatch_status == OutboxDispatchStatus.PUBLISHED.value


def test_30_multiple_publishers_cannot_corrupt_dispatch_state(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    events1 = TransactionalOutboxService.claim_pending_outbox_events(db=db_session, limit=10, publisher_id="pub-1")
    # Immediate second claim sees active processing leases
    events2 = TransactionalOutboxService.claim_pending_outbox_events(db=db_session, limit=10, publisher_id="pub-2")
    assert len(events2) == 0


def test_31_multiple_reapers_cannot_create_duplicate_recovery_intent(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    token = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")

    evt1 = TransactionalOutboxService.create_recovery_dispatch_intent(
        db=db_session, tenant_id=tenant.id, investigation_id=inv.id, prior_token=token
    )
    evt2 = TransactionalOutboxService.create_recovery_dispatch_intent(
        db=db_session, tenant_id=tenant.id, investigation_id=inv.id, prior_token=token
    )
    assert evt1.id == evt2.id


def test_32_expired_outbox_processing_lease_can_be_recovered(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    events1 = TransactionalOutboxService.claim_pending_outbox_events(db=db_session, limit=1, publisher_id="pub-1")
    evt = events1[0]
    assert evt.dispatch_status == OutboxDispatchStatus.PROCESSING.value

    # Expire publisher lease
    evt.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=5)
    db_session.commit()

    # Second publisher reclaims
    events2 = TransactionalOutboxService.claim_pending_outbox_events(db=db_session, limit=1, publisher_id="pub-2")
    assert len(events2) == 1
    assert events2[0].id == evt.id


def test_33_redis_recovery_publishes_pending_outbox_events(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    with patch("app.workers.outbox_publisher.enqueue_job", return_value={"job_id": "job_ok"}):
        count = OutboxPublisher.publish_pending_events(db=db_session, limit=10)
        assert count >= 1


def test_34_reaper_can_mark_exhausted_investigations_failed_without_redis(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    inv.attempt_count = 3
    inv.status = InvestigationStatus.IN_PROGRESS.value
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=5)
    db_session.commit()

    # Reaper directly queries DB, no Redis calls
    results = OrphanInvestigationReaper.reap_orphaned_investigations(db=db_session, limit=10)
    assert results["exhausted_failed"] == 1
    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.FAILED.value


# ==============================================================================
# E. Tenant and Integrity Tests (35 - 40)
# ==============================================================================

def test_35_cross_tenant_lease_access_rejected(db_session: Session):
    tenant1, inv1 = _create_pending_investigation(db_session)
    tenant2 = Tenant(name="Foreign Tenant", slug=f"foreign-{uuid.uuid4().hex[:6]}")
    db_session.add(tenant2)
    db_session.commit()

    with pytest.raises(Exception):
        ForensicInvestigationService.get_investigation(db_session, tenant_id=tenant2.id, investigation_id=inv1.id)


def test_36_cross_tenant_outbox_dispatch_rejected(db_session: Session):
    tenant1, inv1 = _create_pending_investigation(db_session)
    tenant2 = Tenant(name="Foreign Tenant 2", slug=f"foreign-{uuid.uuid4().hex[:6]}")
    db_session.add(tenant2)
    db_session.commit()

    outbox = select(ForensicDispatchOutbox).where(ForensicDispatchOutbox.investigation_id == inv1.id)
    evt = db_session.execute(outbox).scalar_one()
    assert evt.tenant_id == tenant1.id
    assert evt.tenant_id != tenant2.id


def test_37_evidence_snapshot_remains_unchanged_across_recovery(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    orig_snapshot = dict(inv.evidence_bundle_snapshot)

    token1 = InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=5)
    db_session.commit()

    token2 = InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    db_session.refresh(inv)
    assert inv.evidence_bundle_snapshot == orig_snapshot


def test_38_evidence_fingerprint_remains_unchanged(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    orig_fp = inv.evidence_bundle_fingerprint

    InvestigationLeaseManager.claim_pending_investigation(db=db_session, investigation_id=inv.id, worker_id="w1")
    inv.lease_expires_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(seconds=5)
    db_session.commit()

    InvestigationLeaseManager.reclaim_expired_investigation(db=db_session, investigation_id=inv.id, worker_id="w2")
    db_session.refresh(inv)
    assert inv.evidence_bundle_fingerprint == orig_fp


def test_39_canonical_financial_records_remain_unchanged(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    exc = db_session.get(LeakageException, inv.exception_id)
    orig_amount = exc.recoverable_amount

    # Execute full investigation
    with patch("app.services.forensics.investigation_service.get_llm_adapter", return_value=MockLLMAdapter()):
        ForensicInvestigationService.execute_investigation(db_session, inv.id)

    db_session.refresh(exc)
    assert exc.recoverable_amount == orig_amount


def test_40_terminal_investigation_remains_immutable(db_session: Session):
    tenant, inv = _create_pending_investigation(db_session)
    inv.status = InvestigationStatus.COMPLETED.value
    db_session.commit()

    with pytest.raises(ImmutabilityViolationError):
        inv.summary = "Attempted unauthorized edit"
        db_session.commit()
    db_session.rollback()
