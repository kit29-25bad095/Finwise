import logging
from typing import Any, Callable, Dict, Optional
import redis
from rq import Queue
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None
_task_queue: Optional[Queue] = None
_checked_connection: bool = False


def get_redis_client(force_reconnect: bool = False) -> Optional[redis.Redis]:
    global _redis_client, _checked_connection, _task_queue
    if not force_reconnect and _checked_connection and _redis_client is not None:
        return _redis_client

    if settings.ENVIRONMENT == "test" and not force_reconnect:
        # In test mode, skip network probe by default
        _redis_client = None
        _task_queue = None
        _checked_connection = True
        return None

    _checked_connection = True
    try:
        client = redis.from_url(settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1)
        client.ping()
        _redis_client = client
        _task_queue = Queue("finora_reconciliation_tasks", connection=_redis_client)
        logger.info("Connected to Redis worker queue.")
    except Exception as e:
        _redis_client = None
        _task_queue = None
        if settings.ENVIRONMENT == "production" or not settings.WORKER_FALLBACK_SYNC:
            logger.error(f"Redis unavailable ({e}). Synchronous worker fallback is disabled in {settings.ENVIRONMENT}.")
            raise RuntimeError(
                f"Redis worker queue is unavailable ({e}) and synchronous execution is disabled in {settings.ENVIRONMENT}."
            )
        logger.warning(f"Redis unavailable ({e}). Worker running in fallback synchronous mode for development.")

    return _redis_client


def reset_redis_client_cache() -> None:
    """Resets cached Redis connection state to allow reconnection attempts."""
    global _redis_client, _checked_connection, _task_queue
    _redis_client = None
    _checked_connection = False
    _task_queue = None


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
        elif settings.ENVIRONMENT != "production" and (settings.WORKER_FALLBACK_SYNC or settings.ENVIRONMENT == "test"):
            result = func(*args, **kwargs)
            return {
                "job_id": "sync-local-job",
                "status": "COMPLETED",
                "mode": "SYNC_LOCAL",
                "result": result
            }
        else:
            raise RuntimeError(
                f"Redis task queue is unavailable and synchronous fallback is strictly prohibited in {settings.ENVIRONMENT}."
            )


enqueue_job = WorkerDispatcher.dispatch_job
