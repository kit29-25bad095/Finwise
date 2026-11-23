import sys
import time
import signal
import logging
from threading import Event

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.forensics.orphan_reaper import OrphanInvestigationReaper
from app.workers.outbox_publisher import OutboxPublisher
from app.services.storage.file_storage import PrivateFileStorageService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [finora-scheduler] %(name)s: %(message)s"
)
logger = logging.getLogger("scheduler")

shutdown_event = Event()


def handle_shutdown_signal(signum, frame):
    logger.info("Received termination signal (%s). Initiating graceful scheduler shutdown...", signum)
    shutdown_event.set()


def run_scheduler_loop(
    reaper_interval_seconds: int = 60,
    outbox_interval_seconds: int = 15,
    retention_interval_seconds: int = 86400,
):
    """
    Continuous background daemon running periodic recovery and maintenance tasks:
    1. Transactional Outbox draining (every 15s)
    2. Orphan investigation lease recovery (every 60s)
    3. Document retention policy enforcement (daily)
    """
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    logger.info("Starting Finora Maintenance & Recovery Scheduler...")
    logger.info("Outbox drain interval: %ds", outbox_interval_seconds)
    logger.info("Orphan lease reaper interval: %ds", reaper_interval_seconds)
    logger.info("Retention sweep interval: %ds", retention_interval_seconds)

    last_outbox_run = 0.0
    last_reaper_run = 0.0
    last_retention_run = 0.0

    while not shutdown_event.is_set():
        now = time.time()

        # 1. Drain Transactional Outbox
        if now - last_outbox_run >= outbox_interval_seconds:
            try:
                db = SessionLocal()
                try:
                    published = OutboxPublisher.publish_pending_events(db, limit=50)
                    if published > 0:
                        logger.info("OutboxPublisher delivered %d events to queue.", published)
                finally:
                    db.close()
            except Exception as e:
                logger.error("Error running OutboxPublisher: %s", e)
            last_outbox_run = now

        # 2. Reclaim Orphaned Investigation Leases
        if now - last_reaper_run >= reaper_interval_seconds:
            try:
                db = SessionLocal()
                try:
                    results = OrphanInvestigationReaper.reap_orphaned_investigations(db, limit=50)
                    if results["recovery_enqueued"] > 0 or results["exhausted_failed"] > 0:
                        logger.warning(
                            "OrphanReaper recovered: %d re-queued, %d exhausted/failed (scanned: %d)",
                            results["recovery_enqueued"],
                            results["exhausted_failed"],
                            results["scanned"],
                        )
                finally:
                    db.close()
            except Exception as e:
                logger.error("Error running OrphanInvestigationReaper: %s", e)
            last_reaper_run = now

        # 3. Purge Expired Financial Files
        if now - last_retention_run >= retention_interval_seconds:
            try:
                purged = PrivateFileStorageService.purge_expired_files()
                if purged > 0:
                    logger.info("PrivateFileStorageService purged %d expired files.", purged)
            except Exception as e:
                logger.error("Error running retention file purge: %s", e)
            last_retention_run = now

        # Sleep briefly (1 second increments) to allow prompt exit on shutdown
        shutdown_event.wait(timeout=1.0)

    logger.info("Scheduler daemon terminated cleanly.")


if __name__ == "__main__":
    run_scheduler_loop()
