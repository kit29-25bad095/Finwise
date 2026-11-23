import time
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, status, Response, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_db_session
from app.core.monitoring.metrics import metrics_collector
from app.core.monitoring.alerts import alert_engine, AlertSeverity, AlertEvent

router = APIRouter(tags=["Observability & SRE Monitoring"])


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics exposition endpoint"
)
@router.get(
    "/api/v1/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics exposition endpoint (v1 prefix)"
)
def prometheus_metrics():
    """Exposes all collected application, database, queue, and AI metrics in Prometheus format."""
    return Response(
        content=metrics_collector.generate_prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )


@router.get(
    "/api/v1/monitoring/metrics",
    summary="JSON SRE telemetry snapshot for operational dashboards"
)
def json_telemetry_metrics(db: Session = Depends(get_db_session)):
    """Returns detailed real-time performance, availability, queue, and storage metrics."""
    # Probe database latency
    start = time.perf_counter()
    db_success = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_success = False
    db_latency_ms = (time.perf_counter() - start) * 1000.0
    metrics_collector.record_db_probe(db_latency_ms, db_success)

    # Probe Redis connectivity and queue depth
    try:
        from app.workers.queue import get_redis_client
        client = get_redis_client()
        if client:
            r_start = time.perf_counter()
            client.ping()
            r_latency_ms = (time.perf_counter() - r_start) * 1000.0
            metrics_collector.record_redis_probe(r_latency_ms, True)

            # Update queue depth from Redis
            from rq import Queue
            from rq.registry import FailedJobRegistry
            q = Queue("finora_reconciliation_tasks", connection=client)
            failed_reg = FailedJobRegistry(queue=q)
            metrics_collector.update_queue_metrics(
                depth=len(q),
                failed_count=len(failed_reg)
            )
        elif settings.ENVIRONMENT == "test":
            metrics_collector.record_redis_probe(0.0, True)
        else:
            metrics_collector.record_redis_probe(0.0, False)
    except Exception:
        metrics_collector.record_redis_probe(0.0, False)

    snapshot = metrics_collector.get_telemetry_snapshot()
    # Evaluate alerts
    alert_engine.evaluate_telemetry(snapshot)
    return snapshot


@router.get(
    "/api/v1/monitoring/alerts",
    summary="Active operational alerts list"
)
def get_active_alerts():
    """Lists currently firing operational alerts with assigned severities and SOPs."""
    active = alert_engine.get_active_alerts()
    return {
        "firing_count": len(active),
        "alerts": active
    }


@router.post(
    "/api/v1/monitoring/alerts/evaluate",
    summary="Trigger immediate alert rule evaluation"
)
def evaluate_alerts(db: Session = Depends(get_db_session)):
    """Evaluates telemetry immediately against SRE thresholds and returns fired alerts."""
    snapshot = json_telemetry_metrics(db)
    fired = alert_engine.evaluate_telemetry(snapshot)
    return {
        "evaluated_timestamp": time.time(),
        "newly_fired_count": len(fired),
        "active_alerts_total": len(alert_engine.get_active_alerts()),
        "alerts": fired
    }


@router.post(
    "/api/v1/monitoring/alerts/test",
    summary="Simulate SRE operational alert for runbook verification"
)
def simulate_test_alert(severity: str = "SEV-1_CRITICAL", rule_name: str = "SimulatedAlertTest"):
    """Allows SREs to verify alert dispatching, notification channels, and runbooks."""
    try:
        sev_enum = AlertSeverity(severity)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid severity '{severity}'. Choose from: {[s.value for s in AlertSeverity]}"
        )

    alert = alert_engine.trigger_alert(
        rule_name=rule_name,
        severity=sev_enum,
        summary=f"SRE Verification Test Alert: {rule_name}",
        description="This is an automated simulation to verify alert triggering and runbook procedures.",
        component="monitoring_test",
        value=1.0,
        threshold=0.0,
        response_procedure="SRE verification test successful. No action required."
    )
    return {
        "status": "ALERT_TRIGGERED",
        "alert": alert
    }
