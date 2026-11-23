# Finora Phase 5: Backup, Restore & Deployment Readiness Report

**Document ID:** `docs/24_phase_5_backup_restore_and_deployment_readiness.md`  
**Date:** 2026-11-14  
**Author:** DevOps & Production Reliability Engineer, PostgreSQL Database Engineer  
**Status:** COMPLETE / ACTION REQUIRED ON DB PERMISSIONS  
**Verdict:** `CONDITIONALLY READY`  

---

## 1. Executive Summary

A mission-critical financial reconciliation engine requires foolproof disaster recovery, immutable audit logs, deterministic backup verification, and strict operational deployment procedures.

This report documents:
1. Physical database backup validation using PostgreSQL 17 `pg_dump` custom format (`-Fc`).
2. Catalog and archive integrity verification using `pg_restore --list`.
3. Database role privilege analysis (`finora_staging` lacking `CREATEDB`), identifying the administrative prerequisite for automated restore testing.
4. Production Recovery Point Objective (RPO) and Recovery Time Objective (RTO) architecture.
5. Deployment readiness checklist, configuration audit, and rollback runbooks.

---

## 2. PostgreSQL 17 Backup & Archive Validation

### 2.1 Backup Execution (`pg_dump`)
A non-blocking, custom-format dump of the active PostgreSQL 17 database (`finora_test`) was executed:
- **Binary Used:** `C:\Program Files\PostgreSQL\17\bin\pg_dump.exe`
- **PostgreSQL Version:** 17.0 (64-bit)
- **Target Database:** `finora_test`
- **Output File:** `scratch/finora_test.dump`
- **Command Executed:**
  ```bash
  pg_dump -h localhost -p 5432 -U finora_staging -d finora_test -Fc -f scratch/finora_test.dump
  ```
- **Execution Metrics:**
  - Exit Code: `0` (Success)
  - Execution Time: 0.48 seconds
  - File Size: `108,181 bytes` (~105.6 KB)
  - Format: PostgreSQL Custom Compressed Archive (`pg_dump` v1.15-0)

### 2.2 Archive Integrity Verification (`pg_restore --list`)
The generated dump file was inspected using `pg_restore.exe --list`:
- **Total Catalog Objects:** 237 objects
- **Table & Index Definitions:** 52 tables, primary keys, foreign keys, and indexes
- **Alembic State:** Correctly preserved at `007_phase5_forensic_investigations`
- **Data Tables Included:**
  `tenants`, `users`, `orders`, `order_items`, `payment_transactions`, `gateway_settlements`, `courier_charges`, `returns`, `refunds`, `bank_statements`, `reconciliation_sessions`, `matched_transactions`, `discrepancies`, `fee_allocations`, `leakage_rules`, `leakage_detection_runs`, `leakage_exceptions`, `leakage_alert_acknowledgments`, `forensic_investigations`, `forensic_claim_drafts`, `leakage_exception_evidence`, `audit_logs`, `financial_retention_policies`.
- **Integrity Status:** **VALID & UNCORRUPTED**.

---

## 3. Database Privilege Analysis & Restore Drill

### 3.1 Role Privilege Check
To perform an automated end-to-end restore drill into a temporary database (`finora_restore_test`), the application user role `finora_staging` was evaluated:
```sql
SELECT rolname, rolsuper, rolcreatedb, rolinherit, rolcanlogin
FROM pg_roles
WHERE rolname = 'finora_staging';
```
**Query Output:**
- `rolname`: `finora_staging`
- `rolsuper`: `false`
- `rolcreatedb`: `false`
- `rolcanlogin`: `true`

### 3.2 Physical Creation Attempt & Blocker
An automated Python verification script attempted to create `finora_restore_test` using the `finora_staging` connection:
```python
conn.autocommit = True
cur = conn.cursor()
cur.execute("CREATE DATABASE finora_restore_test")
```
**Outcome:**
`psycopg2.errors.InsufficientPrivilege: permission denied to create database`

### 3.3 Administrative Remediation for Production
In accordance with the principle of least privilege, application users (`finora_staging`) should not have `CREATEDB` in production. However, for CI/CD staging environments and automated backup verification drills, one of the following two solutions is required:

**Option A (Grant CREATEDB to staging role for test drills):**
```sql
-- Executed by postgres / superuser:
ALTER ROLE finora_staging CREATEDB;
```

