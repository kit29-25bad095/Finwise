# Phase 5.1-D.1: Orphaned Investigation Recovery Architectural Design

**Document ID:** `FINORA-DOC-030-ORPHANED-INVESTIGATION-RECOVERY`  
**Revision:** 2.0 (Final Architecture Review)  
**Date:** 2026-11-14  
**Author Roles:** Principal Backend Architect, Distributed Systems Reliability Engineer, Financial Systems Security Auditor  
**System Under Design:** Finora Financial Reconciliation & Revenue Leakage Platform  
**Target Environment:** FastAPI, PostgreSQL 17, Redis 7 / RQ, Google Gemini API  
**Design Phase:** Phase 5.1-D.1 (Architecture & System Design Only — Zero Code or Schema Modifications)  
**Status:** ARCHITECTURE APPROVED — AWAITING IMPLEMENTATION AUTHORIZATION  

---

## 1. Executive Summary

During the Phase 5.1-D Redis and Worker Resilience Audit, an architectural vulnerability was identified in the asynchronous forensic investigation pipeline:
1. When an RQ worker process picks up an investigation in `PENDING` status, it atomically updates `status = 'IN_PROGRESS'` in PostgreSQL and immediately commits the transaction.
2. If the worker process subsequently dies abruptly (e.g., operating system `SIGKILL`, container termination, out-of-memory eviction, unhandled thread death, or power disruption), the investigation remains permanently stuck in `status = 'IN_PROGRESS'`.
3. Because Finora's at-least-once delivery protection deliberately skips investigations currently marked `IN_PROGRESS` to avoid duplicate processing, orphaned investigations can become permanently stranded without automated resolution or notification.

This document presents the revised, production-grade architectural design of a **Lease-Based Investigation Recovery Mechanism with Fencing Tokens and Transaction-Wide Protection**.

### Key Architectural Guarantees
- **Atomic Lease Ownership:** Exactly one worker can hold active ownership of an investigation at any point in time.
- **Transaction-Wide Fencing Protection:** Stale workers that experience network partitions or garbage collection freezes cannot persist partial findings, evidence references, conclusions, or claim drafts after their lease expires.
- **Strict Lease Renewal:** A worker may renew its lease only while the lease is strictly valid (`lease_expires_at > NOW()`). An expired lease can never be renewed by its former owner.
- **Separate Claim and Reclaim Operations:** Distinct atomic operations govern initial claiming versus expired lease reclamation, each generating a fresh UUID fencing token and incrementing the attempt count exactly once.
- **Bounded 3-Attempt Lifecycle:** Coordinated retry accounting between RQ and PostgreSQL strictly enforces a 3-attempt ceiling (Attempt 1: Initial, Attempt 2: First Recovery, Attempt 3: Second Recovery) before fail-closed termination.
- **Idempotent Reaper Architecture:** Independent scheduled background reaper identifies expired leases and cleans up abandoned investigations with zero race conditions across worker pods.
- **Zero Financial and Evidence Drift:** Core deterministic financial amounts, cryptographic evidence bundles, and audit history remain strictly immutable.

---

## 2. Actual Root Cause from Code Inspection

Inspection of the actual codebase revealed the precise structural reason for orphaned investigations:

### 2.1 Missing Lease and Ownership State in Models
Inspecting `backend/app/models/forensic.py` (lines 65–139) and Alembic migration `007_phase5_forensic_investigations.py` (lines 28–63):
- The `ForensicInvestigation` model contains lifecycle columns (`status`, `conclusion`, `confidence`, `summary`) and evidence columns (`evidence_bundle_fingerprint`, `evidence_bundle_snapshot`), but **lacks any worker lease metadata**:
  - No `lease_owner_id` (no tracking of which worker instance or process owns the job).
  - No `lease_token` (no monotonic or UUID fencing token to detect stale workers).
  - No `lease_expires_at` (no timestamp defining when the lease becomes invalid).
  - No `attempt_count` (no counter tracking execution attempts).
  - No `last_heartbeat_at` (no heartbeat timestamp).

### 2.2 Premature Commit in Execution Pipeline
Inspecting `backend/app/services/forensics/investigation_service.py` (lines 165–192):
```python
if inv.status == InvestigationStatus.PENDING.value:
    stmt = (
        update(ForensicInvestigation)
        .where(
            ForensicInvestigation.id == investigation_id,
            ForensicInvestigation.status == InvestigationStatus.PENDING.value,
        )
        .values(status=InvestigationStatus.IN_PROGRESS.value)
    )
    result = db.execute(stmt)
    db.commit()  # <-- Commits status = 'IN_PROGRESS' immediately
    if result.rowcount == 0:
        return inv
    db.refresh(inv)
elif inv.status == InvestigationStatus.IN_PROGRESS.value:
    logger.info("Investigation %s is already IN_PROGRESS under another worker. Skipping concurrent execution.", investigation_id)
    return inv
```

### 2.3 Permanent API and Worker Skip
Inspecting `backend/app/services/forensics/investigation_service.py` (lines 72–95) and `backend/app/api/v1/forensic.py` (lines 68–84):
- When a user or system retries `POST /exceptions/{id}/investigations`:
  `create_investigation()` queries for existing investigations with status in `(COMPLETED, IN_PROGRESS, PENDING)`.
  It finds the existing row with `status = 'IN_PROGRESS'`, returns it, and skips enqueuing because `status != 'PENDING'`.
