# FINORA — STAGE 02: POSTGRESQL DATABASE READINESS REPORT
## Production Database Architecture, Migration Verification, Disaster Recovery & Security Hardening

**Document ID:** `FINORA-STAGE-02-DATABASE-READINESS`  
**Version:** `1.0.0`  
**Status:** `CONDITIONALLY READY FOR MANAGED CLOUD PROVISIONING`  
**Date:** `2026-11-22`  
**Classification:** Financial Core / PostgreSQL 17 / Production Readiness  
**Lead Role:** Senior PostgreSQL Database Architect  
**Target Engine:** PostgreSQL 17.12 (64-bit)  
**Regression Test Status:** **296 / 296 PASSED (100%)**

---

## 1. Executive Summary

This report documents the architectural audit, migration validation, disaster recovery benchmarking, and security hardening executed for **Stage 02: PostgreSQL Database Readiness** of the Finora Financial Reconciliation Engine.

Finora processes mission-critical financial data for Indian D2C e-commerce merchants across Shopify, Razorpay, Cashfree, Delhivery, Bluedart, and bank statement feeds. The database architecture must guarantee strict ACID compliance, arbitrary-precision currency representation (`NUMERIC(18, 4)`), immutable audit and forensic records, durable multi-tenant isolation, automated disaster recovery, and non-destructive schema evolution.

### Key Readiness Findings & Verified Capabilities
1. **Unbroken Sequential Migration Chain:** Verified 8 sequential Alembic migrations from `<base>` (`001_initial_phase1`) to `HEAD` (`008_forensic_investigation_leases_and_outbox`).
2. **Clean Database Migration:** Successfully migrated a brand-new, empty PostgreSQL database from 0 to HEAD without errors. All 27 application and audit tables were created cleanly.
3. **Zero Data Loss on Populated Migrations:** Seeded complex financial records at revision 007 and upgraded to HEAD (008). 100% of rows and exact monetary values were preserved without truncation, schema distortion, or orphaned records.
4. **Fail-Closed Immutability Protection:** Verified that downgrading past immutable audit revisions (revisions 005 and 006) strictly fails closed (`RuntimeError: strictly prohibited to prevent irreversible data loss`).
5. **Managed Connection Pooling:** Engineered production-grade connection pooling (`DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=20`, `DB_POOL_TIMEOUT=30`, `DB_POOL_RECYCLE=1800`, `DB_POOL_PRE_PING=True`).
6. **Empirical Disaster Recovery (RTO & RPO):**
   - **Empirical RTO (Recovery Time Objective):** Physical restoration drill of an active PostgreSQL 17 custom archive (`pg_restore -Fc`) into an isolated database completed in **0.846 seconds** with 100% data and catalog integrity.
   - **Empirical RPO (Recovery Point Objective):** Architectural target is $\le 15\text{ minutes}$. However, local server catalog inspection confirms `archive_mode = off`. Achieving this target in production mandates enabling continuous Write-Ahead Log (WAL) archiving in managed cloud PostgreSQL (AWS RDS / GCP Cloud SQL PITR).
7. **Full Test Suite Integrity:** **296 / 296 tests passed** (including 5 new production-readiness PostgreSQL integration tests).

---

## 2. SQLAlchemy Model & Alembic Migration Audit

### 2.1 Sequential Revision Graph
The Alembic migration lineage was audited from root to HEAD:

```
[ <base> ]
    │
    ▼
[ 001_initial_phase1 ]                   (Tenants, Users, Memberships, AuditLogs)
    │
    ▼
[ 002_phase2_ingestion ]                 (Ingestion Batches, Source Errors, Canonical Datasets)
    │
    ▼
[ 003_phase3_reconciliation ]            (Contracts, Fee Tiers, Runs, Matches, Allocations)
    │
    ▼
[ 004_phase4_leakage ]                   (Leakage Runs, Exceptions, Evidence, Reviews)
    │
    ▼
[ 005_phase4_evidence_and_lineage ]      (Point-in-time Observations, Run Lineage & SHA-256)
    │
    ▼
[ 006_tenant_financial_history_retention](ON DELETE RESTRICT across 20 tables; alembic_version width 128)
    │
    ▼
[ 007_phase5_forensic_investigations ]   (AI Investigations, Evidence Snapshots, Claim Drafts)
    │
    ▼
[ 008_forensic_investigation_leases_and_outbox ] (HEAD: Lease tokens, Fencing, Outbox Dispatch)
```

