# Finora Production Rollback and Disaster Recovery Plan

**Document ID**: PR-REP-010  
**Version**: 1.0.0  
**Classification**: Enterprise Operational Continuity Plan  
**System**: Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine  
**Target Environment**: AWS / GCP Managed Production Stacks  

---

## 1. Executive Summary & Objectives

The Finora Production Rollback and Disaster Recovery Plan defines the protocols, automated procedures, and technical runbooks required to reverse failed deployments, restore database state, and recover operational services in the event of software regression, data corruption, or infrastructure failure.

### 1.1 Recovery Metrics (SLA / SLO)

| Metric | Target | Description |
| :--- | :--- | :--- |
| **RTO (Recovery Time Objective)** | **< 15 minutes** | Maximum allowable downtime during an application deployment rollback. |
| **RTO (Disaster Database Recovery)**| **< 60 minutes** | Maximum allowable time to restore a full database cluster from cold/warm backup. |
| **RPO (Recovery Point Objective)**| **< 5 minutes** | Maximum acceptable data loss window during a catastrophic failover (achieved via WAL / point-in-time recovery). |

---

## 2. Incident Classification & Rollback Triggers

An emergency rollback or recovery sequence must be initiated immediately upon detecting any of the following critical triggers:

| Trigger Code | Severity | Description | Action Required |
| :--- | :--- | :--- | :--- |
| **TRG-01** | Critical | **Elevated Error Rate**: HTTP 5xx responses exceed 1.0% of total traffic for $> 3$ consecutive minutes. | Immediate Application Rollback |
| **TRG-02** | Critical | **Financial Invariant Violation**: Settlement allocation $\neq$ total amount, or balance $< 0$ detected by audit daemon. | Immediate Traffic Halt & Rollback |
| **TRG-03** | Critical | **Database Migration Failure**: Alembic migration fails midway or causes table lock exceeding 30 seconds. | Migration Rollback & Restore |
| **TRG-04** | High | **Health Probe Failure**: Kubernetes `/health/ready` probe fails consecutively for 3 cycles (45 seconds). | Automatic Container Rollback |
| **TRG-05** | High | **Worker Deadlock / Queue Stalling**: Unreconciled queue depth grows $> 5,000$ jobs with zero dequeue completions. | Worker Node Reset & Queue Drain |

---

## 3. Rollback Runbooks

### 3.1 Runbook A: Application Version Rollback (Zero Downtime)

For stateless FastAPI backend or Next.js frontend container failures.

```
Step 1: Shift Traffic at Load Balancer
   ├── Set Target Group traffic weight to Previous Stable Release (Blue) = 100%
   └── Reduce New Release (Green) traffic weight = 0%

Step 2: Verify Ingress Health
   ├── Inspect HTTP 200 response rate on https://api.finora.internal/health
   └── Confirm error rate drops below 0.05%

Step 3: Terminate Unhealthy Container Instances
   └── Gracefully terminate Green task instances after in-flight requests finish (timeout: 30s)
```

**CLI Execution (Docker Compose / Container Cluster):**
```bash
# 1. Roll back to previous image tag
docker compose -f docker-compose.prod.yml up -d --no-deps --build backend_previous

# 2. Verify backend status
curl -s http://localhost:8000/health/ready | jq .
```

---

### 3.2 Runbook B: Database Migration Rollback (Alembic)

When a schema migration introduces incompatible constraints, broken foreign keys, or query timeouts.

> **CRITICAL PRE-CONDITION**: Never perform an in-place `alembic downgrade` without confirming that newly written data has been evaluated for schema compatibility.

```bash
# 1. Place application in Maintenance Mode (block new write requests)
# Configure Nginx / ALB to return HTTP 503 with Retry-After: 300

# 2. Check current Alembic revision in PostgreSQL
cd backend
python -m alembic current

# 3. Revert exactly one revision (or target specific revision ID)
python -m alembic downgrade -1

# 4. Verify schema state and constraints
python -m alembic heads

# 5. Disable Maintenance Mode and resume traffic
```

---