- When an RQ job is re-delivered:
  `execute_investigation_async()` detects `inv.status == 'IN_PROGRESS'` and returns immediately.
- The investigation is stranded permanently in `IN_PROGRESS` unless manually forced via `force_refresh=True`.

---

## 3. Existing Investigation Lifecycle

The existing investigation lifecycle follows a one-way state transition:

```
[ PENDING ] ───────────────► [ IN_PROGRESS ] ───────────────► [ COMPLETED ]
                                   │                               ▲
                                   │ (LLM/DB Failure)              │ (Deterministic Evaluation)
                                   ▼                               │
                              [ FAILED ]                      [ BLOCKED ] (Evidence Tampered)
```

### Constraints Imposed by Existing Immutability Rules
In `backend/app/models/forensic.py` (lines 231–266), the SQLAlchemy event listener `_prevent_forensic_investigation_update` enforces:
1. `tenant_id`, `exception_id`, `detection_run_id`, `evidence_bundle_fingerprint`, and `evidence_bundle_snapshot` are strictly immutable once created.
2. If `status` in the database is already `COMPLETED`, `BLOCKED`, or `FAILED` (terminal statuses), any subsequent update raises `ImmutabilityViolationError`.
3. Updates are permitted **only while status is `PENDING` or `IN_PROGRESS`**.

**Conclusion:** The recovery mechanism must operate strictly within `PENDING` and `IN_PROGRESS` states and must never alter immutable evidence attributes or attempt to resurrect terminal investigations.

---

## 4. Proposed Lease-Based Architecture

The recovery architecture uses a **Database-Backed Lease with Fencing Tokens**. PostgreSQL acts as the single authoritative source of truth. Redis/RQ serves purely as the distributed transport layer.

```
                           ┌──────────────────────────────────────────────┐
                           │            PostgreSQL 17 Database            │
                           │                                              │
                           │   status: IN_PROGRESS                        │
                           │   lease_owner_id: "worker-node-1-abc"        │
                           │   lease_token: "d290f1ee-..." (Fencing Token)│
                           │   lease_expires_at: 2026-11-14 20:35:00 UTC  │
                           │   attempt_count: 1                           │
                           └──────────────────────┬───────────────────────┘
                                                  │
                     ┌────────────────────────────┴───────────────────────────┐
                     │                                                        │
         Active Valid Lease                                      Lease Expired (Crash / Stall)
    (lease_expires_at > NOW())                                     (lease_expires_at < NOW())
                     │                                                        │
     Worker 1 proceeds with Gemini                             Reaper or Worker 2 reclaims lease:
     (OUTSIDE of DB transaction)                               • New lease_token: "e741c2aa-..."
                     │                                         • attempt_count = attempt_count + 1
     Finishes & persists atomically                            • New lease_expires_at = NOW() + 5m
     WHERE lease_token = "d290f1ee-..."                        • Error logged: 'Reclaimed...'
                     │                                                        │
              [ COMPLETED ]                                            [ IN_PROGRESS ]
```

### 4.1 Required New Entity Attributes
Add five discrete columns to the `forensic_investigations` table:

1. `lease_owner_id` (`String(100)`, nullable): Unique identifier of the worker process holding the lease (e.g., `worker-prod-az1-pid4829-uuid`).
2. `lease_token` (`UUID`, nullable): Fencing token regenerated on every claim or reclamation. Acts as an optimistic concurrency guard.
3. `lease_expires_at` (`DateTime(timezone=True)`, nullable): UTC wall-clock timestamp when the lease expires.
4. `attempt_count` (`Integer`, nullable=False, default=0): Total number of execution attempts initiated.
5. `last_heartbeat_at` (`DateTime(timezone=True)`, nullable): UTC timestamp of the most recent worker heartbeat/renewal.

### 4.2 Composite Index for High-Performance Recovery Queries
Add a dedicated composite index:
```sql
CREATE INDEX ix_forensic_inv_lease_recovery 
ON forensic_investigations (status, lease_expires_at) 
WHERE status = 'IN_PROGRESS';
```
This partial index guarantees $O(\log N)$ lookups for orphaned records without scanning completed historical investigations.

---

## 5. State-Transition Diagram

```
                 ┌──────────────────────────────────────────────────────────┐
                 │                                                          │
                 │                     [ PENDING ]                          │
                 │           (Freshly created or re-queued)                 │
                 │                                                          │
                 └──────────────┬───────────────────────────▲───────────────┘
                                │                           │
             Worker Claims Job  │                           │ Lease Expired &
            (Operation 1:       │                           │ Re-queued by Reaper
             attempt_count = 1) │                           │ (attempt_count < 3)
                                ▼                           │
                 ┌──────────────────────────────────────────┴───────────────┐
                 │                                                          │
                 │                   [ IN_PROGRESS ]                        │
                 │          (Lease valid: lease_expires_at > NOW())         │
                 │                                                          │
                 └───┬──────────────────┬───────────────────┬───────────────┘
                     │                  │                   │
         Heartbeat   │                  │ Unrecoverable     │ Evidence
         Renewal     │                  │ Error / Retries   │ Tampered
    (Same worker/    │                  │ Exhausted (>= 3)  ▼
     token extends   │                  ▼              [ BLOCKED ]
     if not expired) │             [ FAILED ]          (Terminal)
                     │             (Terminal)
                     │
                     │ Successfully Completed
                     │ (UPDATE ... WHERE lease_token = :token)
                     ▼
              [ COMPLETED ]
               (Terminal)
```

