import time
import math
import shutil
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque

from app.core.config import settings


class MetricsCollector:
    """
    Centralized, thread-safe SRE metrics aggregator for Finora.
    Collects performance, availability, queue, AI latency, and storage metrics,
    exporting to both Prometheus exposition format and JSON SRE dashboards.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # 1. HTTP API Metrics
        self.http_requests_total: Dict[str, int] = defaultdict(int)
        self.http_requests_in_flight: int = 0
        self.http_durations_sec: deque = deque(maxlen=2000)  # rolling window for percentiles
        self.http_5xx_errors: int = 0
        self.http_4xx_errors: int = 0
        self.http_2xx_success: int = 0

        # 2. Database Metrics
        self.db_queries_total: int = 0
        self.db_query_errors_total: int = 0
        self.db_last_ping_ms: float = 0.0
        self.db_is_healthy: bool = True

        # 3. Redis & Queue Metrics
        self.redis_connected: bool = False
        self.redis_last_ping_ms: float = 0.0
        self.redis_errors_total: int = 0
        self.queue_depth: int = 0
        self.jobs_enqueued_total: int = 0
        self.jobs_completed_total: int = 0
        self.jobs_failed_total: int = 0
        self.jobs_retried_total: int = 0

        # 4. Gemini AI Metrics
        self.gemini_requests_total: int = 0
        self.gemini_requests_success: int = 0
        self.gemini_requests_failed: int = 0
        self.gemini_durations_sec: deque = deque(maxlen=500)
        self.gemini_errors_by_type: Dict[str, int] = defaultdict(int)

        # 5. Financial Ingestion & Reconciliation Metrics
        self.ingestion_batches_total: Dict[str, int] = defaultdict(int)
        self.ingestion_rows_total: int = 0
        self.ingestion_errors_total: int = 0
        self.reconciliation_runs_total: int = 0
        self.reconciliation_matches_total: int = 0
        self.reconciliation_leakages_total: Dict[str, int] = defaultdict(int)

    # --- HTTP API Tracking ---

    def record_http_request(self, method: str, path_template: str, status_code: int, duration_sec: float):
        with self._lock:
            key = f"{method}:{path_template}:{status_code}"
            self.http_requests_total[key] += 1
            self.http_durations_sec.append(duration_sec)

            if 200 <= status_code < 300:
                self.http_2xx_success += 1
            elif 400 <= status_code < 500:
                self.http_4xx_errors += 1
            elif status_code >= 500:
                self.http_5xx_errors += 1

    def inc_http_in_flight(self):
        with self._lock:
            self.http_requests_in_flight += 1

    def dec_http_in_flight(self):
        with self._lock:
            self.http_requests_in_flight = max(0, self.http_requests_in_flight - 1)

    # --- Database Tracking ---

    def record_db_probe(self, latency_ms: float, success: bool):
        with self._lock:
            self.db_queries_total += 1
            self.db_last_ping_ms = latency_ms
            self.db_is_healthy = success
            if not success:
                self.db_query_errors_total += 1

    # --- Redis & Background Queue Tracking ---

    def record_redis_probe(self, latency_ms: float, success: bool):
        with self._lock:
            self.redis_last_ping_ms = latency_ms
            self.redis_connected = success
            if not success:
                self.redis_errors_total += 1

    def update_queue_metrics(self, depth: int, failed_count: int = 0):
        with self._lock:
            self.queue_depth = depth
            if failed_count > self.jobs_failed_total:
                self.jobs_failed_total = failed_count

    def record_job_enqueued(self):
        with self._lock:
            self.jobs_enqueued_total += 1

    def record_job_completed(self):
        with self._lock:
            self.jobs_completed_total += 1

    def record_job_failed(self):
        with self._lock:
            self.jobs_failed_total += 1

    def record_job_retried(self):
        with self._lock:
            self.jobs_retried_total += 1

    # --- Gemini AI Tracking ---

    def record_gemini_call(self, duration_sec: float, success: bool, error_type: Optional[str] = None):
        with self._lock:
            self.gemini_requests_total += 1
            self.gemini_durations_sec.append(duration_sec)
            if success:
                self.gemini_requests_success += 1
            else:
                self.gemini_requests_failed += 1
                if error_type:
                    self.gemini_errors_by_type[error_type] += 1

    # --- Ingestion & Reconciliation Tracking ---

    def record_ingestion_batch(self, source_type: str, status: str, row_count: int = 0, error_count: int = 0):
        with self._lock:
            self.ingestion_batches_total[f"{source_type}:{status}"] += 1
            self.ingestion_rows_total += row_count
            self.ingestion_errors_total += error_count

    def record_reconciliation_run(self, matches_count: int, leakage_counts_by_type: Dict[str, int]):
        with self._lock:
            self.reconciliation_runs_total += 1
            self.reconciliation_matches_total += matches_count
            for l_type, count in leakage_counts_by_type.items():
                self.reconciliation_leakages_total[l_type] += count

    # --- Percentile Calculation Helpers ---

    @staticmethod
    def _calc_percentile(values: deque, percentile: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * percentile
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return float(sorted_vals[int(k)])
        d0 = sorted_vals[int(f)] * (c - k)
        d1 = sorted_vals[int(c)] * (k - f)
        return float(d0 + d1)

    # --- Storage Metrics ---

    @staticmethod
    def get_storage_stats() -> Dict[str, Any]:
        storage_path = Path(settings.STORAGE_DIR).resolve()
        storage_path.mkdir(parents=True, exist_ok=True)
        try:
            total, used, free = shutil.disk_usage(storage_path)
            pct = (used / total) * 100.0 if total > 0 else 0.0
        except Exception:
            total, used, free, pct = 0, 0, 0, 0.0

        file_count = 0
        try:
            for _ in storage_path.glob("**/*"):
                file_count += 1
        except Exception:
            pass

        return {
            "path": str(storage_path),
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "usage_percent": round(pct, 2),
            "file_count": file_count,
        }

    # --- Telemetry Snapshots ---

    def get_telemetry_snapshot(self) -> Dict[str, Any]:
        """Provides a comprehensive JSON monitoring snapshot."""
        with self._lock:
            total_reqs = sum(self.http_requests_total.values())
            availability_pct = (
                ((total_reqs - self.http_5xx_errors) / total_reqs * 100.0)
                if total_reqs > 0 else 100.0
            )
            p50_latency = self._calc_percentile(self.http_durations_sec, 0.50)
            p95_latency = self._calc_percentile(self.http_durations_sec, 0.95)
            p99_latency = self._calc_percentile(self.http_durations_sec, 0.99)

            gemini_p50 = self._calc_percentile(self.gemini_durations_sec, 0.50)
            gemini_p95 = self._calc_percentile(self.gemini_durations_sec, 0.95)

        storage = self.get_storage_stats()

        return {
            "timestamp": time.time(),
            "service": "Finora Financial Engine",
            "environment": settings.ENVIRONMENT,
            "api": {
                "total_requests": total_reqs,
                "in_flight_requests": self.http_requests_in_flight,
                "success_2xx": self.http_2xx_success,
                "client_error_4xx": self.http_4xx_errors,
                "server_error_5xx": self.http_5xx_errors,
                "availability_percent": round(availability_pct, 3),
                "latency_p50_ms": round(p50_latency * 1000, 2),
                "latency_p95_ms": round(p95_latency * 1000, 2),
                "latency_p99_ms": round(p99_latency * 1000, 2),
            },
            "database": {
                "healthy": self.db_is_healthy,
                "last_ping_latency_ms": round(self.db_last_ping_ms, 2),
                "total_queries_probed": self.db_queries_total,
                "query_errors": self.db_query_errors_total,
            },
            "redis": {
                "connected": self.redis_connected,
                "last_ping_latency_ms": round(self.redis_last_ping_ms, 2),
                "errors_total": self.redis_errors_total,
            },
            "background_queues": {
                "queue_name": "finora_reconciliation_tasks",
                "queue_depth": self.queue_depth,
                "jobs_enqueued": self.jobs_enqueued_total,
                "jobs_completed": self.jobs_completed_total,
                "jobs_failed": self.jobs_failed_total,
                "jobs_retried": self.jobs_retried_total,
            },
            "gemini_ai": {
                "model": settings.AI_MODEL,
                "total_calls": self.gemini_requests_total,
                "successful_calls": self.gemini_requests_success,
                "failed_calls": self.gemini_requests_failed,
                "latency_p50_ms": round(gemini_p50 * 1000, 2),
                "latency_p95_ms": round(gemini_p95 * 1000, 2),
                "error_breakdown": dict(self.gemini_errors_by_type),
            },
            "financial_engine": {
                "ingestion_batches": dict(self.ingestion_batches_total),
                "ingestion_rows_total": self.ingestion_rows_total,
                "ingestion_errors_total": self.ingestion_errors_total,
                "reconciliation_runs_total": self.reconciliation_runs_total,
                "reconciliation_matches_total": self.reconciliation_matches_total,
                "leakage_exceptions_detected": dict(self.reconciliation_leakages_total),
            },
            "storage": storage,
        }

    # --- Prometheus Exposition Output ---

    def generate_prometheus_text(self) -> str:
        """Generates standard Prometheus text exposition format."""
        snapshot = self.get_telemetry_snapshot()
        lines: List[str] = [
            "# HELP finora_http_requests_total Total number of HTTP requests processed",
            "# TYPE finora_http_requests_total counter",
        ]
        with self._lock:
            for k, count in self.http_requests_total.items():
                method, path, status = k.split(":", 2)
                lines.append(f'finora_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')

        lines.extend([
            f'finora_http_requests_in_flight {snapshot["api"]["in_flight_requests"]}',
            f'finora_http_availability_ratio {snapshot["api"]["availability_percent"] / 100.0}',
            f'finora_http_latency_seconds{{quantile="0.5"}} {snapshot["api"]["latency_p50_ms"] / 1000.0}',
            f'finora_http_latency_seconds{{quantile="0.95"}} {snapshot["api"]["latency_p95_ms"] / 1000.0}',
            f'finora_http_latency_seconds{{quantile="0.99"}} {snapshot["api"]["latency_p99_ms"] / 1000.0}',
            "# HELP finora_database_healthy Database connection status (1 = healthy, 0 = unhealthy)",
            "# TYPE finora_database_healthy gauge",
            f'finora_database_healthy {1 if snapshot["database"]["healthy"] else 0}',
            f'finora_database_ping_latency_ms {snapshot["database"]["last_ping_latency_ms"]}',
            "# HELP finora_redis_connected Redis queue connection status",
            "# TYPE finora_redis_connected gauge",
            f'finora_redis_connected {1 if snapshot["redis"]["connected"] else 0}',
            f'finora_redis_ping_latency_ms {snapshot["redis"]["last_ping_latency_ms"]}',
            "# HELP finora_queue_depth Pending background job queue depth",
            "# TYPE finora_queue_depth gauge",
            f'finora_queue_depth{{queue="finora_reconciliation_tasks"}} {snapshot["background_queues"]["queue_depth"]}',
            f'finora_queue_jobs_failed_total {snapshot["background_queues"]["jobs_failed"]}',
            f'finora_queue_jobs_retried_total {snapshot["background_queues"]["jobs_retried"]}',
            "# HELP finora_gemini_requests_total Calls to Google Gemini AI API",
            "# TYPE finora_gemini_requests_total counter",
            f'finora_gemini_requests_total{{status="success"}} {snapshot["gemini_ai"]["successful_calls"]}',
            f'finora_gemini_requests_total{{status="failed"}} {snapshot["gemini_ai"]["failed_calls"]}',
            f'finora_gemini_latency_seconds{{quantile="0.95"}} {snapshot["gemini_ai"]["latency_p95_ms"] / 1000.0}',
            "# HELP finora_storage_usage_ratio File storage volume usage ratio",
            "# TYPE finora_storage_usage_ratio gauge",
            f'finora_storage_usage_ratio {snapshot["storage"]["usage_percent"] / 100.0}',
            f'finora_storage_used_bytes {snapshot["storage"]["used_bytes"]}',
        ])
        return "\n".join(lines) + "\n"


# Global singleton metrics collector
metrics_collector = MetricsCollector()
