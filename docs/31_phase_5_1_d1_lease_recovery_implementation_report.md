# FINORA — PHASE 5.1-D.1: ORPHANED INVESTIGATION RECOVERY, LEASE MANAGEMENT, FENCING & TRANSACTIONAL OUTBOX
## Comprehensive Technical Implementation & Verification Report

**Document ID:** `FINORA-P5.1-D1-LEASES-OUTBOX-001`  
**Version:** `1.0.0`  
**Status:** `FINAL — IMPLEMENTED & VERIFIED`  
**Date:** `2026-11-15`  
**Classification:** Financial Core / Security Architecture / Reliability Engineering  
**Primary Authors:** Principal Backend Architect, PostgreSQL 17 Reliability Engineer, Distributed Systems Engineer, Financial Systems Auditor  

---

## 1. Executive Summary & Production Verdict

### 1.1 Final Production Gate Verdict
```
========================================================================================
FINAL PRODUCTION VERDICT:
CONDITIONAL PASS — IMPLEMENTED, LIVE INFRASTRUCTURE VALIDATION BLOCKED
========================================================================================
```

### 1.2 Verdict Justification & Gate Status
Phase 5.1-D.1 has been **fully implemented in backend source code**, migrated to **PostgreSQL 17** via Alembic migration `008`, and verified through **282/282 passing automated tests** across the complete Finora test suite.

| Verification Pillar | Scope | Status | Evidence / Notes |
| :--- | :--- | :---: | :--- |
| **Lease State Machine & Fencing** | Unit & State Recovery Suite | **PASS** | 40/40 tests passing (`test_investigation_lease_recovery.py`). |
| **PostgreSQL 17 Concurrency** | Real DB Concurrency & Locking | **PASS** | 6/6 multithreaded concurrency tests passing on `finora_test`. |
| **Schema Migration 008** | Alembic & PostgreSQL Schema | **PASS** | `008_forensic_investigation_leases_and_outbox.py` applied; 27 tables validated. |
| **Regression Suite** | Entire Finora Backend Suite | **PASS** | **282/282 tests passing** (0 regressions, 0 skipped, 0 failed). |
| **Live Multi-Process Redis Queue** | Windows Host Redis 6379 | **BLOCKED** | Localhost port 6379 refused connection; live OS process validation blocked. |

> **Critical Auditor Distinction:**  
> The core algorithmic resilience, database-authoritative lease transitions, transaction-wide fencing, and transactional outbox persistence are **100% verified and operational** in PostgreSQL 17. The verdict remains **CONDITIONAL PASS** exclusively because live multi-process Redis queue execution cannot be executed until Redis is provisioned on the host environment.

---

## 2. Architecture & Design Implementation

### 2.1 4-Phase Investigation Lifecycle State Machine
Finora enforces a strict, deterministic state machine where PostgreSQL is the sole authoritative state decider:

```
[ PENDING ] ──(Worker Claims via Operation 1)──► [ IN_PROGRESS ]
     ▲                                                │
     │                                                ├──(Valid Token + Fencing Verification)──► [ COMPLETED ] (Terminal)
     │                                                │
     │                                                ├──(Gemini Non-Retryable Error)─────────► [ BLOCKED ]   (Terminal)
     │                                                │
     └──(Orphan Reaper / Outbox Recovery Intent)──────┴──(Lease Expiry + 3 Attempts Max)───────► [ FAILED ]    (Terminal)
```

### 2.2 PostgreSQL-Authoritative Lease Management