### 5.1 Permitted Transitions Table

| Current State | Target State | Condition / Trigger | Concurrency Guard |
| :--- | :--- | :--- | :--- |
| `PENDING` | `IN_PROGRESS` | Operation 1: Worker initial claim | `status = 'PENDING' AND attempt_count = 0` |
| `IN_PROGRESS` | `IN_PROGRESS` | Heartbeat lease renewal | `status = 'IN_PROGRESS' AND lease_token = :worker_token AND lease_expires_at > NOW()` |
| `IN_PROGRESS` | `IN_PROGRESS` | Operation 2: Worker reclaims expired lease | `status = 'IN_PROGRESS' AND lease_expires_at < NOW() AND attempt_count < 3` |
| `IN_PROGRESS` | `PENDING` | Reaper resets expired lease to queue | `status = 'IN_PROGRESS' AND lease_expires_at < NOW() AND attempt_count < 3` |
| `IN_PROGRESS` | `COMPLETED` | Worker finishes analysis successfully | `status = 'IN_PROGRESS' AND lease_token = :worker_token` |
| `IN_PROGRESS` | `FAILED` | Unhandled error OR 3 attempts exhausted | `status = 'IN_PROGRESS' AND (lease_token = :worker_token OR (lease_expires_at < NOW() AND attempt_count >= 3))` |
| `IN_PROGRESS` | `BLOCKED` | Cryptographic evidence mismatch | `status = 'IN_PROGRESS' AND lease_token = :worker_token` |
| `COMPLETED` | *ANY* | **STRICTLY FORBIDDEN** | Blocked by SQLAlchemy listener & DB immutability trigger |
| `FAILED` | *ANY* | **STRICTLY FORBIDDEN** | Blocked by SQLAlchemy listener & DB immutability trigger |
| `BLOCKED` | *ANY* | **STRICTLY FORBIDDEN** | Blocked by SQLAlchemy listener & DB immutability trigger |

---

## 6. Atomic Concurrency Strategy & Separate Claim/Reclaim Operations

PostgreSQL provides row-level write locks during `UPDATE` operations. By embedding conditional predicates directly into single SQL statements, we achieve strict atomicity without distributed lock managers (like Redlock) and eliminate split-brain races.

### 6.1 Operation 1: Initial Atomic Claim (`PENDING` -> `IN_PROGRESS`)
Executed exclusively when an investigation is in `PENDING` status:
```sql
UPDATE forensic_investigations
SET
    status = 'IN_PROGRESS',
    lease_owner_id = :worker_id,
    lease_token = :new_token,
    lease_expires_at = NOW() + INTERVAL '300 seconds',
    last_heartbeat_at = NOW(),
    attempt_count = attempt_count + 1,
    updated_at = NOW()
WHERE id = :investigation_id
  AND status = 'PENDING'
  AND attempt_count = 0
RETURNING id, lease_token, attempt_count;
```
- **Atomicity & Invariant:** Increments `attempt_count` from 0 to 1. Sets initial fencing token.
- If `rowcount == 1`: The worker successfully owns the initial lease.
- If `rowcount == 0`: Another worker claimed it or it is no longer `PENDING`. Skip execution.

### 6.2 Operation 2: Atomic Reclamation of Expired Lease (`IN_PROGRESS` -> `IN_PROGRESS`)
Executed when a worker or reaper encounters an investigation stuck in `IN_PROGRESS` with an expired lease:
```sql
UPDATE forensic_investigations
SET
    status = 'IN_PROGRESS',
    lease_owner_id = :worker_id,
    lease_token = :new_token,
    lease_expires_at = NOW() + INTERVAL '300 seconds',
    last_heartbeat_at = NOW(),
    attempt_count = attempt_count + 1,
    error_message = 'Reclaimed after previous worker lease expired.',
    updated_at = NOW()
WHERE id = :investigation_id
  AND status = 'IN_PROGRESS'
  AND lease_expires_at < NOW()
  AND attempt_count < 3
RETURNING id, lease_token, attempt_count;
```
- **Atomicity & Invariant:** Increments `attempt_count` (from 1 to 2, or 2 to 3). Generates a fresh UUID `lease_token`, immediately invalidating any prior worker's token.
- **Race Condition Safety:** If Worker A and Worker B both observe an expired lease at $t_1$, they both execute Operation 2. PostgreSQL serializes row updates. Worker A's update executes first, advancing `lease_expires_at` to $t_1 + 300\text{s}$. Worker B's update then executes; its condition `lease_expires_at < NOW()` is now **FALSE**. Operation 2 returns `rowcount == 0` for Worker B. Worker B cleanly backs off. Exactly one worker wins.

---

## 7. Transaction-Wide Fencing & Stale-Worker Protection

A critical architectural mandate is that **a stale worker must never persist partial or complete forensic results after losing lease ownership**.

### 7.1 Separation of Gemini Inference from DB Transactions
Database connection pool exhaustion and long-held row locks must be avoided:
1. **Transaction 1 (Claim Phase):** The worker executes Operation 1 (or 2) to claim the lease, commits immediately, and closes the transaction.
2. **Inference Phase (Zero DB Locks):** The worker invokes Google Gemini API via `GeminiLLMAdapter` completely **OUTSIDE** of any database transaction. During the 2s to 90s HTTP wait, no PostgreSQL connections or row locks are held.
3. **Transaction 2 (Validation & Persistence Phase):** When inference completes, the worker opens a single atomic persistence transaction.

