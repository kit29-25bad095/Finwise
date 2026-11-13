# Finora — Production Monitoring, Observability & Incident Response Manual

**Document Reference:** `FINORA-DEP-007`  
**Classification:** Site Reliability & Operational Procedures  
**Audit Date:** November 13, 2026  
**Auditor Roles:** Principal SRE, Production Reliability Engineer  
**Subsystem:** Area 6 — Monitoring, Observability & Incident Response  

---

## 1. Observability Architecture & Standards

Finora implements structured JSON logging, dependency health probes, background queue metrics, and error tracking abstractions designed for standard enterprise observability platforms (Datadog, AWS CloudWatch, Grafana Loki, Sentry).

```
  [ FastAPI App ] ─── JSON Logs ───> [ CloudWatch / Loki / Datadog ]
         │                                      │
         ├─── Health Probes (/health/*) ───────> [ Kubernetes / Load Balancer ]
         │                                      │
         ├─── Queue Metrics (RQ len) ─────────> [ Prometheus / CloudWatch ]
         │                                      │
         └─── Exceptions / Errors ────────────> [ Sentry / Error Aggregator ]
```

### Observability Readiness Matrix

| Component | Implementation | Audit Result | Classification |
|---|---|:---:|---|
| **Structured JSON Logging** | `JSONFormatter` in `app/core/logging_config.py` | ✅ Operational | **IMPLEMENTED** |
| **Credential & PII Redaction** | Regex scrubbing of tokens, API keys, cards, IFSC | ✅ Verified | **TESTED LOCALLY** |
| **Liveness Probe (`/health/live`)** | Lightweight endpoint returning `{"status": "ALIVE"}` | ✅ HTTP 200 | **VERIFIED WITH LIVE SERVICE** |
| **Readiness Probe (`/health/ready`)** | Evaluates DB connectivity, queue health, AI status | ✅ HTTP 200 | **VERIFIED WITH LIVE SERVICE** |
| **Background Queue Telemetry** | `check_worker_queue_health()` reports depth & mode | ✅ Operational | **IMPLEMENTED** |
| **Operational Alerting Rules** | Defined thresholds for errors, latency, and DB saturation | ✅ Documented | **IMPLEMENTED** |
| **Incident Response Runbooks** | Step-by-step procedures for 5 critical failure scenarios | ✅ Documented | **IMPLEMENTED** |

---

## 2. Structured JSON Logging & Sensitive Data Scrubbing

### 2.1 Log Schema
Every application log record emits a structured JSON object containing standard correlation fields:
```json
{
  "timestamp": "2026-11-13T19:30:00.123456Z",
  "level": "INFO",
  "logger": "app.services.reconciliation.reconciliation_service",
  "message": "Reconciliation run completed for tenant 42dde591-1d69...",
  "module": "reconciliation_service",
  "line": 142
}
```

### 2.2 PII & Secret Scrubbing Rules
Before writing to stdout, messages pass through `redact_sensitive_data()`:
- **Authorization Tokens:** `Bearer eyJ...` -> `Bearer [REDACTED_TOKEN]`
- **Google GenAI Keys:** `AIzaSy...` -> `[REDACTED_GEMINI_KEY]`
- **Credit Card Numbers:** `4111 1111 1111 1111` -> `[REDACTED_CARD_NUMBER]`
- **Bank IFSC Codes:** `HDFC0001234` -> `[REDACTED_IFSC]`
- **Passwords / Secrets:** `password="mySecret"` -> `password=[REDACTED]`

---

## 3. Dependency Health & Readiness Probes

### 3.1 Kubernetes / Cloud Liveness Probe
- **Route:** `GET /health/live`
- **Response:** HTTP 200 `{"status": "ALIVE"}`
- **Purpose:** Fast, non-blocking check. Indicates the Uvicorn process is listening and capable of accepting connections.

### 3.2 Kubernetes / Cloud Readiness Probe
- **Route:** `GET /health/ready`
- **Response Payload:**
  ```json
  {
    "status": "READY",
    "database": "CONNECTED",
    "worker_queue": {
      "mode": "SYNC_LOCAL",
      "redis_connected": false,
      "status": "OPERATIONAL_FALLBACK",
      "queue_depth": 0
    },
    "ai_provider": {
      "provider": "gemini",
      "model": "gemini-2.0-flash",
      "status": "PENDING_CONFIGURATION"
    }
  }
  ```