### 3.3 Runbook C: Database Disaster Recovery (Point-in-Time Restore)

When database data is corrupted or an unrecoverable schema error occurs.

Finora provides an automated database backup and restore utility located at `backend/app/scripts/backup_restore.py`.

#### Automated Snapshot Execution:
```bash
# Manual snapshot creation prior to deployment:
python backend/app/scripts/backup_restore.py backup --output /var/backups/finora/pre_deploy_$(date +%Y%m%d_%H%M%S).sql
```

#### Full Restoration Procedure:
```bash
# 1. Stop all backend API and background worker processes to prevent concurrent writes
docker compose stop backend worker

# 2. Terminate active PostgreSQL database connections
psql $DATABASE_URL -c "
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = 'finora_prod'
  AND pid <> pg_backend_pid();"

# 3. Execute restore using Finora backup utility or native pg_restore
python backend/app/scripts/backup_restore.py restore --input /var/backups/finora/pre_deploy_snapshot.sql

# 4. Run database verification and invariant check
python -m pytest tests/test_independent_financial_oracle.py -q

# 5. Restart application services
docker compose start backend worker
```

---

### 3.4 Runbook D: Asynchronous Worker & Redis Queue Recovery

When poisoned payloads, network partitions, or unhandled exceptions stall the Redis worker pool.

1. **Pause Ingestion Endpoint**:
   Temporarily throttle `POST /api/v1/ingestion/upload` to prevent new jobs from entering the queue.
2. **Inspect Dead Letter Queue (DLQ)**:
   ```bash
   # Connect to Redis CLI
   redis-cli -u $REDIS_URL
   LLEN finora:reconciliation:dlq
   ```
3. **Flush Poisoned Job from Active Queue**:
   Move poisoned job payload to isolation bucket for engineering review:
   ```bash
   RPOPLPUSH finora:reconciliation:active finora:reconciliation:poison_quarantine
   ```
4. **Restart Worker Processes**:
   ```bash
   docker compose restart worker
   ```
5. **Resume Normal Traffic**:
   Re-enable ingestion endpoint and verify dequeue rates.

---

## 4. Post-Rollback Financial Integrity Verification

Following any rollback or recovery event, the Financial Systems Auditor must verify the 17 core financial invariants:

1. **Run Independent Financial Verification Oracle**:
   ```bash
   cd backend
   python -m pytest tests/test_independent_financial_oracle.py --tb=short -q
   ```
2. **Execute Multi-Tenant Balance Audit**:
   Verify that for every tenant:
   $$\text{Ledger Balance} = \sum \text{Settled Payments} - \sum \text{Refunds} - \sum \text{Deducted Fees}$$
3. **Verify Ledger Tamper-Evidence**:
   Query audit log hash chains to ensure continuity:
   ```sql
   SELECT tenant_id, COUNT(*) as unchained_records 
   FROM audit_logs 
   WHERE previous_hash IS NULL AND sequence_num > 1;
   ```
   *(Must return 0 rows).*

---

## 5. Incident Roles & Communication Escalation Matrix

| Role | Responsibility | Primary Contact |
| :--- | :--- | :--- |
| **Incident Commander (IC)** | Declares incident severity; authorizes deployment rollback. | Principal FinTech Architect |
| **Database Lead** | Executes Alembic rollback or point-in-time PostgreSQL recovery. | Database Administrator |
| **DevOps / SRE Lead** | Handles container traffic shifts, load balancer routing, and container redeployments. | Lead SRE |
| **Financial QA Lead** | Executes test oracles and signs off on post-recovery financial integrity. | QA Automation Lead |

---

## 6. Post-Mortem & Blameless Review SLA

Within **24 hours** of any production rollback or disaster recovery event, the Incident Commander must publish a Root Cause Analysis (RCA) document covering:
1. Exact timeline of events (timestamps in UTC).
2. Root cause (code defect, infrastructure failure, configuration error).
3. Financial impact assessment (reconciliation delay, orphaned transactions, zero-balance drift verification).
4. Permanent remediation work items added to the engineering sprint backlog.