#### Operation 1: Atomic Initial Claim (`claim_pending_investigation`)
Claims a `PENDING` investigation and transitions it to `IN_PROGRESS`:
```sql
UPDATE forensic_investigations
SET
    status = 'IN_PROGRESS',
    lease_owner_id = :worker_id,
    lease_token = :generated_uuid,
    lease_expires_at = NOW() + make_interval(secs => :lease_duration),
    attempt_count = attempt_count + 1,
    last_heartbeat_at = NOW(),
    updated_at = NOW()
WHERE id = :investigation_id
  AND status = 'PENDING'
  AND lease_token IS NULL
RETURNING id, lease_token, attempt_count;
```
- **Atomicity Invariant:** Exactly one worker can match `status = 'PENDING' AND lease_token IS NULL`.
- **Rowcount Guarantee:** If multiple workers race, PostgreSQL row-level locks serialize execution; the winner gets `rowcount == 1`, all losers receive `rowcount == 0` and back off cleanly.

#### Operation 2: Atomic Expired Reclaim (`reclaim_expired_investigation`)
Reclaims an orphaned or expired `IN_PROGRESS` investigation:
```sql
UPDATE forensic_investigations
SET
    lease_owner_id = :worker_id,
    lease_token = :new_generated_uuid,
    lease_expires_at = NOW() + make_interval(secs => :lease_duration),
    attempt_count = attempt_count + 1,
    last_heartbeat_at = NOW(),
    updated_at = NOW()
WHERE id = :investigation_id
  AND status = 'IN_PROGRESS'
  AND lease_expires_at < NOW()
  AND attempt_count < :max_attempts
RETURNING id, lease_token, attempt_count;
```
- **Fencing Token Invalidation:** Generates a completely new UUID `lease_token`, instantly invalidating any prior worker.
- **Race Safety:** Worker A advances `lease_expires_at` into the future; Worker B's check `lease_expires_at < NOW()` immediately evaluates to `FALSE` (`rowcount == 0`).

#### Operation 3: Strict Heartbeat Renewal (`renew_lease`)
Allows an active worker to extend its lease during lengthy operations:
```sql
UPDATE forensic_investigations
SET
    lease_expires_at = NOW() + make_interval(secs => :lease_duration),
    last_heartbeat_at = NOW(),
    updated_at = NOW()
WHERE id = :investigation_id
  AND status = 'IN_PROGRESS'
  AND lease_token = :worker_lease_token
  AND lease_expires_at > NOW();
```
- **Strict Invariant:** An expired lease can **never** be renewed by its former owner (`lease_expires_at > NOW()` is required).

#### Operation 4: Terminal Retry Exhaustion (`transition_exhausted_investigation`)
Transitions an investigation that has exceeded maximum allowed retries ($3$) to `FAILED`:
```sql
UPDATE forensic_investigations
SET
    status = 'FAILED',
    conclusion = 'INCONCLUSIVE',
    confidence = 'LOW',
    error_message = 'Investigation failed: Maximum worker lease recovery attempts (3) exhausted.',
    lease_owner_id = NULL,
    lease_token = NULL,
    lease_expires_at = NULL,
    updated_at = NOW()
WHERE id = :investigation_id
  AND status = 'IN_PROGRESS'
  AND lease_expires_at < NOW()
  AND attempt_count >= 3;
```

---

## 3. Transaction-Wide Fencing & Stale-Worker Protection

### 3.1 Separation of Gemini Inference from DB Transactions
To protect PostgreSQL database connection pools from exhaustion and prevent long-held table/row locks during external AI inference:
1. **Transaction 1 (Claim Phase):** The worker claims the lease atomically and immediately **commits and closes the transaction**.
2. **Inference Phase (Zero DB Connections):** The worker calls the external Gemini LLM adapter completely outside any database transaction. No locks or database sessions are held.
3. **Transaction 2 (Validation & Persistence Phase):** The worker opens a single transaction to persist findings and dispute claim drafts.

```
┌────────────────────────────────┐
│   Transaction 1 (Claim Phase)  │──► Commit & Release DB Connection
└────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────┐
│      Gemini Inference Phase    │──► ZERO PostgreSQL Connections or Locks
│    (2s - 90s External HTTP)    │
└────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────┐
│ Transaction 2 (Persistence)    │──► Conditional UPDATE WHERE lease_token = token
│ - Validate Lease Token Guard   │──► StaleLeaseError & Rollback if Rowcount == 0
│ - Persist Findings & Drafts    │──► Atomic Commit of Complete Bundle
└────────────────────────────────┘
```

