"""
Management CLI command for invoking the Orphan Investigation Reaper.
Usage:
    python -m app.workers.orphan_reaper_cli [--limit 50] [--publish]
"""
import sys
import argparse
import logging
from app.core.database import SessionLocal
from app.services.forensics.orphan_reaper import OrphanInvestigationReaper
from app.workers.outbox_publisher import OutboxPublisher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("reaper_cli")


def main():
    parser = argparse.ArgumentParser(description="Finora Forensic Orphan Investigation Reaper")
    parser.add_argument("--limit", type=int, default=50, help="Max expired investigations to scan")
    parser.add_argument("--publish", action="store_true", help="Also publish pending outbox events to queue")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        logger.info("Executing Orphan Investigation Reaper (limit=%d)...", args.limit)
        results = OrphanInvestigationReaper.reap_orphaned_investigations(db, limit=args.limit)
        logger.info(
            "Reaper execution finished. Scanned: %d, Exhausted Failed: %d, Recovery Intent: %d",
            results["scanned"],
            results["exhausted_failed"],
            results["recovery_enqueued"],
        )

        if args.publish:
            logger.info("Publishing pending outbox events...")
            pub_count = OutboxPublisher.publish_pending_events(db, limit=args.limit)
            logger.info("Published %d outbox events to queue.", pub_count)

    finally:
        db.close()


if __name__ == "__main__":
    main()