### 7.2 Atomic Persistence with Fencing Token Verification
Inside Transaction 2, the worker performs all updates and downstream inserts within a single atomic boundary:

```python
def persist_investigation_results(
    db: Session,
    investigation_id: uuid.UUID,
    worker_lease_token: uuid.UUID,
    result_contract: InvestigationContract,
    conclusion: InvestigationConclusion,
    confidence: InvestigationConfidence,
    active_adapter: BaseLLMAdapter,
    claim_draft_data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Atomically persists investigation findings, conclusion, and claim drafts
    strictly bounded by the worker's fencing token.
    """
    try:
        # Step 1: Conditional Update with Fencing Token Guard
        stmt = (
            update(ForensicInvestigation)
            .where(
                ForensicInvestigation.id == investigation_id,
                ForensicInvestigation.status == InvestigationStatus.IN_PROGRESS.value,
                ForensicInvestigation.lease_token == worker_lease_token,
                ForensicInvestigation.lease_expires_at > sa.func.now(),  # Must not be expired
            )
            .values(
                status=InvestigationStatus.COMPLETED.value,
                conclusion=conclusion.value,
                confidence=confidence.value,
                summary=result_contract.summary,
                investigation_result=result_contract.model_dump(),
                model_provider=active_adapter.provider_name,
                model_name=active_adapter.model_name,
                error_message=None,
                lease_owner_id=None,
                lease_token=None,
                lease_expires_at=None,
                updated_at=sa.func.now(),
            )
        )
        result = db.execute(stmt)

        # Step 2: Strict Row Count Verification
        if result.rowcount != 1:
            raise StaleLeaseError(
                f"Ownership validation failed for investigation {investigation_id}. "
                f"Lease token {worker_lease_token} was superseded, expired, or investigation was terminated. "
                f"Aborting persistence."
            )

        # Step 3: Atomic Downstream Persistence (Claim Drafts / Evidence References)
        # Any claim draft or auxiliary record MUST be persisted in the exact same transaction
        if claim_draft_data:
            draft = ForensicClaimDraft(
                tenant_id=claim_draft_data["tenant_id"],
                exception_id=claim_draft_data["exception_id"],
                investigation_id=investigation_id,
                detection_run_id=claim_draft_data["detection_run_id"],
                draft_number=claim_draft_data.get("draft_number", 1),
                status=ClaimDraftStatus.DRAFT.value,
                dispute_amount=claim_draft_data["dispute_amount"],
                currency=claim_draft_data.get("currency", "INR"),
                target_entity=claim_draft_data["target_entity"],
                target_reference=claim_draft_data["target_reference"],
                claim_summary=claim_draft_data["claim_summary"],
                supporting_facts=claim_draft_data["supporting_facts"],
                evidence_references=claim_draft_data["evidence_references"],
                human_review_status=ClaimDraftReviewStatus.PENDING_HUMAN_REVIEW.value,
            )
            db.add(draft)

        # Step 4: Atomic Commit
        db.commit()

    except Exception:
        # Step 5: Fail-Closed Rollback
        db.rollback()
        raise
```

### 7.3 Complete Prevention of Separate Persistence Paths
- **No Direct Draft Creation:** `ClaimDraftService.create_draft()` must reject any call unless passed a validated investigation whose status is already verified as `COMPLETED`.
- **Foreign Key Dependency:** `ForensicClaimDraft.investigation_id` links to `ForensicInvestigation`. If the investigation update fails, the entire transaction rolls back; no orphaned drafts or evidence references can exist.
- **Fail-Closed Outcome:** If a worker loses its lease (e.g., due to an unhandled 350-second pause), its Transaction 2 detects `rowcount == 0`, raises `StaleLeaseError`, rolls back, and discards all in-memory LLM output.

---

## 8. Strict Lease Renewal (Heartbeat) Policy

### 8.1 Renewal Query Specification
To prevent long-running, legitimate investigations from having their lease stolen while LLM inference is progressing, the worker executes a periodic heartbeat renewal.

```sql
UPDATE forensic_investigations
SET
    lease_expires_at = NOW() + INTERVAL '300 seconds',
    last_heartbeat_at = NOW(),
    updated_at = NOW()
WHERE id = :investigation_id
  AND status = 'IN_PROGRESS'
  AND lease_token = :worker_lease_token
  AND lease_expires_at > NOW();
```

### 8.2 Strict Renewal Rules
1. **Investigation ID Match:** `id == :investigation_id`.
2. **Token Match:** `lease_token == :worker_lease_token`.
3. **Status Match:** `status == 'IN_PROGRESS'`.
4. **Current Expiry Must Be Strictly in the Future:** `lease_expires_at > NOW()`.

**Critical Concurrency Invariant:**  
An expired lease (`lease_expires_at <= NOW()`) **can NEVER be renewed by its former owner**. If the worker experiences a stall such that the lease expires, the query evaluates `lease_expires_at > NOW()` to **FALSE** and returns `rowcount == 0`.  
The worker detects `rowcount == 0`, immediately aborts its background tasks, and cancels any in-flight LLM calls.

---

## 9. Bounded 3-Attempt Retry Accounting & RQ Coordination