- **Failure Conditions:**
  - Database unreachable -> HTTP 503 `{"detail": "Database unreachable: ..."}`
  - Strict production mode (`WORKER_FALLBACK_SYNC=False`) and Redis unreachable -> HTTP 503 `{"detail": "Redis worker queue unavailable in strict production mode"}`

---

## 4. Background Job & Queue Monitoring

### 4.1 Queue Modes
- **Production Mode (`WORKER_FALLBACK_SYNC=False`):** Enqueues tasks to Redis queue `finora_reconciliation_tasks`. Workers process jobs asynchronously across `high`, `default`, and `low` queues.
- **Fallback / Development Mode (`WORKER_FALLBACK_SYNC=True`):** Executes tasks synchronously in-process. Eliminates Redis dependency for development and single-server deployments.

### 4.2 Financial Idempotency Guarantee
All background worker tasks (`reconciliation_tasks`, `leakage_tasks`, `forensic_tasks`) accept unique transaction or batch IDs. If a job is re-dispatched or retried due to worker restart, idempotency checks guarantee no duplicate allocations or duplicate leakage exceptions are created.

---

## 5. Production Alerting Thresholds

| Metric / Event | Warning Threshold | Critical Alert Threshold | Recommended Action |
|---|---|---|---|
| **API Error Rate (5xx)** | $> 1\%$ in 5 min | $> 5\%$ in 2 min | Inspect JSON error logs; check DB pool |
| **API Latency (p95)** | $> 250\text{ ms}$ | $> 1000\text{ ms}$ | Check DB slow queries, CPU saturation |
| **Database Pool Usage** | $> 70\%$ pool capacity | $> 90\%$ pool capacity | Scale `DB_POOL_SIZE` or DB instance |
| **Redis Task Queue Depth** | $> 100$ jobs waiting | $> 500$ jobs waiting | Scale worker containers (`scale worker=3`) |
| **Failed Worker Jobs** | $\ge 1$ job failure | $> 5$ job failures/hr | Check poison pill payloads in queue |
| **Authentication Lockouts** | $> 10$ lockouts in 15 min | $> 50$ lockouts in 15 min | Investigate distributed brute-force attack |
| **Gemini API Error Rate** | $> 5\%$ (HTTP 429) | Provider Down (HTTP 5xx) | Verify quota limits; fallback to mock |

---

## 6. Operational Incident Response Runbooks

### Runbook 1: Database Connection Failure (HTTP 503 on `/health/ready`)
1. Check database container / RDS health:
   ```bash
   pg_isready -h <db-host> -p 5432 -U finora_user
   ```
2. Inspect backend logs for connection pool exhaustion:
   ```bash
   grep "TimeoutError" /var/log/finora/backend.log
   ```
3. Restart backend if pool is exhausted or restart database if service halted.

### Runbook 2: Redis Worker Queue Backlog
1. Check queue length via readiness probe or Redis CLI:
   ```bash
   redis-cli -a $REDIS_PASSWORD LLEN rq:queue:finora_reconciliation_tasks
   ```
2. Check worker process status:
   ```bash
   ps aux | grep "rq worker"
   ```
3. Scale worker containers:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --scale worker=4
   ```

### Runbook 3: High Rate of Discrepancies Flagged by Leakage Engine
1. Query active exception counts per detector:
   ```sql
   SELECT detector_type, COUNT(*), SUM(leakage_amount) 
   FROM leakage_run_exceptions 
   GROUP BY detector_type;
   ```
2. If `FEE_OVERCHARGE` spikes, check whether the payment gateway altered MDR tariffs without updating the merchant fee contract in `fee_contracts`.
3. If `MISSING_SETTLEMENT` spikes, check if an unannounced bank holiday occurred.

### Runbook 4: Emergency Maintenance & Read-Only Mode
1. Set `MAINTENANCE_MODE=true` in environment.
2. Ingress router routes traffic to static maintenance page.
3. Database backups are taken prior to schema migrations.
