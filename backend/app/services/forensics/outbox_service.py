import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import select, update, and_
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.forensic import (
    ForensicDispatchOutbox,
    OutboxDispatchStatus,
    OutboxEventType,
)

logger = logging.getLogger(__name__)


class TransactionalOutboxService:
    """
    Manages durable dispatch intent co-committed within the same PostgreSQL transaction
    as forensic investigation lifecycle transitions.
    """

    BATCH_SIZE = getattr(settings, "FORENSIC_OUTBOX_BATCH_SIZE", 50)
    LEASE_SECONDS = getattr(settings, "FORENSIC_OUTBOX_LEASE_SECONDS", 60)

    @classmethod
    def _is_postgresql(cls, session: Session) -> bool:
        bind = session.get_bind()
        return bind.dialect.name == "postgresql"

    @classmethod
    def _get_now_expr(cls, session: Session):
        if cls._is_postgresql(session):
            return sa.func.now()
        else:
            return datetime.now(timezone.utc).replace(tzinfo=None)

    @classmethod
    def _get_expiry_expr(cls, session: Session, duration_seconds: int):
        if cls._is_postgresql(session):
            return sa.text(f"NOW() + make_interval(secs => {int(duration_seconds)})")
        else:
            return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=duration_seconds)

    # --------------------------------------------------------------------------
    # Initial Dispatch Intent (Atomically co-committed with investigation creation)
    # --------------------------------------------------------------------------
    @classmethod
    def create_initial_dispatch_intent(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        investigation_id: uuid.UUID,
    ) -> ForensicDispatchOutbox:
        """
        Creates an initial dispatch intent record for a newly created PENDING investigation.
        Does NOT commit, allowing the caller to commit both in a single transaction.
        """
        idempotency_key = f"{investigation_id}:{OutboxEventType.INVESTIGATION_DISPATCH.value}:initial"

        stmt = select(ForensicDispatchOutbox).where(
            ForensicDispatchOutbox.idempotency_key == idempotency_key
        )
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            return existing

        outbox_event = ForensicDispatchOutbox(
            tenant_id=tenant_id,
            investigation_id=investigation_id,
            event_type=OutboxEventType.INVESTIGATION_DISPATCH.value,
            idempotency_key=idempotency_key,
            expected_prior_token=None,
            dispatch_status=OutboxDispatchStatus.PENDING.value,
            attempt_count=0,
        )
        db.add(outbox_event)
        return outbox_event

    # --------------------------------------------------------------------------
    # Recovery Dispatch Intent (Persisted by Orphan Reaper)
    # --------------------------------------------------------------------------
    @classmethod
    def create_recovery_dispatch_intent(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        investigation_id: uuid.UUID,
        prior_token: Optional[uuid.UUID] = None,
        commit: bool = True,
    ) -> Optional[ForensicDispatchOutbox]:
        """
        Creates a recovery dispatch intent for an orphaned/expired investigation.
        Idempotent by investigation_id + event_type + prior_token.
        """
        token_str = str(prior_token) if prior_token else "none"
        idempotency_key = f"{investigation_id}:{OutboxEventType.INVESTIGATION_RECOVERY.value}:{token_str}"

        stmt = select(ForensicDispatchOutbox).where(
            ForensicDispatchOutbox.idempotency_key == idempotency_key
        )
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            return existing

        outbox_event = ForensicDispatchOutbox(
            tenant_id=tenant_id,
            investigation_id=investigation_id,
            event_type=OutboxEventType.INVESTIGATION_RECOVERY.value,
            idempotency_key=idempotency_key,
            expected_prior_token=prior_token,
            dispatch_status=OutboxDispatchStatus.PENDING.value,
            attempt_count=0,
        )
        try:
            db.add(outbox_event)
            if commit:
                db.commit()
                db.refresh(outbox_event)
            else:
                db.flush()
            return outbox_event
        except IntegrityError:
            db.rollback()
            existing = db.execute(stmt).scalar_one_or_none()
            return existing

    # --------------------------------------------------------------------------
    # Claim Batch for Publishing (Concurrency-Safe with SKIP LOCKED)
    # --------------------------------------------------------------------------
    @classmethod
    def claim_pending_outbox_events(
        cls,
        db: Session,
        limit: Optional[int] = None,
        publisher_id: str = "outbox-publisher-default",
    ) -> List[ForensicDispatchOutbox]:
        """
        Claims a batch of pending or expired-processing outbox events using FOR UPDATE SKIP LOCKED
        in PostgreSQL to allow concurrent publishers without collisions.
        """
        batch_limit = limit or cls.BATCH_SIZE
        now_expr = cls._get_now_expr(db)
        expiry_expr = cls._get_expiry_expr(db, cls.LEASE_SECONDS)

        # Condition: PENDING and available, OR PROCESSING with expired lease
        claim_condition = sa.or_(
            and_(
                ForensicDispatchOutbox.dispatch_status == OutboxDispatchStatus.PENDING.value,
                ForensicDispatchOutbox.available_at <= now_expr,
            ),
            and_(
                ForensicDispatchOutbox.dispatch_status == OutboxDispatchStatus.PROCESSING.value,
                ForensicDispatchOutbox.lease_expires_at < now_expr,
            ),
        )

        stmt = (
            select(ForensicDispatchOutbox)
            .where(claim_condition)
            .order_by(ForensicDispatchOutbox.created_at.asc())
            .limit(batch_limit)
        )

        if cls._is_postgresql(db):
            stmt = stmt.with_for_update(skip_locked=True)

        events = list(db.execute(stmt).scalars().all())
        if not events:
            return []

        # Claim the batch
        event_ids = [e.id for e in events]
        update_stmt = (
            update(ForensicDispatchOutbox)
            .where(ForensicDispatchOutbox.id.in_(event_ids))
            .values(
                dispatch_status=OutboxDispatchStatus.PROCESSING.value,
                lease_owner_id=publisher_id,
                lease_expires_at=expiry_expr,
                attempt_count=ForensicDispatchOutbox.attempt_count + 1,
                updated_at=now_expr,
            )
        )
        db.execute(update_stmt.execution_options(synchronize_session=False))
        db.commit()

        # Refresh claimed records
        for e in events:
            db.refresh(e)
        return events

    # --------------------------------------------------------------------------
    # Mark Event Status Transitions
    # --------------------------------------------------------------------------
    @classmethod
    def mark_event_published(cls, db: Session, event_id: uuid.UUID) -> None:
        now_expr = cls._get_now_expr(db)
        stmt = (
            update(ForensicDispatchOutbox)
            .where(ForensicDispatchOutbox.id == event_id)
            .values(
                dispatch_status=OutboxDispatchStatus.PUBLISHED.value,
                published_at=now_expr,
                lease_owner_id=None,
                lease_expires_at=None,
                updated_at=now_expr,
            )
        )
        db.execute(stmt.execution_options(synchronize_session=False))
        db.commit()

    @classmethod
    def mark_event_failed(cls, db: Session, event_id: uuid.UUID, error_message: str) -> None:
        now_expr = cls._get_now_expr(db)
        # Release back to PENDING with exponential backoff
        backoff_seconds = 10
        available_expr = cls._get_expiry_expr(db, backoff_seconds)
        stmt = (
            update(ForensicDispatchOutbox)
            .where(ForensicDispatchOutbox.id == event_id)
            .values(
                dispatch_status=OutboxDispatchStatus.PENDING.value,
                available_at=available_expr,
                lease_owner_id=None,
                lease_expires_at=None,
                last_error=error_message,
                updated_at=now_expr,
            )
        )
        db.execute(stmt.execution_options(synchronize_session=False))
        db.commit()