To prevent infinite crash loops, the recovery architecture defines a strict three-attempt limit:
- **Attempt 1:** Initial execution claim (Operation 1).
- **Attempt 2:** First recovery reclamation (Operation 2).
- **Attempt 3:** Second recovery reclamation (Operation 2).

```
Attempt 1 (Claim)      ──► Crash / Expiry (300s)
  │
  ▼
Attempt 2 (Reclaim 1)  ──► Crash / Expiry (300s + Backoff)
  │
  ▼
Attempt 3 (Reclaim 2)  ──► Crash / Expiry (300s + Backoff)
  │
  ▼
[ FAILED ] (Terminal)  ──► Permanent fail-closed transition (INCONCLUSIVE, LOW confidence)
```

### 9.1 Database as Authoritative Attempt Counter
- RQ provides queue-level retry mechanisms (e.g., `Retry(max=3)`). However, network hiccups or duplicate delivery can cause RQ to re-deliver jobs without an actual execution attempt having occurred.
- In Finora, **PostgreSQL is the single authoritative source of truth for attempt accounting**.
- `attempt_count` is incremented **only** when SQL Operation 1 or Operation 2 successfully commits a row update.
- If RQ re-delivers a job whose lease is still valid (`lease_expires_at > NOW()`), Operation 1 and 2 both return `rowcount == 0`. `attempt_count` is **not** incremented, and the duplicate delivery is safely discarded.

### 9.2 Exhaustion Transition to FAILED
When an investigation has reached `attempt_count >= 3` and its lease has expired, neither Operation 1 nor Operation 2 can succeed. The scheduled reaper or inspecting worker executes the terminal exhaustion statement:

```sql
UPDATE forensic_investigations
SET
    status = 'FAILED',
    conclusion = 'INCONCLUSIVE',
    confidence = 'LOW',
    error_message = 'Investigation failed: Maximum worker lease recovery attempts (3) exhausted without completion.',
    lease_owner_id = NULL,
    lease_token = NULL,
    lease_expires_at = NULL,
    updated_at = NOW()
WHERE id = :investigation_id
  AND status = 'IN_PROGRESS'
  AND lease_expires_at < NOW()
  AND attempt_count >= 3;
```
- Permanently locks the record in `FAILED` with `INCONCLUSIVE` and `LOW` confidence.
- Existing immutability listeners immediately prevent any further modifications.
- Alerts operational metrics: `forensic_investigation_retries_exhausted_total`.

---

## 10. Reaper Architecture Evaluation & Concurrency Control

To guarantee that expired investigations are reclaimed even if no incoming API requests or duplicate RQ jobs trigger them, a background reaper mechanism is required.

### 10.1 Evaluation of Reaper Architectural Options

| Option | Description | Trade-offs & Evaluation | Recommendation |
| :--- | :--- | :--- | :--- |
| **Option A: RQ Scheduled Job** | An RQ job enqueued periodically (e.g. every 60s) via `rq-scheduler` or cron dispatch. | *Pros:* Reuses existing worker infrastructure; zero new container dependencies.<br>*Cons:* Dependent on Redis availability; if Redis is down, reaper cannot run. | **Preferred for Standard Deployments** |
| **Option B: Dedicated Worker Daemon** | A standalone Python background process running a continuous loop with `time.sleep(60)`. | *Pros:* Direct database communication; functions even during complete Redis outages.<br>*Cons:* Additional container/process to monitor, deploy, and scale. | **Viable for Air-Gapped Environments** |
| **Option C: External Cloud Scheduler** | Kubernetes CronJob or AWS EventBridge calling an internal authenticated API route (`/internal/forensic/reap`). | *Pros:* Cloud-native reliability; independent of worker and API crashes.<br>*Cons:* Cloud-specific infrastructure; requires internal network ingress routing. | **Preferred for Enterprise Kubernetes** |

### 10.2 Recommended Hybrid Reaper Strategy
1. **Application Layer (Development & Standard Production):** An RQ periodic task running every 60 seconds.
2. **Infrastructure Fallback (Enterprise Production):** A Kubernetes CronJob executing every 5 minutes invoking an internal management CLI command: `python -m app.cli reap-orphaned-investigations`.

### 10.3 Concurrency Control across Multiple Reaper Instances
To prevent multiple reaper processes from competing or colliding when scanning expired investigations, the reaper employs PostgreSQL's `FOR UPDATE SKIP LOCKED` pattern:

```sql
WITH expired_jobs AS (
    SELECT id
    FROM forensic_investigations
    WHERE status = 'IN_PROGRESS'
      AND lease_expires_at < NOW()
    ORDER BY lease_expires_at ASC
    LIMIT 50
    FOR UPDATE SKIP LOCKED
)
UPDATE forensic_investigations fi
SET
    status = CASE 
        WHEN fi.attempt_count >= 3 THEN 'FAILED'
        ELSE 'PENDING'
    END,
    conclusion = CASE
        WHEN fi.attempt_count >= 3 THEN 'INCONCLUSIVE'
        ELSE fi.conclusion
    END,
    confidence = CASE
        WHEN fi.attempt_count >= 3 THEN 'LOW'
        ELSE fi.confidence
    END,
    error_message = CASE
        WHEN fi.attempt_count >= 3 THEN 'Investigation failed: Maximum worker lease recovery attempts (3) exhausted.'
        ELSE 'Lease expired. Re-queued for worker pickup by reaper.'
    END,
    lease_owner_id = NULL,
    lease_token = NULL,
    lease_expires_at = NULL,
    updated_at = NOW()
FROM expired_jobs ej
WHERE fi.id = ej.id
RETURNING fi.id, fi.status, fi.attempt_count;
```

