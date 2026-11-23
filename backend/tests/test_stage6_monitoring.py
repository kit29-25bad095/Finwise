import json
import logging
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.main import app
from app.core.monitoring.logging import SensitiveDataRedactor, StructuredJsonFormatter
from app.core.monitoring.metrics import metrics_collector
from app.core.monitoring.alerts import alert_engine, AlertSeverity, AlertStatus

client = TestClient(app)


# ==============================================================================
# 1. Sensitive Data Redaction & Privacy Guardrails
# ==============================================================================

def test_01_redactor_scrubs_api_keys_and_bearer_tokens():
    """Verify that Google GenAI API keys and bearer tokens are strictly scrubbed."""
    raw_log = "Error using key AIzaSyD3xAmPlE1234567890-_abcdefghijk or Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token"
    redacted = SensitiveDataRedactor.redact(raw_log)
    assert "AIzaSy" not in redacted
    assert "[REDACTED_API_KEY]" in redacted
    assert "[REDACTED_BEARER_TOKEN]" in redacted


def test_02_redactor_scrubs_passwords_and_credentials():
    """Verify that credentials and connection strings are masked."""
    raw_log = "Connecting with postgres_password='supersecretpass' and secret_key='anothersecret123'"
    redacted = SensitiveDataRedactor.redact(raw_log)
    assert "supersecretpass" not in redacted
    assert "anothersecret123" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_03_redactor_scrubs_bank_account_numbers():
    """Verify that Indian bank account numbers are redacted."""
    raw_log = "Settlement payout to bank_account=50100234567891 and account_number: 98765432101234"
    redacted = SensitiveDataRedactor.redact(raw_log)
    assert "50100234567891" not in redacted
    assert "98765432101234" not in redacted
    assert "[REDACTED_BANK_ACCOUNT]" in redacted


def test_04_redactor_scrubs_customer_pii():
    """Verify that customer emails and Indian mobile numbers are redacted."""
    raw_log = "Customer contact: priya.sharma@merchant.in with phone +91 9876543210 placed order"
    redacted = SensitiveDataRedactor.redact(raw_log)
    assert "priya.sharma@merchant.in" not in redacted
    assert "9876543210" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_05_redactor_scrubs_confidential_csv_contents():
    """Verify that multi-line financial CSV contents are replaced with redacted placeholder."""
    csv_dump = """Shopify,Order,Amount
#1001,4999.00
#1002,1250.00"""
    raw_log = f"Failed while parsing raw document:\n{csv_dump}\nProcessing stopped."
    redacted = SensitiveDataRedactor.redact(raw_log)
    assert "4999.00" not in redacted
    assert "[REDACTED_CONFIDENTIAL_CSV_DATA]" in redacted


# ==============================================================================
# 2. Structured JSON Logging Formatter
# ==============================================================================

def test_06_structured_json_formatter():
    """Verify JSON formatter outputs compliant JSON records with standard attributes."""
    formatter = StructuredJsonFormatter(service_name="finora-test", environment="test")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Processing settlement for account_no=12345678901234",
        args=(),
        exc_info=None
    )
    record.correlation_id = "test-corr-uuid-123"

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "INFO"
    assert parsed["service"] == "finora-test"
    assert parsed["environment"] == "test"
    assert parsed["correlation_id"] == "test-corr-uuid-123"
    assert "12345678901234" not in parsed["message"]
    assert "[REDACTED_BANK_ACCOUNT]" in parsed["message"]


# ==============================================================================
# 3. Observability Middleware, Latency & Error Shielding
# ==============================================================================

def test_07_correlation_id_injection_and_propagation():
    """Verify that requests receive and propagate X-Correlation-ID headers."""
    # Test auto-generation
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert "X-Correlation-ID" in resp.headers
    gen_id = resp.headers["X-Correlation-ID"]
    assert len(gen_id) >= 16

    # Test propagation of client-provided correlation ID
    custom_id = "custom-client-trace-999"
    resp2 = client.get("/health/live", headers={"X-Correlation-ID": custom_id})
    assert resp2.headers["X-Correlation-ID"] == custom_id


def test_08_middleware_error_shielding_and_sanitization():
    """Verify that unhandled server exceptions return sanitized error IDs and hide internals."""
    @app.get("/test-unhandled-crash-simulation")
    def crash_endpoint():
        # Simulate fatal crash containing database password in exception text
        raise RuntimeError("Database connection password='secret_db_pass' failed unexpectedly")

    resp = client.get("/test-unhandled-crash-simulation")
    assert resp.status_code == 500
    data = resp.json()

    assert "error_id" in data
    assert "correlation_id" in data
    assert "secret_db_pass" not in str(data)  # Crucial security assertion
    assert "internal server error" in data["detail"].lower()


# ==============================================================================
# 4. Metrics Collection & Prometheus Exposition
# ==============================================================================

