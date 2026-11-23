import time
import logging
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger("finora.alerts")


class AlertSeverity(str, Enum):
    SEV1_CRITICAL = "SEV-1_CRITICAL"   # PagerDuty on-call, SLA <= 15m (Outage, DB Down, Invariant Breach)
    SEV2_HIGH = "SEV-2_HIGH"           # Immediate Slack escalation, SLA <= 30m (Backlog, p95 > 2s, Disk > 85%)
    SEV3_MEDIUM = "SEV-3_MEDIUM"       # Ticket, SLA <= 4h (Gemini 429 rate limit, 4xx spike)
    SEV4_LOW = "SEV-4_LOW"             # Daily review (Retention sweeps, warnings)


class AlertStatus(str, Enum):
    FIRING = "FIRING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class AlertEvent(BaseModel):
    alert_id: str
    rule_name: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.FIRING
    summary: str
    description: str
    component: str
    value: float
    threshold: float
    timestamp: float = Field(default_factory=time.time)
    response_procedure: str


class AlertEngine:
    """
    Evaluates system metrics against SRE thresholds and dispatches
    tiered operational alerts with standard operating procedures (SOPs).
    """

    def __init__(self):
        self._active_alerts: Dict[str, AlertEvent] = {}
        self._alert_history: List[AlertEvent] = []

    def get_active_alerts(self) -> List[AlertEvent]:
        return list(self._active_alerts.values())

    def get_alert_history(self) -> List[AlertEvent]:
        return list(self._alert_history)

    def trigger_alert(
        self,
        rule_name: str,
        severity: AlertSeverity,
        summary: str,
        description: str,
        component: str,
        value: float,
        threshold: float,
        response_procedure: str,
    ) -> AlertEvent:
        """Triggers or updates an active alert."""
        alert_id = f"{rule_name}:{component}"
        event = AlertEvent(
            alert_id=alert_id,
            rule_name=rule_name,
            severity=severity,
            status=AlertStatus.FIRING,
            summary=summary,
            description=description,
            component=component,
            value=value,
            threshold=threshold,
            response_procedure=response_procedure,
        )
        self._active_alerts[alert_id] = event
        self._alert_history.append(event)

        logger.critical(
            "[%s] OPERATIONAL ALERT: %s - %s (Val: %s, Threshold: %s) -> SOP: %s",
            severity.value, rule_name, summary, value, threshold, response_procedure
        )
        return event

    def resolve_alert(self, alert_id: str) -> Optional[AlertEvent]:
        if alert_id in self._active_alerts:
            alert = self._active_alerts.pop(alert_id)
            alert.status = AlertStatus.RESOLVED
            self._alert_history.append(alert)
            logger.info("RESOLVED operational alert: %s", alert_id)
            return alert
        return None

    def clear_all_alerts(self):
        self._active_alerts.clear()

    def evaluate_telemetry(self, telemetry: Dict[str, Any]) -> List[AlertEvent]:
        """
        Evaluates current snapshot against operational thresholds
        and fires alerts for any violated health invariants.
        """
        fired: List[AlertEvent] = []

        # Rule 1: Database Outage (SEV-1)
        db = telemetry.get("database", {})
        if not db.get("healthy", True):
            fired.append(self.trigger_alert(
                rule_name="DatabaseConnectionFailure",
                severity=AlertSeverity.SEV1_CRITICAL,
                summary="PostgreSQL database unreachable or query failed",
                description="Engine health probe failed to execute SELECT 1 against PostgreSQL.",
                component="database",
                value=0.0,
                threshold=1.0,
                response_procedure="Check PostgreSQL service status, database connection limits, and network routing immediately."
            ))

        # Rule 2: Redis Outage (SEV-1 in production)
        redis = telemetry.get("redis", {})
        if not redis.get("connected", True) and settings.ENVIRONMENT == "production":
            fired.append(self.trigger_alert(
                rule_name="RedisBrokerFailure",
                severity=AlertSeverity.SEV1_CRITICAL,
                summary="Redis task queue connection severed",
                description="Unable to connect or ping Redis broker. Asynchronous reconciliation tasks are blocked.",
                component="redis",
                value=0.0,
                threshold=1.0,
                response_procedure="Verify Redis container health, verify password authentication and host networking."
            ))

        # Rule 3: High HTTP 5xx Server Error Rate (SEV-1)
        api = telemetry.get("api", {})
        total_reqs = api.get("total_requests", 0)
        err_5xx = api.get("server_error_5xx", 0)
        if total_reqs >= 20:
            rate_5xx = (err_5xx / total_reqs) * 100.0
            if rate_5xx > 5.0:
                fired.append(self.trigger_alert(
                    rule_name="HighHttp5xxErrorRate",
                    severity=AlertSeverity.SEV1_CRITICAL,
                    summary=f"HTTP 5xx error rate is {rate_5xx:.2f}% (exceeds 5% threshold)",
                    description="Excessive server errors detected on backend API endpoints.",
                    component="api",
                    value=rate_5xx,
                    threshold=5.0,
                    response_procedure="Inspect application error logs for unhandled exceptions, database deadlock, or OOM crashes."
                ))

        # Rule 4: High Background Queue Backlog (SEV-2)
        queues = telemetry.get("background_queues", {})
        q_depth = queues.get("queue_depth", 0)
        if q_depth > 100:
            fired.append(self.trigger_alert(
                rule_name="QueueBacklogExceeded",
                severity=AlertSeverity.SEV2_HIGH,
                summary=f"Task queue depth is {q_depth} (exceeds 100 job threshold)",
                description="Background workers are lagging behind ingestion or reconciliation job submissions.",
                component="worker_queue",
                value=float(q_depth),
                threshold=100.0,
                response_procedure="Scale out worker instances: `docker compose up --scale worker=4 -d`."
            ))

        # Rule 5: High Job Failure Count (SEV-2)
        failed_jobs = queues.get("jobs_failed", 0)
        if failed_jobs >= 10:
            fired.append(self.trigger_alert(
                rule_name="ExcessiveBackgroundJobFailures",
                severity=AlertSeverity.SEV2_HIGH,
                summary=f"Failed background jobs count reached {failed_jobs}",
                description="Multiple reconciliation or ingestion background jobs terminated abnormally.",
                component="workers",
                value=float(failed_jobs),
                threshold=10.0,
                response_procedure="Inspect RQ FailedJobRegistry, verify database constraints, and inspect worker logs."
            ))

        # Rule 6: High Storage Utilization (SEV-2)
        storage = telemetry.get("storage", {})
        usage_pct = storage.get("usage_percent", 0.0)
        if usage_pct > 85.0:
            fired.append(self.trigger_alert(
                rule_name="StorageDiskCapacityHigh",
                severity=AlertSeverity.SEV2_HIGH,
                summary=f"Private file storage utilization is {usage_pct}% (exceeds 85% threshold)",
                description="Financial document storage volume is nearing maximum capacity.",
                component="storage",
                value=usage_pct,
                threshold=85.0,
                response_procedure="Expand private volume partition or trigger statutory retention purge."
            ))

        # Rule 7: High API Latency p95 (SEV-2)
        p95_ms = api.get("latency_p95_ms", 0.0)
        if total_reqs >= 20 and p95_ms > 2000.0:
            fired.append(self.trigger_alert(
                rule_name="HighApiLatencyP95",
                severity=AlertSeverity.SEV2_HIGH,
                summary=f"API p95 latency is {p95_ms:.1f}ms (exceeds 2000ms threshold)",
                description="Slow response times observed on core API endpoints.",
                component="api",
                value=p95_ms,
                threshold=2000.0,
                response_procedure="Check database connection pool contention, slow queries, and knapsack solver bounds."
            ))

        # Rule 8: Gemini AI Rate Limits (SEV-3)
        gemini = telemetry.get("gemini_ai", {})
        rate_limits = gemini.get("error_breakdown", {}).get("rate_limit", 0)
        if rate_limits >= 5:
            fired.append(self.trigger_alert(
                rule_name="GeminiRateLimitExceeded",
                severity=AlertSeverity.SEV3_MEDIUM,
                summary=f"Gemini API 429 rate limit errors ({rate_limits}) detected",
                description="Google Gemini quota or concurrency limits are being reached.",
                component="gemini_ai",
                value=float(rate_limits),
                threshold=5.0,
                response_procedure="Implement exponential backoff in worker jobs or request Google Cloud quota increase."
            ))

        return fired


# Global singleton alert engine
alert_engine = AlertEngine()