### 10.4 Behavior During Redis Outages
- If Redis is down, the reaper directly reads and updates PostgreSQL.
- Investigations with `attempt_count >= 3` are cleanly terminated to `FAILED` in the database.
- Investigations with `attempt_count < 3` can be transitioned to `PENDING` directly in the database. When Redis reconnects, workers or the API dispatcher re-enqueue the `PENDING` records.

---

## 11. Comprehensive Failure-Scenario Matrix

| # | Scenario | Failure Trigger | Concurrency & Recovery Handling | Invariant & Data Integrity Result |
| :---: | :--- | :--- | :--- | :--- |
| **1** | **Crash immediately after claim** | Worker killed by OS (`SIGKILL`) right after Operation 1 commits. | Status is `IN_PROGRESS`, `lease_expires_at = NOW() + 300s`, `attempt_count = 1`. Concurrent claims rejected while lease is valid. At 300s, lease expires. Reaper or worker reclaims via Operation 2 (`attempt_count = 2`). | Clean recovery; zero duplicate work. |
| **2** | **Crash during Gemini inference** | Worker OOM killed during external HTTP request to Gemini. | Request terminates in flight. PostgreSQL connection was closed (Transaction 1). At 300s, lease expires. Next worker re-reads canonical evidence bundle snapshot and re-runs. | Zero partial data committed. |
| **3** | **Crash during database write** | Network disconnect or power cut during Transaction 2. | PostgreSQL automatically rolls back uncommitted transaction. Row remains `IN_PROGRESS`. After lease expiry, reclaimed by next worker. | Strict ACID transaction rollback. |
| **4** | **Unresponsive worker (deadlock / GC pause)** | Worker thread freezes; stops sending heartbeats. | `lease_expires_at` lapses. Worker 2 reclaims row with new token $T_2$. If Worker 1 awakens, its commit with $T_1$ returns `rowcount == 0` and rolls back. | Stale worker write completely blocked. |
| **5** | **Lease expires mid-LLM call** | Gemini takes $>300\text{s}$ and heartbeat failed. | Worker 2 reclaims job ($T_2$). Worker 1 finishes later and attempts commit with $T_1$. Update matches 0 rows; Worker 1 rolls back. Worker 2 completes normally. | Exactly one valid result persisted. |
| **6** | **Concurrent reclamation race** | Two workers attempt to reclaim the same expired row at the same millisecond. | PostgreSQL serializes row updates via row-level lock. Worker A updates row and advances `lease_expires_at`. Worker B's `WHERE lease_expires_at < NOW()` is false (`rowcount == 0`). Worker B backs off. | Exactly one worker wins; no duplicate jobs. |
| **7** | **Stale worker persistence attempt** | Stale worker attempts to write findings with superseded token. | `UPDATE ... WHERE lease_token = :worker_token` matches 0 rows. Code raises `StaleLeaseError` and invokes `db.rollback()`. | Zero corrupted findings. |
| **8** | **DB fails during heartbeat** | Worker calls heartbeat renewal query, but PostgreSQL connection drops. | Worker catches `OperationalError`. If lease expires before reconnect, worker marks lease lost and aborts without writing. | Safe fail-closed abort. |
| **9** | **Redis disconnects mid-job** | Redis restarts while worker is processing. | Worker communicates directly with Gemini and PostgreSQL; does not depend on Redis during active execution. Findings commit successfully to PostgreSQL. | Complete DB independence from queue health. |
| **10**| **Retry limit exhausted** | Worker crashes 3 consecutive times on the same record. | `attempt_count` reaches 3. Reaper transitions row to `FAILED`, `INCONCLUSIVE`, `LOW` confidence. | Crash loop terminated; incident alerted. |

---

## 12. Database Migration Specification

A new Alembic migration (`008_forensic_investigation_leases.py`) will be executed upon implementation approval:

```python
"""add_forensic_investigation_leases

Revision ID: 008_forensic_investigation_leases
Revises: 007_phase5_forensic_investigations
Create Date: 2026-11-15 10:00:00.000000

Phase 5.1-D.1 Migration: Lease-Based Orphaned Investigation Recovery
- Adds lease_owner_id, lease_token, lease_expires_at, attempt_count, last_heartbeat_at.
- Adds partial index ix_forensic_inv_lease_recovery on (status, lease_expires_at).
- Fully backward compatible with existing records.
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column('forensic_investigations', sa.Column('lease_owner_id', sa.String(100), nullable=True))
    op.add_column('forensic_investigations', sa.Column('lease_token', sa.Uuid(), nullable=True))
    op.add_column('forensic_investigations', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('forensic_investigations', sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('forensic_investigations', sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True))
    
    op.create_index(
        'ix_forensic_inv_lease_recovery',
        'forensic_investigations',
        ['status', 'lease_expires_at'],
        postgresql_where=sa.text("status = 'IN_PROGRESS'")
    )

def downgrade() -> None:
    op.drop_index('ix_forensic_inv_lease_recovery', table_name='forensic_investigations')
    op.drop_column('forensic_investigations', 'last_heartbeat_at')
    op.drop_column('forensic_investigations', 'attempt_count')
    op.drop_column('forensic_investigations', 'lease_expires_at')
    op.drop_column('forensic_investigations', 'lease_token')
    op.drop_column('forensic_investigations', 'lease_owner_id')
```