### 2.2 Table Inventory (27 Base Tables in PostgreSQL 17)
All 26 SQLAlchemy declarative models registered in `Base.metadata` plus the `alembic_version` catalog table exist in PostgreSQL:

| Table Name | Category | Primary Key | Tenant Foreign Key Rule |
| :--- | :--- | :---: | :---: |
| `alembic_version` | Migration Catalog | N/A | N/A |
| `tenants` | Multi-Tenancy Core | UUID | Root Entity |
| `users` | Identity & RBAC | UUID | N/A |
| `tenant_memberships` | RBAC Association | UUID | `ON DELETE CASCADE` |
| `audit_logs` | System Audit Trail | UUID | `ON DELETE RESTRICT` |
| `ingestion_batches` | Data Ingestion | UUID | `ON DELETE RESTRICT` |
| `source_row_errors` | Ingestion Quarantining | UUID | `ON DELETE RESTRICT` |
| `canonical_orders` | Financial Orders | UUID | `ON DELETE RESTRICT` |
| `canonical_payments` | Gateway Captures | UUID | `ON DELETE RESTRICT` |
| `canonical_refunds` | Payment Refunds | UUID | `ON DELETE RESTRICT` |
| `canonical_settlements` | Gateway Batches | UUID | `ON DELETE RESTRICT` |
| `canonical_bank_transactions` | Bank Statements (HDFC) | UUID | `ON DELETE RESTRICT` |
| `fee_contracts` | Gateway Contracts | UUID | `ON DELETE RESTRICT` |
| `fee_schedule_tiers` | Tiered Rate Cards | UUID | `ON DELETE RESTRICT` |
| `reconciliation_runs` | Reconciliation Sessions | UUID | `ON DELETE RESTRICT` |
| `reconciliation_matches` | Transaction Matches | UUID | `ON DELETE RESTRICT` |
| `reconciliation_allocations`| Conservation Allocations| UUID | `ON DELETE RESTRICT` |
| `reconciliation_run_deltas` | Historical Differences | UUID | `ON DELETE RESTRICT` |
| `leakage_detection_runs` | Leakage Engine Runs | UUID | `ON DELETE RESTRICT` |
| `leakage_exceptions` | Detected Leakages | UUID | `ON DELETE RESTRICT` |
| `leakage_exception_evidence`| Cryptographic Evidence | UUID | `ON DELETE RESTRICT` |
| `leakage_exception_reviews` | Human Review Logs | UUID | `ON DELETE RESTRICT` |
| `leakage_run_evidence` | Run Evidence Mappings | UUID | `ON DELETE RESTRICT` |
| `leakage_run_exceptions` | Historical Lineage | UUID | `ON DELETE RESTRICT` |
| `forensic_investigations` | AI Forensic Analyses | UUID | `ON DELETE RESTRICT` |
| `forensic_claim_drafts` | Human-Reviewable Claims | UUID | `ON DELETE RESTRICT` |
| `forensic_dispatch_outbox`| Transactional Outbox | UUID | `ON DELETE RESTRICT` |

### 2.3 Financial Column Precision Audit
Across all 27 tables, 56 numeric columns were audited for fractional scale and precision:
- **50 Monetary Amounts:** Strictly defined as `NUMERIC(18, 4)`. Up to 14 integral digits and exactly 4 fractional decimal places to model Indian rupees down to a hundredth of a paisa (e.g. `gross_amount`, `captured_amount`, `leakage_amount`, `allocated_amount`, `dispute_amount`).
- **4 Percentage & Fee Rates:** Configured as `NUMERIC(8, 6)` to support micro-basis points (e.g. `gst_rate = 0.180000`, `rolling_reserve_percentage = 0.050000`).
- **1 Confidence Metric:** Configured as `NUMERIC(6, 4)` for `confidence_score` ($0.0000$ to $1.0000$).
- **1 Tenant Threshold:** Configured as `NUMERIC(10, 4)` for `fee_overcharge_tolerance`.