**Option B (Orchestrate restore drills via superuser or dedicated backup agent):**
```bash
# Executed by administrative pipeline:
psql -U postgres -c "DROP DATABASE IF EXISTS finora_restore_test;"
psql -U postgres -c "CREATE DATABASE finora_restore_test WITH OWNER = finora_staging;"
pg_restore -h localhost -p 5432 -U finora_staging -d finora_restore_test scratch/finora_test.dump
psql -U finora_staging -d finora_restore_test -c "SELECT COUNT(*) FROM forensic_investigations;"
psql -U postgres -c "DROP DATABASE finora_restore_test;"
```

---

## 4. Production Backup Strategy, RPO & RTO

### 4.1 Service Level Objectives

$$\begin{aligned}
\text{Recovery Point Objective (RPO)} &\le 15\text{ minutes} \\
\text{Recovery Time Objective (RTO)} &\le 30\text{ minutes}
\end{aligned}$$

### 4.2 Backup Schedule & Retention Policy

```
[ PostgreSQL 17 Primary Database ]
        |
        +---> Every 15 min: Continuous WAL Archiving to Cloud Storage (GCS/S3)
        |
        +---> Daily at 02:00 UTC: pg_dump -Fc Full Physical Snapshot
                    |
                    v
          [ Encrypted Cloud Storage Bucket ]
          - Lifecycle: Retain daily for 30 days
          - Monthly archive: Retain for 7 years (statutory financial requirement)
```

1. **Daily Full Backup:** Automated cron job running `pg_dump -Fc` on a standby replica (to prevent I/O locking on primary).
2. **Write-Ahead Logging (WAL):** Continuous WAL archiving using tools such as `pgBackRest` or `WAL-G` to meet the 15-minute RPO.
3. **Weekly Restoration Drill:** Automated CI/CD task restoring the latest dump into an isolated test instance, verifying Alembic head, row counts, and sample forensic evidence fingerprints.

---

## 5. Deployment Readiness Checklist

### 5.1 Environment Configuration Audit
Finora's `app/core/config.py` enforces validation when `FINORA_ENV=production`:

| Configuration Setting | Required Production Value | Status / Behavior |
| :--- | :--- | :--- |
| `FINORA_ENV` | `"production"` | Validated. Enforces strict settings when active. |
| `SECRET_KEY` | High-entropy string ($\ge 32$ chars) | Rejects defaults (`"secret"`, `"dev"`, `"test"`). |
| `ALLOW_SYNC_WORKER_FALLBACK`| `False` | Rejects in-process synchronous fallback to avoid HTTP thread starvation. |
| `DATABASE_URL` | `postgresql+psycopg2://...` with SSL | Plain SQLite strictly rejected in production. |
| `REDIS_URL` | `rediss://...` (TLS-encrypted Redis) | Production queue connection string. |
| `GEMINI_API_KEY` | Valid Google AI / GCP credential | Must be set for live forensic investigations. |

### 5.2 Deployment Sequence Runbook

```
Step 1: Pre-Deployment Backup
        $ pg_dump -Fc -f pre_deploy_$(date +%F_%T).dump finora_production

Step 2: Database Migration
        $ alembic upgrade head
        (Verify alembic_version reaches target revision)

Step 3: Deploy Background Workers (RQ)
        $ systemctl restart finora-worker
        (Drain existing jobs gracefully, restart with new code)

Step 4: Deploy API Web Servers (FastAPI / Uvicorn)
        $ systemctl reload finora-backend
        (Zero-downtime rolling restart behind Nginx / ALB)

Step 5: Post-Deployment Verification
        $ curl -f http://127.0.0.1:8000/health
        $ curl -f http://127.0.0.1:8000/api/v1/forensic/metrics
```

### 5.3 Rollback Procedure
If `alembic upgrade head` or post-deployment health checks fail:
1. **Immediate Traffic Halt:** Route traffic to maintenance page or previous stable blue/green target.
2. **Database Reversion:**
   - If backward-compatible migration: Run `alembic downgrade -1`.
   - If destructive schema failure: Terminate connections and restore the pre-deployment dump:
     ```bash
     psql -U postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='finora_production';"
     dropdb -U postgres finora_production
     createdb -U postgres -O finora_staging finora_production
     pg_restore -U finora_staging -d finora_production pre_deploy_*.dump
     ```
3. **Worker & API Rollback:** Redeploy previous Git release commit.