---

## 13. Comprehensive Testing Strategy

All concurrency, transaction isolation, and row locking tests must run against **PostgreSQL 17** (`finora_test`). Fast state-machine logic and schema validation tests run against unit/SQLite environments.

### 13.1 Test Matrix

| Test Identifier | Test Name | Environment | Concurrency & Validation Objective |
| :--- | :--- | :--- | :--- |
| **TEST-REC-01** | `test_initial_lease_acquisition` | SQLite / Unit | Operation 1 transitions `PENDING` -> `IN_PROGRESS`, sets UUID token, duration, and `attempt_count = 1`. |
| **TEST-REC-02** | `test_valid_lease_rejects_concurrent_claims` | PostgreSQL 17 | While `lease_expires_at > NOW()`, concurrent claims return 0 rows. |
| **TEST-REC-03** | `test_expired_worker_cannot_renew_its_lease` | PostgreSQL 17 | Worker with `lease_expires_at <= NOW()` calls heartbeat renewal; query returns `rowcount == 0`. |
| **TEST-REC-04** | `test_expired_lease_reclaimed_by_second_worker` | PostgreSQL 17 | Set mock clock past expiry; Operation 2 reclaims lease with fresh token and `attempt_count = 2`. |
| **TEST-REC-05** | `test_concurrent_reclamation_race_condition` | PostgreSQL 17 | 10 parallel threads execute Operation 2 on the same expired row. Exactly 1 thread succeeds; 9 threads return `rowcount == 0`. |
| **TEST-REC-06** | `test_stale_worker_cannot_overwrite_investigation_results`| PostgreSQL 17 | Worker A with token $T_1$ calls persistence after Worker B reclaimed with $T_2$. Update matches 0 rows; raises `StaleLeaseError`. |
| **TEST-REC-07** | `test_stale_worker_cannot_insert_evidence` | PostgreSQL 17 | Verify stale worker cannot add unlinked or fabricated evidence records. |
| **TEST-REC-08** | `test_stale_worker_cannot_create_claim_drafts` | PostgreSQL 17 | Verify stale worker persistence rollback prevents any row insertion into `forensic_claim_drafts`. |
| **TEST-REC-09** | `test_ownership_validation_and_persistence_rollback_atomic` | PostgreSQL 17 | Verify that investigation findings update and claim draft insert are in the same transaction, rolling back atomically on fencing failure. |
| **TEST-REC-10** | `test_heartbeat_renewal_extends_lease` | PostgreSQL 17 | Active worker calls heartbeat while valid; `lease_expires_at` advances by 300s without altering `attempt_count`. |
| **TEST-REC-11** | `test_attempt_count_cannot_exceed_three` | PostgreSQL 17 | Simulate 3 successive worker crashes; verify attempts increment 1 -> 2 -> 3, and a 4th claim/reclaim is strictly rejected. |
| **TEST-REC-12** | `test_retry_exhaustion_transitions_to_failed` | PostgreSQL 17 | Reaper evaluates expired row with `attempt_count = 3`; transitions atomically to `FAILED`, `INCONCLUSIVE`, `LOW` confidence. |
| **TEST-REC-13** | `test_concurrent_reapers_cannot_reclaim_the_same_investigation` | PostgreSQL 17 | 5 concurrent reaper jobs query expired rows using `FOR UPDATE SKIP LOCKED`; zero duplicate re-enqueues. |
| **TEST-REC-14** | `test_completed_investigations_cannot_be_reclaimed` | PostgreSQL 17 | Verify that investigations in `COMPLETED`, `BLOCKED`, or `FAILED` reject all lease claims, renewals, or reaper updates. |
| **TEST-REC-15** | `test_evidence_bundle_immutable_during_recovery` | PostgreSQL 17 | Cryptographic bundle fingerprint and snapshot are identical across initial claim and multiple recoveries. |
| **TEST-REC-16** | `test_tenant_isolation_in_recovery` | PostgreSQL 17 | Recovery queries and reaper actions strictly enforce `tenant_id` boundaries. |

---

## 14. Security and Financial Integrity Analysis

### 14.1 Strict Preservation of Financial Integrity
- **Zero AI Math:** At no point in the recovery lifecycle does the AI perform calculations or modify ledger balances. The recovery mechanism only manages worker execution leases.
- **Evidence Immutability:** The cryptographic snapshot `evidence_bundle_snapshot` is constructed once during initial creation and remains immutable. A recovering worker evaluates the exact same canonical evidence bundle.
- **Dispute Amount Invariance:** Any subsequent claim draft generated after recovery takes its `dispute_amount` strictly from `LeakageException.recoverable_amount` via deterministic copying.

### 14.2 Tenant Isolation
All recovery operations filter by `tenant_id` or query specific investigation UUIDs that belong to verified tenant memberships. Reclaiming an investigation does not expose cross-tenant boundaries.

### 14.3 Audit Trail Preservation
`attempt_count`, `last_heartbeat_at`, and error messages document the full operational history of retries, providing complete observability for SOC2/ISO financial platform compliance.

---

## 15. Implementation Risks and Trade-offs