---

## 3. Managed PostgreSQL Connection Configuration

Finora's backend persistence layer in `app/core/config.py` and `app/core/database.py` has been enhanced with environment-driven pooling parameters for cloud-managed PostgreSQL:

```python
# app/core/config.py
class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg2://user:pwd@db-host:5432/finora"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://user:pwd@db-host:5432/finora"
    
    # Managed PostgreSQL Connection Pool Settings
    DB_POOL_SIZE: int = 10           # Steady-state connection pool size
    DB_MAX_OVERFLOW: int = 20        # Burst capacity connections
    DB_POOL_TIMEOUT: int = 30        # Seconds to wait before timing out on pool checkout
    DB_POOL_RECYCLE: int = 1800      # Recycle connections every 30 mins to prevent stale TCP drops
    DB_POOL_PRE_PING: bool = True    # Health-check connections before checkout (avoids closed-socket errors)
    DB_ECHO: bool = False            # SQL statement echo (disabled in production)
    DB_SSL_MODE: Optional[str] = None # e.g. "require", "verify-ca", "verify-full"
```

### Production Validation Rules Enforced
In `Settings.validate_production_settings()`, the application fails to start if:
- `DATABASE_URL` contains `sqlite` (strict PostgreSQL requirement).
- `WORKER_FALLBACK_SYNC` is `True` (prevents worker fallback from starving API request threads).
- `SECRET_KEY` is default or $< 32$ characters.
- `AI_API_KEY` is missing when `AI_PROVIDER` is `gemini`.

---

## 4. Database Migration Benchmarks

### 4.1 Clean Database Migration Benchmark (000 $\to$ HEAD)
An isolated test database (`finora_migration_clean_test`) was provisioned on PostgreSQL 17 to test cold-start schema provisioning:
- **Starting State:** Clean database created with `TEMPLATE template1`.
- **Command:** `alembic upgrade head`
- **Duration:** 1.84 seconds.
- **Outcome:** **SUCCESS.** All 8 revisions executed sequentially.
- **Verification:** System catalogs confirmed 27 tables, 56 numeric columns, 66 foreign keys (23 `RESTRICT` to `tenants`), and 113 indexes.
- **Teardown:** Clean test database terminated and dropped without residual locks.

### 4.2 Populated Database Migration Benchmark (007 $\to$ HEAD)
An isolated populated database (`finora_migration_populated_test`) was provisioned at revision 007 (`007_phase5_forensic_investigations`). Complete business objects were seeded:
- 1 Tenant (`Populated Test Merchant`, slug `pop-XXXXXX`)
- 1 User (`pop@merchant.com`) and Tenant Membership
- 1 Ingestion Batch (`orders_2026.csv`, 10 rows)
- 1 Canonical Order (`ORD-9999`, Gross: `15000.7500`, Tax: `2700.0000`, Total: `17350.5000`)
- 1 Canonical Payment (`PAY-9999`, Captured: `17350.5000`, Fee: `347.0100`, Tax: `62.4618`)
- 1 Leakage Run and Exception (`FEE_OVERCHARGE`, Leakage: `250.0000`)
- 1 Forensic Investigation (`COMPLETED`, Confidence: `HIGH`, Snapshot: `{"facts": [...]}`)
- 1 Forensic Claim Draft (`DRAFT`, Dispute: `250.0000`)

#### Upgrade Execution & Data Preservation:
- **Command:** `alembic upgrade head` (Applies migration 008)
- **Result:** **SUCCESS.**
- **Integrity Audit Post-Upgrade:**
  * `tenants`: 1 row (100% preserved)
  * `canonical_orders`: 1 row (Gross: `15000.7500`, Total: `17350.5000` exact Decimal match)
  * `canonical_payments`: 1 row (`17350.5000` exact Decimal match)
  * `leakage_exceptions`: 1 row (`250.0000` exact Decimal match)
  * `forensic_investigations`: New lease columns populated with defaults (`attempt_count = 0`, `lease_owner_id = None`, `lease_token = None`, `lease_expires_at = None`).
  * `forensic_dispatch_outbox`: Table operational with 0 rows.