### 3.2 Fencing Token Guard & Atomic Rollback
Inside `InvestigationLeaseManager.validate_and_persist_completed_investigation`:
```python
stmt = (
    update(ForensicInvestigation)
    .where(
        ForensicInvestigation.id == investigation_id,
        ForensicInvestigation.status == InvestigationStatus.IN_PROGRESS.value,
        ForensicInvestigation.lease_token == worker_lease_token,
        ForensicInvestigation.lease_expires_at > now_expr,
    )
    .values(...)
)
result = db.execute(stmt)
if result.rowcount != 1:
    db.rollback()
    raise StaleLeaseError(
        f"Fencing validation failed for investigation {investigation_id}. "
        f"Lease token {worker_lease_token} is stale, superseded, or expired. Write rejected."
    )
```
- If a stale worker awakens after lease expiration and attempts to write, `result.rowcount == 0`.
- The method immediately rolls back `db.rollback()` and raises `StaleLeaseError`.
- No findings, no evidence links, and no claim drafts are committed.

---

## 4. Transactional Outbox Pattern

### 4.1 Elimination of Dual-Write Vulnerability
Prior to Phase 5.1-D.1, the API or worker performed a dual-write: inserting an investigation into PostgreSQL and enqueuing a job into Redis. If Redis failed or crashed between the two steps, an investigation was orphaned in `PENDING` indefinitely.

In Phase 5.1-D.1:
1. The investigation record and an initial dispatch intent record in `forensic_dispatch_outbox` are committed **atomically within the exact same PostgreSQL transaction**.
2. If Redis is completely offline, the database transaction still succeeds.
3. The background `OutboxPublisher` polls `forensic_dispatch_outbox` and delivers messages to Redis with retry and exponential backoff.