| Risk | Impact | Likelihood | Mitigation Strategy |
| :--- | :--- | :--- | :--- |
| **Clock Drift across Nodes** | Worker clock differs from DB server clock | Low (NTP standard) | Use database server clock (`NOW()`) exclusively in SQL statements rather than application server time. |
| **Premature Lease Expiry during High Load** | Heavy GC pause or LLM delay causes valid worker to lose lease | Low | Generous 300s lease duration + 60s asynchronous background heartbeat renewal. |
| **Reaper Process Contention** | Multiple scheduled reapers run concurrently across API pods | Medium | Reaper uses `SELECT ... FOR UPDATE SKIP LOCKED` or the atomic `UPDATE ... WHERE ... RETURNING` pattern. |
| **Database Connection Exhaustion** | Frequent heartbeats consume connection pool | Low | Heartbeat uses lightweight single-row update via existing thread connection; heartbeat interval capped at 60s. |

---

## 16. Final Architecture Review and Implementation Acceptance Criteria

This section establishes the definitive, binding technical requirements that must be met during Phase 5.1-D.1 implementation.

### Criterion 1: Transaction-Wide Fencing & Stale-Worker Protection
- [ ] **External Inference Isolation:** External Google Gemini API calls must be executed completely outside of any active database transaction. No PostgreSQL connection or row lock may be held during LLM network wait.
- [ ] **Pre-Persistence Lease Validation:** Before persisting findings, the worker must verify that its `lease_token` matches the database row and that `lease_expires_at > NOW()`.
- [ ] **Atomic Persistence Transaction:** Investigation status (`COMPLETED`), findings JSON, summary, confidence, model provenance, and any associated `ForensicClaimDraft` record must be persisted in a **single database transaction**.
- [ ] **Row Count Verification:** The update statement must assert `result.rowcount == 1`. If `rowcount != 1`, the worker must raise `StaleLeaseError`.
- [ ] **Fail-Closed Rollback:** On `StaleLeaseError` or any persistence failure, `db.rollback()` must be invoked immediately. Zero claim drafts, evidence references, or partial findings may remain in the database.
- [ ] **Prevention of Separate Persistence Paths:** `ClaimDraftService.create_draft()` must reject invocation on any investigation not confirmed as `COMPLETED`.

### Criterion 2: Strict Lease Renewal (Heartbeat)
- [ ] **Renewal Query Guard:** Heartbeat renewal must require `id == :id AND status == 'IN_PROGRESS' AND lease_token == :worker_token AND lease_expires_at > NOW()`.
- [ ] **Expired Renewal Prohibition:** If `lease_expires_at <= NOW()`, the renewal update must evaluate to `rowcount == 0`. An expired lease can never be renewed by its former owner.
- [ ] **Immediate Worker Termination:** When a heartbeat renewal returns `rowcount == 0`, the worker must immediately abort background tasks and cancel active LLM calls.

### Criterion 3: Separate Claim and Reclaim Operations
- [ ] **Discrete Initial Claim (Operation 1):** Dedicated function `claim_pending_investigation()` targets `status = 'PENDING' AND attempt_count = 0`. Increments `attempt_count` to 1. Sets initial `lease_token`.
- [ ] **Discrete Expired Reclaim (Operation 2):** Dedicated function `reclaim_expired_investigation()` targets `status = 'IN_PROGRESS' AND lease_expires_at < NOW() AND attempt_count < 3`. Increments `attempt_count` by 1. Generates fresh UUID `lease_token`.
- [ ] **Concurrency Safety:** Both operations must execute as single atomic conditional `UPDATE ... RETURNING` statements in PostgreSQL.

### Criterion 4: Strict 3-Attempt Retry Accounting
- [ ] **Attempt Ceiling:** Exactly three attempts are permitted (Attempt 1: Initial claim, Attempt 2: First recovery, Attempt 3: Second recovery).
- [ ] **Database as Source of Truth:** `attempt_count` in PostgreSQL is the authoritative counter; transport-level RQ re-deliveries must not increment `attempt_count` if the active lease is valid.
- [ ] **Exhaustion Transition:** If an investigation fails or expires with `attempt_count >= 3`, it must transition permanently to `status = 'FAILED'`, `conclusion = 'INCONCLUSIVE'`, and `confidence = 'LOW'`.

### Criterion 5: Idempotent Reaper Architecture
- [ ] **Concurrency Protection:** The scheduled reaper must query expired records using `SELECT ... FOR UPDATE SKIP LOCKED` or atomic conditional updates, preventing multiple reaper instances from contending on or re-enqueuing the same investigation.
- [ ] **Redis Disconnect Resilience:** During Redis downtime, the reaper must continue to clean up and transition exhausted records (`attempt_count >= 3`) to `FAILED` directly in PostgreSQL.

### Criterion 6: Immutability and Financial Invariants
- [ ] **Zero Financial Modification:** AI and worker recovery logic must never modify amounts, balances, or status of `LeakageException`, `canonical_payments`, or other financial records.
- [ ] **Evidence Integrity:** The original `evidence_bundle_snapshot` and `evidence_bundle_fingerprint` must remain strictly immutable across all recovery cycles.
- [ ] **Terminal State Locking:** Once an investigation reaches `COMPLETED`, `BLOCKED`, or `FAILED`, all claim, reclaim, renewal, or reaper operations must be strictly rejected.

### Criterion 7: PostgreSQL 17 Automated Verification
- [ ] **Comprehensive Suite:** All 16 automated tests defined in Section 13 must pass with 100% success against PostgreSQL 17 (`finora_test`).