def test_09_prometheus_metrics_exposition_endpoint():
    """Verify GET /metrics returns standard Prometheus text format."""
    # Generate some traffic first
    client.get("/health/live")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    content = resp.text

    assert "finora_http_requests_total" in content
    assert "finora_database_healthy" in content
    assert "finora_queue_depth" in content
    assert "finora_storage_usage_ratio" in content


def test_10_json_telemetry_snapshot_endpoint():
    """Verify GET /api/v1/monitoring/metrics returns complete structured telemetry."""
    resp = client.get("/api/v1/monitoring/metrics")
    assert resp.status_code == 200
    data = resp.json()

    assert "api" in data
    assert "database" in data
    assert "redis" in data
    assert "background_queues" in data
    assert "gemini_ai" in data
    assert "financial_engine" in data
    assert "storage" in data

    assert data["api"]["availability_percent"] >= 0.0
    assert "usage_percent" in data["storage"]


# ==============================================================================
# 5. Operational Alert Engine & Threshold Triggering
# ==============================================================================

def test_11_alert_triggering_on_database_down():
    """Verify SEV-1 CRITICAL alert fires when database probe fails."""
    alert_engine.clear_all_alerts()
    telemetry = {
        "database": {"healthy": False, "query_errors": 5},
        "redis": {"connected": True},
        "api": {"total_requests": 50, "server_error_5xx": 0},
    }

    fired = alert_engine.evaluate_telemetry(telemetry)
    assert any(a.rule_name == "DatabaseConnectionFailure" for a in fired)
    assert any(a.severity == AlertSeverity.SEV1_CRITICAL for a in fired)


def test_12_alert_triggering_on_high_5xx_rate():
    """Verify SEV-1 CRITICAL alert fires when 5xx error rate exceeds 5%."""
    alert_engine.clear_all_alerts()
    telemetry = {
        "database": {"healthy": True},
        "redis": {"connected": True},
        "api": {
            "total_requests": 100,
            "server_error_5xx": 12,  # 12% > 5%
        },
    }

    fired = alert_engine.evaluate_telemetry(telemetry)
    assert any(a.rule_name == "HighHttp5xxErrorRate" for a in fired)
    assert any(a.severity == AlertSeverity.SEV1_CRITICAL for a in fired)


def test_13_alert_triggering_on_high_queue_backlog():
    """Verify SEV-2 HIGH alert fires when task queue exceeds 100 jobs."""
    alert_engine.clear_all_alerts()
    telemetry = {
        "database": {"healthy": True},
        "redis": {"connected": True},
        "background_queues": {"queue_depth": 150, "jobs_failed": 0},
        "api": {"total_requests": 10},
    }

    fired = alert_engine.evaluate_telemetry(telemetry)
    assert any(a.rule_name == "QueueBacklogExceeded" for a in fired)
    assert any(a.severity == AlertSeverity.SEV2_HIGH for a in fired)


def test_14_alert_triggering_on_high_storage_capacity():
    """Verify SEV-2 HIGH alert fires when storage exceeds 85% capacity."""
    alert_engine.clear_all_alerts()
    telemetry = {
        "database": {"healthy": True},
        "redis": {"connected": True},
        "storage": {"usage_percent": 89.5},
        "api": {"total_requests": 10},
    }

    fired = alert_engine.evaluate_telemetry(telemetry)
    assert any(a.rule_name == "StorageDiskCapacityHigh" for a in fired)
    assert any(a.severity == AlertSeverity.SEV2_HIGH for a in fired)


def test_15_alert_triggering_on_gemini_rate_limits():
    """Verify SEV-3 MEDIUM alert fires on Gemini 429 rate limit errors."""
    alert_engine.clear_all_alerts()
    telemetry = {
        "database": {"healthy": True},
        "redis": {"connected": True},
        "gemini_ai": {"error_breakdown": {"rate_limit": 8}},
        "api": {"total_requests": 10},
    }

    fired = alert_engine.evaluate_telemetry(telemetry)
    assert any(a.rule_name == "GeminiRateLimitExceeded" for a in fired)
    assert any(a.severity == AlertSeverity.SEV3_MEDIUM for a in fired)


def test_16_simulate_test_alert_endpoint():
    """Verify SRE test alert endpoint triggers simulated alerts."""
    resp = client.post(
        "/api/v1/monitoring/alerts/test?severity=SEV-1_CRITICAL&rule_name=SRE_Disaster_Recovery_Drill"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ALERT_TRIGGERED"
    assert data["alert"]["rule_name"] == "SRE_Disaster_Recovery_Drill"

    # Verify present in active alerts list
    active_resp = client.get("/api/v1/monitoring/alerts")
    assert active_resp.status_code == 200
    alerts_data = active_resp.json()
    assert alerts_data["firing_count"] >= 1
    assert any(a["rule_name"] == "SRE_Disaster_Recovery_Drill" for a in alerts_data["alerts"])