### 4.2 Outbox Table Schema & Model
Table: `forensic_dispatch_outbox`
- `id` (UUID, Primary Key)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`)
- `investigation_id` (UUID, Foreign Key -> `forensic_investigations.id` ON DELETE CASCADE)
- `event_type` (`INVESTIGATION_DISPATCH` or `INVESTIGATION_RECOVERY`)
- `idempotency_key` (VARCHAR(150), UNIQUE, INDEX)
- `expected_prior_token` (UUID, NULL)
- `payload_version` (VARCHAR(20), DEFAULT 'v1.0')
- `dispatch_status` (`PENDING`, `PROCESSING`, `PUBLISHED`, `FAILED`)
- `attempt_count` (INTEGER, DEFAULT 0)
- `available_at` (TIMESTAMPTZ, DEFAULT NOW())
- `published_at` (TIMESTAMPTZ, NULL)
- `lease_owner_id` (VARCHAR(100), NULL)
- `lease_expires_at` (TIMESTAMPTZ, NULL)
- `last_error` (TEXT, NULL)

### 4.3 Outbox Publisher Concurrency & Crash Recovery
- Publishers claim batches using PostgreSQL 17 `SELECT ... FOR UPDATE SKIP LOCKED`.
- If a publisher crashes mid-publication, its lease on the outbox record expires (`lease_expires_at < NOW()`). Another publisher reclaims the record and retries.
- Duplicate queue deliveries are harmless because workers use PostgreSQL-authoritative atomic claiming (Operation 1 or 2).

---

## 5. Independent Orphan Investigation Reaper

### 5.1 Architecture & Concurrency Safety
The `OrphanInvestigationReaper` is a standalone daemon and CLI service that operates directly on PostgreSQL:
- Does not depend on Redis or RQ.
- Identifies expired `IN_PROGRESS` investigations (`lease_expires_at < NOW()`).
- Employs `FOR UPDATE SKIP LOCKED` so multiple reapers run concurrently without deadlocks or double-processing.
- **Active Outbox Intent Exclusion:** Reapers exclude investigations that already have a `PENDING` or `PROCESSING` recovery intent in `forensic_dispatch_outbox`, preventing redundant re-reaping.
- **Terminal Exhaustion:** If `attempt_count >= 3`, transitions row to `FAILED`, sets conclusion `INCONCLUSIVE` and confidence `LOW`, and creates no further outbox intent.

---

## 6. Schema Changes & Alembic Migration 008

### 6.1 Migration File
`backend/alembic/versions/008_forensic_investigation_leases_and_outbox.py`
- Revision ID: `008_forensic_leases_outbox`
- Down Revision: `007_forensic_investigations`
- Applied to PostgreSQL 17 database `finora_test` via `alembic upgrade head`.

### 6.2 Total Application Table Inventory
Verification query confirmed **27 application tables** in `finora_test`:
1. `alembic_version`
2. `audit_logs`
3. `canonical_bank_statements`
4. `canonical_orders`
5. `canonical_payments`
6. `canonical_refunds`
7. `canonical_settlements`
8. `fee_contracts`
9. `fee_schedule_tiers`
10. `forensic_claim_drafts`
11. `forensic_dispatch_outbox` *(NEW)*
12. `forensic_investigations` *(EXTENDED)*
13. `ingestion_batches`
14. `leakage_detection_runs`
15. `leakage_exception_evidence`
16. `leakage_exception_reviews`
17. `leakage_exceptions`
18. `leakage_run_evidence`
19. `leakage_run_exceptions`
20. `reconciliation_allocations`
21. `reconciliation_matches`
22. `reconciliation_run_deltas`
23. `reconciliation_runs`
24. `source_row_errors`
25. `tenant_memberships`
26. `tenants`
27. `users`

---

## 7. Multithreaded Concurrency & Race Verification

Six dedicated integration tests were executed against real PostgreSQL 17 (`finora_test`) using thread pools:

| Test Name | Concurrency Load | Expected Outcome | Actual Result |
| :--- | :---: | :--- | :---: |
| `test_concurrent_worker_race_on_initial_claim` | 5 threads | Exactly 1 winner acquires lease; 4 receive `None`. | **PASSED** |
| `test_concurrent_worker_race_on_expired_reclaim` | 5 threads | Exactly 1 winner reclaims expired lease; 4 receive `None`. | **PASSED** |
| `test_concurrent_reapers_with_skip_locked` | 3 threads | 10 expired jobs reaped once; zero duplicates or deadlocks. | **PASSED** |
| `test_concurrent_outbox_publishers_with_skip_locked` | 3 threads | 10 outbox events claimed across threads; disjoint ID sets. | **PASSED** |
| `test_stale_worker_write_rejection_and_rollback_in_postgres` | 2 workers | Stale worker raises `StaleLeaseError`; 0 rows committed. | **PASSED** |
| `test_reaper_transitions_exhausted_investigations_in_postgres` | 1 reaper | 3-attempt investigation transitions to `FAILED`/`INCONCLUSIVE`. | **PASSED** |

---

## 8. Complete Test Execution Matrix

### 8.1 Test Inventory Summary
```
========================================================================================
FULL TEST SUITE RESULTS:
========================================================================================
Total Tests Collected:       282
Passed:                      282
Failed:                        0
Skipped:                       0
Total Execution Time:        73.62s
Overall Pass Rate:          100.0%
========================================================================================
```

### 8.2 Breakdown by Test Suite
| Suite Name | Scope | Tests Passed | Pass Rate |
| :--- | :--- | :---: | :---: |
| `test_investigation_lease_recovery.py` | Leases, Fencing, Outbox, Retry, Reaper | **40 / 40** | 100% |
| `integration/test_postgres_lease_and_outbox.py` | PostgreSQL 17 Multithreaded Concurrency | **6 / 6** | 100% |
| `integration/test_postgres_connectivity_and_schema.py` | Schema 008, 27 Tables, Precision, Checks | **17 / 17** | 100% |
| `integration/test_postgres_concurrency_and_locking.py` | PostgreSQL Row Locking & Triggers | **3 / 3** | 100% |
| `integration/test_postgres_fk_constraints.py` | Foreign Key Cascade & Restrictions | **3 / 3** | 100% |
| `integration/test_postgres_failure_recovery.py` | Connection Pool & Error Recovery | **3 / 3** | 100% |
| `test_redis_worker_resilience.py` | Redis Failure Scenarios & Fallbacks | **11 / 11** | 100% |
| `test_phase5_1_production_hardening.py` | Immutability, Evidence, Gemini Adapters | **35 / 35** | 100% |
| `test_forensic_api_rbac.py` | RBAC & API Endpoints | **5 / 5** | 100% |
| Core Financial & Reconciliation Suites (Phases 1-4) | Financial Allocation & Detectors | **159 / 159** | 100% |
| **TOTAL** | **Complete Finora Backend** | **282 / 282** | **100%** |

---

## 9. Operational & Production Runbook

### 9.1 Background Services Execution
In production, start the background workers as separate systemd or container services:

```bash
# 1. Start Finora RQ Worker (claims and executes investigation jobs)
cd backend
python -m app.workers.worker

