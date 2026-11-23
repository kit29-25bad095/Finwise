import uuid
import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.workers.queue import enqueue_job
from app.workers.forensic_tasks import process_forensic_investigation_job
from app.services.forensics.outbox_service import TransactionalOutboxService

logger = logging.getLogger(__name__)


class OutboxPublisher:
    """
    Idempotent outbox publisher that drains durable outbox events from PostgreSQL
    and delivers them to the Redis/RQ task queue.
    """

    @classmethod
    def publish_pending_events(
        cls,
        db: Session,
        limit: Optional[int] = None,
        publisher_id: str = "outbox-publisher-1",
    ) -> int:
        """
        Claims a batch of pending outbox events, dispatches them to RQ,
        and marks them published.
        If Redis is unavailable, events remain durable in PostgreSQL for future retry.
        """
        events = TransactionalOutboxService.claim_pending_outbox_events(
            db=db, limit=limit, publisher_id=publisher_id
        )
        if not events:
            return 0

        published_count = 0
        for event in events:
            try:
                # Dispatch to RQ worker queue
                enqueue_job(process_forensic_investigation_job, str(event.investigation_id))
                TransactionalOutboxService.mark_event_published(db, event.id)
                published_count += 1
                logger.info(
                    "Outbox event %s for investigation %s published to queue (type: %s)",
                    event.id,
                    event.investigation_id,
                    event.event_type,
                )
            except Exception as e:
                logger.warning(
                    "Failed to publish outbox event %s to queue (%s). Event left durable in DB for retry.",
                    event.id,
                    str(e),
                )
                TransactionalOutboxService.mark_event_failed(db, event.id, str(e))

        return published_count
