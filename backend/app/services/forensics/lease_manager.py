import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import update, select, and_

from app.core.config import settings
from app.models.forensic import (
    ForensicInvestigation,
    ForensicClaimDraft,
    InvestigationStatus,
    InvestigationConclusion,
    InvestigationConfidence,
    ClaimDraftStatus,
    ClaimDraftReviewStatus,
)
from app.services.forensics.exceptions import StaleLeaseError, LeaseRenewalError
from app.services.forensics.monitoring import ForensicMetricsCollector

logger = logging.getLogger(__name__)


class InvestigationLeaseManager:
    """
    Authoritative PostgreSQL lease manager for forensic investigations.
    Coordinates atomic initial claiming, expired lease reclamation, strict heartbeat renewal,
    retry attempt accounting, and fencing-protected transaction persistence.
    """

    DEFAULT_LEASE_DURATION = getattr(settings, "FORENSIC_LEASE_DURATION_SECONDS", 300)
    MAX_ATTEMPTS = getattr(settings, "FORENSIC_MAX_EXECUTION_ATTEMPTS", 3)

    @classmethod
    def _is_postgresql(cls, session: Session) -> bool:
        bind = session.get_bind()
        return bind.dialect.name == "postgresql"

    @classmethod
    def _get_expiry_expr(cls, session: Session, duration_seconds: int):
        if cls._is_postgresql(session):
            return sa.text(f"NOW() + make_interval(secs => {int(duration_seconds)})")
        else:
            return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=duration_seconds)

    @classmethod
    def _get_now_expr(cls, session: Session):
        if cls._is_postgresql(session):
            return sa.func.now()
        else:
            return datetime.now(timezone.utc).replace(tzinfo=None)

    # --------------------------------------------------------------------------
    # Operation 1: Initial Atomic Claim (PENDING -> IN_PROGRESS)
    # --------------------------------------------------------------------------
    @classmethod
    def claim_pending_investigation(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        worker_id: str,
        lease_duration_seconds: Optional[int] = None,
    ) -> Optional[uuid.UUID]:
        """
        Operation 1: Claims a PENDING investigation atomically.
        Increments attempt_count exactly once (from 0 to 1).
        Generates a fresh UUID ownership token.
        Returns the lease_token if claim succeeded, or None if already claimed.
        """
        duration = lease_duration_seconds or cls.DEFAULT_LEASE_DURATION
        token = uuid.uuid4()
        now_expr = cls._get_now_expr(db)
        expiry_expr = cls._get_expiry_expr(db, duration)

        stmt = (
            update(ForensicInvestigation)
            .where(
                ForensicInvestigation.id == investigation_id,
                ForensicInvestigation.status == InvestigationStatus.PENDING.value,
                ForensicInvestigation.attempt_count == 0,
            )
            .values(
                status=InvestigationStatus.IN_PROGRESS.value,
                lease_owner_id=worker_id,
                lease_token=token,
                lease_expires_at=expiry_expr,
                last_heartbeat_at=now_expr,
                attempt_count=ForensicInvestigation.attempt_count + 1,
                updated_at=now_expr,
            )
        )
        result = db.execute(stmt.execution_options(synchronize_session=False))
        db.commit()

        if result.rowcount == 1:
            logger.info(
                "Worker %s successfully claimed PENDING investigation %s with lease token %s (attempt 1)",
                worker_id,
                investigation_id,
                token,
            )
            ForensicMetricsCollector.record_investigation_started(str(investigation_id), worker_id)
            return token
        return None

    # --------------------------------------------------------------------------
    # Operation 2: Atomic Reclamation of Expired Lease (IN_PROGRESS -> IN_PROGRESS)
    # --------------------------------------------------------------------------
    @classmethod
    def reclaim_expired_investigation(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        worker_id: str,
        expected_prior_token: Optional[uuid.UUID] = None,
        lease_duration_seconds: Optional[int] = None,
    ) -> Optional[uuid.UUID]:
        """
        Operation 2: Reclaims an expired IN_PROGRESS investigation atomically.
        Requires lease_expires_at < NOW() and attempt_count < MAX_ATTEMPTS.
        Generates a fresh UUID ownership token, invalidating previous owner.
        Increments attempt_count by 1.
        Returns new lease_token if reclamation succeeded, or None.
        """
        duration = lease_duration_seconds or cls.DEFAULT_LEASE_DURATION
        token = uuid.uuid4()
        now_expr = cls._get_now_expr(db)
        expiry_expr = cls._get_expiry_expr(db, duration)

        conditions = [
            ForensicInvestigation.id == investigation_id,
            ForensicInvestigation.status == InvestigationStatus.IN_PROGRESS.value,
            ForensicInvestigation.lease_expires_at < now_expr,
            ForensicInvestigation.attempt_count < cls.MAX_ATTEMPTS,
        ]

        if expected_prior_token is not None:
            conditions.append(ForensicInvestigation.lease_token == expected_prior_token)

        stmt = (
            update(ForensicInvestigation)
            .where(and_(*conditions))
            .values(
                status=InvestigationStatus.IN_PROGRESS.value,
                lease_owner_id=worker_id,
                lease_token=token,
                lease_expires_at=expiry_expr,
                last_heartbeat_at=now_expr,
                attempt_count=ForensicInvestigation.attempt_count + 1,
                error_message="Reclaimed after previous worker lease expired.",
                updated_at=now_expr,
            )
        )
        result = db.execute(stmt.execution_options(synchronize_session=False))
        db.commit()

        if result.rowcount == 1:
            logger.info(
                "Worker %s successfully reclaimed expired investigation %s with fresh token %s",
                worker_id,
                investigation_id,
                token,
            )
            return token
        return None

    # --------------------------------------------------------------------------
    # Strict Heartbeat Renewal
    # --------------------------------------------------------------------------
    @classmethod
    def renew_lease(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        worker_lease_token: uuid.UUID,
        lease_duration_seconds: Optional[int] = None,
    ) -> bool:
        """
        Strict heartbeat renewal.
        Requires:
        - Matching investigation_id
        - status == 'IN_PROGRESS'
        - Matching current lease_token
        - lease_expires_at > NOW() (Strict prohibition: expired lease cannot be renewed)
        Returns True on successful renewal, False if expired/revoked.
        """
        duration = lease_duration_seconds or cls.DEFAULT_LEASE_DURATION
        now_expr = cls._get_now_expr(db)
        expiry_expr = cls._get_expiry_expr(db, duration)

        stmt = (
            update(ForensicInvestigation)
            .where(
                ForensicInvestigation.id == investigation_id,
                ForensicInvestigation.status == InvestigationStatus.IN_PROGRESS.value,
                ForensicInvestigation.lease_token == worker_lease_token,
                ForensicInvestigation.lease_expires_at > now_expr,
            )
            .values(
                lease_expires_at=expiry_expr,
                last_heartbeat_at=now_expr,
                updated_at=now_expr,
            )
        )
        result = db.execute(stmt.execution_options(synchronize_session=False))
        db.commit()

        renewed = result.rowcount == 1
        if renewed:
            logger.debug("Lease successfully renewed for investigation %s (token %s)", investigation_id, worker_lease_token)
        else:
            logger.warning(
                "Lease renewal rejected for investigation %s (token %s): lease expired or ownership lost.",
                investigation_id,
                worker_lease_token,
            )
        return renewed

    # --------------------------------------------------------------------------
    # Exhausted Retries Transition to Terminal FAILED
    # --------------------------------------------------------------------------
    @classmethod
    def transition_exhausted_investigation(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        commit: bool = True,
    ) -> bool:
        """
        Transitions an investigation to terminal FAILED if attempts >= MAX_ATTEMPTS and lease expired.
        """
        now_expr = cls._get_now_expr(db)
        stmt = (
            update(ForensicInvestigation)
            .where(
                ForensicInvestigation.id == investigation_id,
                ForensicInvestigation.status == InvestigationStatus.IN_PROGRESS.value,
                ForensicInvestigation.lease_expires_at < now_expr,
                ForensicInvestigation.attempt_count >= cls.MAX_ATTEMPTS,
            )
            .values(
                status=InvestigationStatus.FAILED.value,
                conclusion=InvestigationConclusion.INCONCLUSIVE.value,
                confidence=InvestigationConfidence.LOW.value,
                error_message=f"Investigation failed: Maximum worker lease recovery attempts ({cls.MAX_ATTEMPTS}) exhausted.",
                lease_owner_id=None,
                lease_token=None,
                lease_expires_at=None,
                updated_at=now_expr,
            )
        )
        result = db.execute(stmt.execution_options(synchronize_session=False))
        if commit:
            db.commit()
        if result.rowcount == 1:
            logger.warning(
                "Investigation %s retries exhausted (%d attempts); transitioned to FAILED/INCONCLUSIVE.",
                investigation_id,
                cls.MAX_ATTEMPTS,
            )
            return True
        return False

    # --------------------------------------------------------------------------
    # Transaction-Wide Fencing Persistence
    # --------------------------------------------------------------------------
    @classmethod
    def validate_and_persist_completed_investigation(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        worker_lease_token: uuid.UUID,
        conclusion: InvestigationConclusion,
        confidence: InvestigationConfidence,
        summary: str,
        investigation_result: Dict[str, Any],
        model_provider: str,
        model_name: str,
        claim_draft_data: Optional[Dict[str, Any]] = None,
    ) -> ForensicInvestigation:
        """
        Atomically validates lease ownership and persists complete investigation findings.
        If ownership validation fails (stale worker or expired lease), rolls back immediately
        and raises StaleLeaseError.
        """
        now_expr = cls._get_now_expr(db)
        try:
            # Step 1: Conditional update on investigation
            stmt = (
                update(ForensicInvestigation)
                .where(
                    ForensicInvestigation.id == investigation_id,
                    ForensicInvestigation.status == InvestigationStatus.IN_PROGRESS.value,
                    ForensicInvestigation.lease_token == worker_lease_token,
                    ForensicInvestigation.lease_expires_at > now_expr,
                )
                .values(
                    status=InvestigationStatus.COMPLETED.value,
                    conclusion=conclusion.value,
                    confidence=confidence.value,
                    summary=summary,
                    investigation_result=investigation_result,
                    model_provider=model_provider,
                    model_name=model_name,
                    error_message=None,
                    lease_owner_id=None,
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=now_expr,
                )
            )
            result = db.execute(stmt.execution_options(synchronize_session=False))
            if result.rowcount != 1:
                db.rollback()
                raise StaleLeaseError(
                    f"Fencing validation failed for investigation {investigation_id}. "
                    f"Lease token {worker_lease_token} is stale, superseded, or expired. Write rejected."
                )

            # Step 2: If a claim draft is being generated, persist it in the exact same transaction
            if claim_draft_data:
                draft = ForensicClaimDraft(
                    tenant_id=claim_draft_data["tenant_id"],
                    exception_id=claim_draft_data["exception_id"],
                    investigation_id=investigation_id,
                    detection_run_id=claim_draft_data["detection_run_id"],
                    draft_number=claim_draft_data.get("draft_number", 1),
                    status=ClaimDraftStatus.DRAFT.value,
                    dispute_amount=claim_draft_data["dispute_amount"],
                    currency=claim_draft_data.get("currency", "INR"),
                    target_entity=claim_draft_data["target_entity"],
                    target_reference=claim_draft_data["target_reference"],
                    claim_summary=claim_draft_data["claim_summary"],
                    supporting_facts=claim_draft_data["supporting_facts"],
                    evidence_references=claim_draft_data["evidence_references"],
                    human_review_status=ClaimDraftReviewStatus.PENDING_HUMAN_REVIEW.value,
                    created_by_user_id=claim_draft_data.get("created_by_user_id"),
                )
                db.add(draft)

            # Step 3: Atomic commit of findings, conclusion, and claim draft
            db.commit()

            inv = db.get(ForensicInvestigation, investigation_id)
            logger.info("Investigation %s successfully completed under lease token %s", investigation_id, worker_lease_token)
            return inv

        except Exception:
            db.rollback()
            raise