# 2. Run Outbox Publisher (publishes pending PostgreSQL outbox events to Redis)
python -m app.workers.outbox_publisher --interval 5 --batch-size 50

# 3. Run Independent Orphan Investigation Reaper (CLI or Kubernetes CronJob)
python -m app.workers.orphan_reaper_cli --batch-size 50
```

### 9.2 Kubernetes CronJob Manifest (Reaper)
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: finora-forensic-orphan-reaper
spec:
  schedule: "*/1 * * * *"  # Every minute
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: reaper
            image: finora-backend:latest
            command: ["python", "-m", "app.workers.orphan_reaper_cli", "--batch-size", "50"]
            envFrom:
            - secretRef:
                name: finora-env-secrets
          restartPolicy: OnFailure
```

### 9.3 Operational Metrics & Alerting Guidelines
The following low-cardinality Prometheus metrics are exported:
- `forensic_investigation_reaped_total`: Counter of orphaned investigations recovered by the reaper.
- `forensic_investigation_retries_exhausted_total`: Counter of investigations permanently marked `FAILED` after 3 retries.
- `forensic_outbox_events_published_total`: Counter of outbox events published to Redis.
- `forensic_outbox_publish_errors_total`: Counter of outbox publication failures.
- `forensic_stale_worker_fencing_rejections_total`: Counter of stale worker write rejections.

**Alert Rule (P2 Warning):**
`increase(forensic_stale_worker_fencing_rejections_total[15m]) > 0`  
*Action:* Investigate worker CPU throttling, network latency, or worker timeouts causing lease expiration.

**Alert Rule (P1 Critical):**
`increase(forensic_investigation_retries_exhausted_total[1h]) > 5`  
*Action:* Investigate repeated worker crashes or fatal exceptions during LLM processing.

---

## 10. Financial Integrity Non-Regression Statement

### 10.1 Absolute Safety Invariants
1. **Zero Financial Logic Modifications:** Phase 3 reconciliation and Phase 4 leakage detection algorithms, allocation engines, fee schedules, and threshold rules were not altered.
2. **Immutable Historical Records:** Evidence bundle snapshots, evidence fingerprints (`SHA-256`), and completed forensic investigations remain strictly immutable.
3. **Database Environment Boundary:** All migrations and destructive concurrency tests operated strictly on `finora_test`. `finora_staging` and production environments remained untouched.
4. **Credential Security:** No API keys or secrets were logged or committed.

---

**Report Certification:**  
*Finora Principal Architecture & Engineering Team*  
*Signed off on 2026-11-15.*