- **Downgrade Security Test:** Attempting to downgrade from 007 to 005 was blocked with `RuntimeError: strictly prohibited to prevent irreversible data loss`. Fail-closed downgrade behavior confirmed.

---

## 5. Automated Backup & Physical Restoration Drill

### 5.1 Automated Backup Utility
Authored `backend/scripts/backup_postgres.py` implementing automated, verifiable physical backups:
- **Archive Format:** PostgreSQL Custom Compressed Archive (`pg_dump -Fc`).
- **Flags:** `--no-owner --no-privileges` to ensure portability across environments and roles.
- **Integrity Validation:** Every backup automatically executes `pg_restore --list` to verify table, sequence, index, and constraint catalog readability.
- **Manifest Generation:** Produces a `.meta.json` companion file containing UTC timestamp, byte size, execution duration, catalog object count, and SHA-256 digest.
- **Retention Pruning:** Automatically prunes daily dumps older than 7 days.

### 5.2 Physical Restoration Drill Execution & Empirical RTO
A full restoration drill was executed into an isolated database (`finora_restore_test`):

```
┌────────────────────────────────────────────────────────┐
│ 1. Active Test Database (finora_test)                 │
│    Size: 113,814 bytes (111.15 KB)                     │
│    Objects: 234 Catalog Items                          │
└────────────────────────────────────────────────────────┘
                            │
              pg_dump -Fc   ▼  (Duration: 0.450s)
┌────────────────────────────────────────────────────────┐
│ 2. Backup Archive (finora_test_20261122_101037.dump)   │
│    SHA-256: A538B04243E3A1591502A0763607D8F82CBFE0... │
└────────────────────────────────────────────────────────┘
                            │
             pg_restore     ▼  (Duration: 0.846s)
┌────────────────────────────────────────────────────────┐
│ 3. Isolated Restore Database (finora_restore_test)     │
│    - Status: 100% RESTORED                             │
│    - Alembic Head: 008                                 │
│    - Tables: 27 / 27 matching                          │
│    - Row Counts: Exact 1:1 match across all 27 tables  │
│    - Foreign Keys: All 24 tenant FKs preserved         │
│    - Indexes: 113 / 113 matching                       │
└────────────────────────────────────────────────────────┘
```

#### Empirical RTO Measurement
$$\text{Empirical Restore Duration (RTO)} = 0.846\text{ seconds}$$
- **Data Throughput:** Full schema reconstitution and table population executed in under 1 second.
- **Scaling Projection:** In a production 10 GB database, restoration via `pg_restore` on standard cloud NVMe storage ($\approx 75\text{ MB/s}$) is projected at $\approx 135\text{ seconds}$ ($\approx 2.25\text{ minutes}$), well within the production recovery threshold ($\le 30\text{ minutes}$).

---

## 6. Empirical RPO Analysis

$$\begin{aligned}
\text{Archival Frequency} &= \text{Continuous WAL Archiving} \\
\text{Target RPO} &\le 15\text{ minutes} \\
\text{Actual Local Host Configuration} &= \text{archive\_mode = off (UNVERIFIED)}
\end{aligned}$$

### Critical RPO Reality Assessment
1. **Logical Backups Alone Cannot Satisfy 15-Minute RPO:** A daily `pg_dump` executed at 02:00 UTC leaves an operational RPO window of up to **24 hours of data loss** if disaster strikes at 01:59 UTC.
2. **Current Host State:** System catalog query `SHOW archive_mode;` on the local PostgreSQL instance returned `off`.
3. **Mandatory Production Architecture:**
   - To achieve the target $\text{RPO} \le 15\text{ minutes}$, the production deployment must use a managed PostgreSQL service with continuous Point-in-Time Recovery (PITR) or configure:
     ```ini
     # postgresql.conf
     wal_level = replica
     archive_mode = on
     archive_command = 'test ! -f /mnt/wal_archive/%f && cp %p /mnt/wal_archive/%f'
     archive_timeout = 900  # Force WAL segment switch every 15 minutes (900 seconds)
     ```
   - Cloud providers (AWS RDS / GCP Cloud SQL) maintain continuous transaction log streaming to cloud object storage (S3/GCS), delivering an effective RPO of $< 5\text{ minutes}$.

---

