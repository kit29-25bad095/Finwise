import logging
from typing import Any, Callable, Dict, Optional
import redis
from rq import Queue
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None
_task_queue: Optional[Queue] = None
_checked_connection: bool = False


def get_redis_client() -> Optional[redis.Redis]:
    global _redis_client, _checked_connection, _task_queue
    if _checked_connection:
        return _redis_client

    _checked_connection = True
    if settings.ENVIRONMENT == "test" or settings.WORKER_FALLBACK_SYNC:
        # In test mode or when sync fallback is explicitly preferred, skip network probe
        _redis_client = None
        _task_queue = None
        return None

    try:
        client = redis.from_url(settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1)
        client.ping()
        _redis_client = client
        _task_queue = Queue("finora_reconciliation_tasks", connection=_redis_client)
        logger.info("Connected to Redis worker queue.")
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}). Worker running in fallback synchronous mode.")
        _redis_client = None
        _task_queue = None

    return _redis_client


class WorkerDispatcher:
    @staticmethod
    def dispatch_job(
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> Dict[str, Any]:
        client = get_redis_client()
        if client and _task_queue:
            job = _task_queue.enqueue(func, *args, **kwargs)
            return {
                "job_id": job.get_id(),
                "status": "QUEUED",
                "mode": "ASYNC_REDIS"
            }
        elif settings.WORKER_FALLBACK_SYNC or settings.ENVIRONMENT == "test":
            result = func(*args, **kwargs)
            return {
                "job_id": "sync-local-job",
                "status": "COMPLETED",
                "mode": "SYNC_LOCAL",
                "result": result
            }
        else:
            raise RuntimeError("Redis task queue is unavailable and synchronous fallback is disabled.")


enqueue_job = WorkerDispatcher.dispatch_job
