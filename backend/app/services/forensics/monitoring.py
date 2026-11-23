import time
from typing import Dict, Any, Optional
from collections import defaultdict
import redis
from app.core.config import settings
from app.workers.queue import get_redis_client, _task_queue


class ForensicMetricsCollector:
    """
    In-memory and Redis-backed metrics collector for Phase 5 AI Forensic Investigations.
    Monitors execution counts, latencies, token consumption, costs, queue depths,
    and integrity failure counters with strict tenant isolation.
    """
    _counters: Dict[str, int] = defaultdict(int)
    _latencies: Dict[str, list] = defaultdict(list)
    _tokens: Dict[str, int] = defaultdict(int)
    _costs_usd: float = 0.0

    # Tenant-isolated metric partitions
    _tenant_counters: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    _tenant_latencies: Dict[str, list] = defaultdict(list)
    _tenant_tokens: Dict[str, int] = defaultdict(int)
    _tenant_costs_usd: Dict[str, float] = defaultdict(float)

    @classmethod
    def record_investigation_started(cls, tenant_id: str, model: str) -> None:
        cls._counters["investigations_started"] += 1
        cls._counters[f"investigations_started_tenant_{tenant_id}"] += 1
        cls._tenant_counters[str(tenant_id)]["started"] += 1

    @classmethod
    def record_investigation_completed(
        cls,
        tenant_id: str,
        model: str,
        latency_ms: float,
        tokens: int = 0,
        cost_usd: float = 0.0,
        conclusion: str = "INCONCLUSIVE",
        confidence: str = "LOW"
    ) -> None:
        t_id = str(tenant_id)
        cls._counters["investigations_completed"] += 1
        cls._counters[f"investigations_conclusion_{conclusion.lower()}"] += 1
        cls._counters[f"investigations_confidence_{confidence.lower()}"] += 1
        cls._latencies["execution_latency_ms"].append(latency_ms)
        cls._tokens["total_tokens_consumed"] += tokens
        cls._costs_usd += cost_usd

        cls._tenant_counters[t_id]["completed"] += 1
        cls._tenant_counters[t_id][f"conclusion_{conclusion.lower()}"] += 1
        cls._tenant_counters[t_id][f"confidence_{confidence.lower()}"] += 1
        cls._tenant_latencies[t_id].append(latency_ms)
        cls._tenant_tokens[t_id] += tokens
        cls._tenant_costs_usd[t_id] += cost_usd

    @classmethod
    def record_investigation_failed(cls, tenant_id: str, error_type: str = "generic") -> None:
        cls._counters["investigations_failed"] += 1
        cls._counters[f"investigations_failed_{error_type}"] += 1
        cls._tenant_counters[str(tenant_id)]["failed"] += 1
        cls._tenant_counters[str(tenant_id)][f"failed_{error_type}"] += 1

    @classmethod
    def record_investigation_blocked(cls, tenant_id: str, reason: str = "integrity_failure") -> None:
        cls._counters["investigations_blocked"] += 1
        cls._counters[f"investigations_blocked_{reason}"] += 1
        cls._tenant_counters[str(tenant_id)]["blocked"] += 1
        cls._tenant_counters[str(tenant_id)][f"blocked_{reason}"] += 1

    @classmethod
    def record_evidence_integrity_failure(cls, tenant_id: str, evidence_id: str) -> None:
        cls._counters["evidence_integrity_failures"] += 1
        cls._tenant_counters[str(tenant_id)]["integrity_failures"] += 1

    # Lease and Outbox Reliability Operational Metrics (Phase 5.1-D.1)
    @classmethod
    def record_lease_claimed(cls) -> None:
        cls._counters["investigation_leases_claimed"] += 1

    @classmethod
    def record_lease_reclaimed(cls) -> None:
        cls._counters["investigation_leases_reclaimed"] += 1

    @classmethod
    def record_lease_renewal_failed(cls) -> None:
        cls._counters["investigation_lease_renewal_failures"] += 1

    @classmethod
    def record_stale_write_rejected(cls) -> None:
        cls._counters["investigation_stale_writes_rejected"] += 1

    @classmethod
    def record_retries_exhausted(cls) -> None:
        cls._counters["investigation_retries_exhausted"] += 1

    @classmethod
    def record_outbox_published(cls, count: int = 1) -> None:
        cls._counters["outbox_events_published"] += count

    @classmethod
    def record_outbox_publish_failed(cls) -> None:
        cls._counters["outbox_events_publish_failed"] += 1

    @classmethod
    def get_redis_queue_depth(cls) -> Dict[str, Any]:
        """
        Inspects the active Redis task queue depth if Redis is accessible.
        """
        try:
            client = get_redis_client()
            if client and _task_queue:
                return {
                    "status": "CONNECTED",
                    "queue_name": _task_queue.name,
                    "depth": len(_task_queue),
                    "failed_queue_depth": _task_queue.failed_job_registry.count if hasattr(_task_queue, "failed_job_registry") else 0,
                }
        except Exception as e:
            return {"status": "UNAVAILABLE", "error": str(e), "depth": 0}
        return {"status": "STANDALONE_LOCAL", "depth": 0}

    @classmethod
    def get_tenant_metrics_summary(cls, tenant_id: str) -> Dict[str, Any]:
        """
        Returns an aggregated operational metrics snapshot strictly scoped to a specific tenant.
        """
        t_id = str(tenant_id)
        counters = cls._tenant_counters.get(t_id, {})
        latencies = cls._tenant_latencies.get(t_id, [])
        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
        max_latency = max(latencies) if latencies else 0.0

        return {
            "tenant_id": t_id,
            "investigations": {
                "started": counters.get("started", 0),
                "completed": counters.get("completed", 0),
                "failed": counters.get("failed", 0),
                "blocked": counters.get("blocked", 0),
                "integrity_failures": counters.get("integrity_failures", 0),
            },
            "performance": {
                "average_latency_ms": round(avg_latency, 2),
                "max_latency_ms": round(max_latency, 2),
                "total_investigations_timed": len(latencies),
            },
            "ai_consumption": {
                "total_tokens_consumed": cls._tenant_tokens.get(t_id, 0),
                "estimated_cost_usd": round(cls._tenant_costs_usd.get(t_id, 0.0), 6),
                "active_provider": settings.AI_PROVIDER,
                "configured_model": settings.AI_MODEL,
            },
            "worker_queue": cls.get_redis_queue_depth(),
        }

    @classmethod
    def get_metrics_summary(cls, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns an aggregated snapshot of operational forensic metrics.
        If tenant_id is provided, returns tenant-scoped metrics.
        """
        if tenant_id:
            return cls.get_tenant_metrics_summary(tenant_id)

        latencies = cls._latencies.get("execution_latency_ms", [])
        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
        max_latency = max(latencies) if latencies else 0.0

        return {
            "investigations": {
                "started": cls._counters.get("investigations_started", 0),
                "completed": cls._counters.get("investigations_completed", 0),
                "failed": cls._counters.get("investigations_failed", 0),
                "blocked": cls._counters.get("investigations_blocked", 0),
                "integrity_failures": cls._counters.get("evidence_integrity_failures", 0),
            },
            "performance": {
                "average_latency_ms": round(avg_latency, 2),
                "max_latency_ms": round(max_latency, 2),
                "total_investigations_timed": len(latencies),
            },
            "ai_consumption": {
                "total_tokens_consumed": cls._tokens.get("total_tokens_consumed", 0),
                "estimated_cost_usd": round(cls._costs_usd, 6),
                "active_provider": settings.AI_PROVIDER,
                "configured_model": settings.AI_MODEL,
            },
            "worker_queue": cls.get_redis_queue_depth(),
        }

    @classmethod
    def reset_metrics_for_testing(cls) -> None:
        cls._counters.clear()
        cls._latencies.clear()
        cls._tokens.clear()
        cls._costs_usd = 0.0
        cls._tenant_counters.clear()
        cls._tenant_latencies.clear()
        cls._tenant_tokens.clear()
        cls._tenant_costs_usd.clear()