## 7. Database Permissions & Least Privilege Access Control

### 7.1 Role Privilege Matrix
A security audit of database roles was conducted against PostgreSQL system catalogs (`pg_roles`, `pg_shadow`, `information_schema.role_table_grants`):

| Role Name | Superuser | Create DB | Production Access Scope | Principle of Least Privilege Recommendation |
| :--- | :---: | :---: | :--- | :--- |
| `postgres` | **YES** | **YES** | System Superuser | **Strictly prohibited** from application configuration. Restrict to DBA emergency maintenance via IAM / bastion host. |
| `orbitra_user` | **YES** | **YES** | External Dev Superuser | **Prohibited** from Finora environments. Segregate or remove on dedicated hosts. |
| `finora_migrator` | NO | NO | CI/CD Pipeline / Alembic Runner | Owns application schema. Granted DDL permissions (`CREATE TABLE`, `ALTER TABLE`, `DROP INDEX`). Does not run web workers. |
| `finora_app` | NO | NO | FastAPI & RQ Worker Runtime | Granted `SELECT`, `INSERT`, `UPDATE`, `DELETE` on tables, `USAGE` on sequences. **`REVOKE TRUNCATE`** and **`REVOKE DROP`** to prevent catastrophic data wipes. |

### 7.2 Production Network & Transport Security Standards
1. **SSL/TLS Mandatory:** `ssl = on` with `ssl_min_protocol_version = 'TLSv1.3'`. Client connection strings must specify `sslmode=require` or `sslmode=verify-full`.
2. **VPC Subnet Isolation (`pg_hba.conf`):** PostgreSQL must bind exclusively to private VPC IP addresses (e.g. `10.0.x.x`). Database port 5432 must never be exposed to public subnets (`0.0.0.0/0`).
3. **SCRAM-SHA-256 Authentication:** Password encryption must enforce `scram-sha-256` rather than obsolete `md5`.
4. **Statement Timeouts:** Configure `statement_timeout = 30000` (30 seconds) in `postgresql.conf` to prevent poorly planned queries from monopolizing connection pool workers.

---

## 8. Full Regression Test Matrix

```
========================================================================================
FULL TEST SUITE EXECUTION SUMMARY:
========================================================================================
Total Test Items Collected:   296
Passed:                       296
Failed:                         0
Skipped:                        0
Warnings:                      10 (Deprecations only)
Execution Duration:           96.98s
Pass Rate:                   100.0%
========================================================================================
```

### New Production Readiness PostgreSQL Integration Tests:
1. `test_managed_postgres_connection_pooling_and_pre_ping` — **PASSED**
2. `test_postgres_numeric_precision_exact_roundtrip` — **PASSED**
3. `test_postgres_all_23_durable_tables_tenant_restrict` — **PASSED**
4. `test_postgres_tenant_isolation_boundary` — **PASSED**
5. `test_postgres_migration_schema_metadata_consistency` — **PASSED**

---

## 9. Unresolved Operational Risks & Production Prerequisites

Prior to public go-live deployment, the following operational gates must be certified by the Cloud Infrastructure and Database Administration team:

> [!WARNING]
> ### 1. Continuous WAL Archiving Inactive on Development Host
> `archive_mode` is currently `off` on this host. The $\le 15$-minute RPO is an architectural requirement, not an operational reality until continuous WAL archiving or cloud-managed PITR (AWS RDS / GCP Cloud SQL) is provisioned.

> [!IMPORTANT]
> ### 2. Production Role Separation (Migrator vs Runtime)
> In local development/staging, `finora_staging` owns the tables and runs both DDL (Alembic) and DML (FastAPI). In production, separate `finora_migrator` (DDL owner) from `finora_app` (DML only, `REVOKE TRUNCATE`) to prevent runtime compromise from executing destructive schema alterations.

> [!IMPORTANT]
> ### 3. Immutability Triggers Pending Administrative Deployment
> Database-level triggers for forensic immutability have been verified in integration tests, but are not permanently installed in persistent system catalogs. They require deployment by a database administrator via `scripts/deploy_immutability_triggers.sql`.

---

**Report Certification:**  
*Senior PostgreSQL Database Architect*  
*Finora Project Team — 2026-11-22*
