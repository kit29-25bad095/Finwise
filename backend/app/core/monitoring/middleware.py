import time
import uuid
import logging
from typing import Callable
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.monitoring.logging import SensitiveDataRedactor
from app.core.monitoring.metrics import metrics_collector
from app.core.monitoring.alerts import alert_engine, AlertSeverity

logger = logging.getLogger("finora.http")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    SRE Middleware:
    - Injects and propagates X-Correlation-ID headers for distributed tracing.
    - Measures high-resolution request latency.
    - Records API metrics to the centralized collector.
    - Emits structured, redacted access logs.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Traceability: Extract or generate correlation ID
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        # Normalize path template to avoid high-cardinality metric explosion
        path = request.url.path
        method = request.method

        start_time = time.perf_counter()
        metrics_collector.inc_http_in_flight()

        try:
            response = await call_next(request)
            duration_sec = time.perf_counter() - start_time
            status_code = response.status_code

            # Record metrics
            metrics_collector.record_http_request(
                method=method,
                path_template=self._normalize_path(path),
                status_code=status_code,
                duration_sec=duration_sec,
            )

            # Structured logging
            logger.info(
                "%s %s -> HTTP %d (%.2fms)",
                method, path, status_code, duration_sec * 1000.0,
                extra={"correlation_id": correlation_id}
            )

            # Propagate correlation ID header
            response.headers["X-Correlation-ID"] = correlation_id
            return response

        except Exception as exc:
            duration_sec = time.perf_counter() - start_time
            metrics_collector.record_http_request(
                method=method,
                path_template=self._normalize_path(path),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                duration_sec=duration_sec,
            )

            # Sanitize error message and trace
            safe_err = SensitiveDataRedactor.redact(str(exc))
            error_id = str(uuid.uuid4())

            logger.exception(
                "Unhandled exception on %s %s [Error ID: %s, Correlation ID: %s]: %s",
                method, path, error_id, correlation_id, safe_err,
                extra={"correlation_id": correlation_id}
            )

            # Trigger operational alert if severe
            alert_engine.trigger_alert(
                rule_name="UnhandledApiException",
                severity=AlertSeverity.SEV2_HIGH,
                summary=f"Unhandled exception on {method} {path}",
                description=f"Error ID: {error_id}. Exception: {safe_err}",
                component="api",
                value=1.0,
                threshold=0.0,
                response_procedure="Inspect structured logs using Error ID and check recent code changes or input anomalies."
            )

            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error_id": error_id,
                    "correlation_id": correlation_id,
                    "detail": "An internal server error occurred. Please quote the Error ID when contacting technical support.",
                    "status_code": 500,
                },
                headers={"X-Correlation-ID": correlation_id}
            )
        finally:
            metrics_collector.dec_http_in_flight()

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Groups dynamic UUIDs and IDs to prevent Prometheus metric explosion."""
        segments = path.strip("/").split("/")
        normalized = []
        for seg in segments:
            # Check if segment looks like a UUID or numeric ID
            if len(seg) >= 32 or seg.isdigit() or (len(seg) == 36 and "-" in seg):
                normalized.append("{id}")
            else:
                normalized.append(seg)
        return "/" + "/".join(normalized)
