import os
import sys
import signal
import logging
from typing import List
from rq import Worker, Queue
import redis

from app.core.config import settings
from app.workers.queue import get_redis_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [finora-worker] %(name)s: %(message)s"
)
logger = logging.getLogger("worker_entrypoint")


def run_worker(queue_names: List[str] = None):
    if not queue_names:
        queue_names = ["finora_reconciliation_tasks"]

    logger.info("Initializing Finora Background Worker...")
    logger.info("Environment: %s", settings.ENVIRONMENT)
    logger.info("Queues: %s", ", ".join(queue_names))

    # Connect to Redis with retry loop for container orchestration readiness
    max_retries = 15
    retry_interval = 2
    redis_conn = None

    for attempt in range(1, max_retries + 1):
        try:
            redis_conn = get_redis_client(force_reconnect=True)
            if redis_conn:
                redis_conn.ping()
                logger.info("Connected to Redis at %s", settings.REDIS_URL.split("@")[-1])
                break
        except Exception as e:
            logger.warning(
                "Redis connection attempt %d/%d failed (%s). Retrying in %ds...",
                attempt, max_retries, e, retry_interval
            )
            import time
            time.sleep(retry_interval)

    if not redis_conn:
        logger.error("Could not establish connection to Redis after %d attempts. Exiting.", max_retries)
        sys.exit(1)

    queues = [Queue(name, connection=redis_conn) for name in queue_names]

    # Initialize RQ worker with graceful shutdown signals handled natively
    worker = Worker(
        queues=queues,
        connection=redis_conn,
        name=f"finora-worker-{os.getpid()}"
    )

    logger.info("Worker %s successfully started. Listening for background jobs...", worker.name)
    try:
        worker.work(with_scheduler=True)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker received shutdown signal. Terminating gracefully...")
    finally:
        logger.info("Worker shutdown complete.")


if __name__ == "__main__":
    cli_queues = sys.argv[1:] if len(sys.argv) > 1 else ["finora_reconciliation_tasks"]
    run_worker(cli_queues)
