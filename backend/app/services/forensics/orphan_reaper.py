import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.models.forensic import (
    ForensicInvestigation,
    ForensicDispatchOutbox,
    InvestigationStatus,
    OutboxDispatchStatus,
    OutboxEventType,
)
from app.services.forensics.lease_manager import InvestigationLeaseManager
from app.services.forensics.outbox_service import TransactionalOutboxService

logger = logging.getLogger(__name__)


class OrphanInvestigationReaper:
    """
    Idempotent orphan-detection and recovery scheduler.
    Directly scans PostgreSQL for expired investigation leases without requiring Redis.
    - Transitions exhausted investigations (attempts >= 3) to FAILED/INCONCLUSIVE.
    - Creates recovery dispatch intent in the transactional outbox for retriable investigations.
    """

    @classmethod
    def _is_postgresql(cls, session: Session) -> bool:
        bind = session.get_bind()
        return bind.dialect.name == "postgresql"

    @classmethod
    def reap_orphaned_investigations(
        cls,
        db: Session,
        limit: int = 50,
    ) -> Dict[str, int]:
        """
        Scans for expired investigations and executes recovery or exhaustion transitions.
        Safe for concurrent execution across multiple reaper instances using SKIP LOCKED.
        Excludes investigations that already have active pending/processing recovery intent.
        """
        now_expr = sa.func.now() if cls._is_postgresql(db) else datetime.now(timezone.utc).replace(tzinfo=None)

        active_outbox_subquery = (
            select(1)
            .where(
                ForensicDispatchOutbox.investigation_id == ForensicInvestigation.id,
                ForensicDispatchOutbox.event_type == OutboxEventType.INVESTIGATION_RECOVERY.value,
                ForensicDispatchOutbox.dispatch_status.in_([
                    OutboxDispatchStatus.PENDING.value,
                    OutboxDispatchStatus.PROCESSING.value,
                ]),
            )
        )

        stmt = (
            select(ForensicInvestigation)
            .where(
                and_(
                    ForensicInvestigation.status == InvestigationStatus.IN_PROGRESS.value,
                    ForensicInvestigation.lease_expires_at < now_expr,
                    ~active_outbox_subquery.exists(),
                )
            )
            .order_by(ForensicInvestigation.lease_expires_at.asc())
            .limit(limit)
        )

        if cls._is_postgresql(db):
            stmt = stmt.with_for_update(skip_locked=True)

        expired_investigations = list(db.execute(stmt).scalars().all())

        exhausted_count = 0
        recovery_intent_count = 0

        for inv in expired_investigations:
            if inv.attempt_count >= InvestigationLeaseManager.MAX_ATTEMPTS:
                # Retries exhausted: Transition to terminal FAILED
                success = InvestigationLeaseManager.transition_exhausted_investigation(db, inv.id, commit=False)
                if success:
                    exhausted_count += 1
                    logger.warning(
                        "Reaper transitioned exhausted investigation %s to FAILED (attempts: %d)",
                        inv.id,
                        inv.attempt_count,
                    )
            else:
                # Retriable: Create recovery dispatch intent in outbox without pre-claiming a lease
                outbox_record = TransactionalOutboxService.create_recovery_dispatch_intent(
                    db=db,
                    tenant_id=inv.tenant_id,
                    investigation_id=inv.id,
                    prior_token=inv.lease_token,
                    commit=False,
                )
                if outbox_record:
                    recovery_intent_count += 1
                    logger.info(
                        "Reaper created recovery outbox intent for investigation %s (attempt %d -> %d)",
                        inv.id,
                        inv.attempt_count,
                        inv.attempt_count + 1,
                    )

        if expired_investigations:
            db.commit()

        return {
            "scanned": len(expired_investigations),
            "exhausted_failed": exhausted_count,
            "recovery_enqueued": recovery_intent_count,
        }
