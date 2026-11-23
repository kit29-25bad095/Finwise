# Finora — Production Database Audit & PostgreSQL Reliability Report

**Document Reference:** `PR-REP-003`  
**Classification:** Workstream 2 — Database Reliability, PostgreSQL Readiness & DR Audit  
**Date:** November 13, 2026  
**Auditor Roles:** Senior PostgreSQL DBA, Financial Database Reliability Engineer  
**Branch:** `chore/production-readiness`  

---

## 1. Executive Summary & Verification Classification

This report audits Workstream 2: Database architecture, SQLAlchemy 2.0 ORM models, Alembic migrations, PostgreSQL readiness, connection pooling, SSL enforcement, and automated backup/restore verification.

### Subsystem Classification Status

| Component | Status | Classification |
|---|---|---|
| **SQLAlchemy 2.0 ORM Models** | Pure Decimal mapping (`NUMERIC(18, 4)`), zero floats | **IMPLEMENTED** |
| **Alembic Migration History** | Revisions 001 through 007 verified to Head | **TESTED LOCALLY** |
| **PostgreSQL Compatibility** | Dialect branching, widened version column (128 chars) | **IMPLEMENTED** |
| **Connection Pooling & Timeouts** | `pool_size=20`, `max_overflow=10`, `pool_recycle=1800` | **IMPLEMENTED** |
| **SSL Enforcement Setting** | `DB_SSL_MODE` setting configured (`sslmode=require`) | **IMPLEMENTED** |
| **Foreign Key Constraints** | `PRAGMA foreign_keys=ON` (SQLite); native FKs (Postgres) | **TESTED LOCALLY** |
| **Disaster Recovery Engine** | `DatabaseBackupManager` (SQLite atomic API & `pg_dump -Fc`) | **IMPLEMENTED** |
| **Disaster Recovery Restore Drill** | Catastrophic data purge and full restoration verified | **TESTED LOCALLY** |
| **Managed Cloud PostgreSQL Instance** | Not provisioned in local sandbox environment | **PENDING CONFIGURATION / BLOCKED** |

---

## 2. Model Audit & Financial Precision

### 2.1 Authoritative Pure Decimal Types
All financial fields across all models are declared strictly as `NUMERIC(18, 4)` and mapped to Python `decimal.Decimal`:
- `canonical_orders`: `gross_amount` (`NUMERIC(18, 4)`)
- `canonical_payments`: `captured_amount`, `reported_fee`, `reported_tax`, `unallocated_balance` (`NUMERIC(18, 4)`)
- `canonical_settlements`: `gross_amount`, `net_amount`, `fee_amount`, `tax_amount`, `unallocated_balance` (`NUMERIC(18, 4)`)
- `canonical_bank_transactions`: `credit_amount`, `debit_amount`, `balance_after_transaction`, `unallocated_balance` (`NUMERIC(18, 4)`)
- `reconciliation_matches`: `matched_amount`, `discrepancy_amount` (`NUMERIC(18, 4)`)
- `reconciliation_allocations`: `allocated_amount` (`NUMERIC(18, 4)`)
- `fee_contracts` & `fee_schedule_tiers`: `gst_rate`, `percentage_rate`, `fixed_fee_per_txn` (`NUMERIC(18, 4)`)
- `leakage_run_exceptions`: `leakage_amount` (`NUMERIC(18, 4)`)

Binary floating-point types (`FLOAT`, `REAL`, `DOUBLE PRECISION`) are 100% absent from all financial calculations and persistence schemas.

### 2.2 Data Immutability & Retention
- **Finalized Runs:** `leakage_run_exceptions` and `reconciliation_matches` use listeners that prohibit updates or deletions on finalized runs.
- **Tenant Deletion Safeguard:** Foreign key constraints with `ON DELETE RESTRICT` block deletion of a tenant if active investigations, audit records, or financial history exist.

---

## 3. Alembic Migration History & Dialect Compatibility

### Migration Sequence (001 to 007 Head)
```
001_initial_phase1_models
  └─> 002_phase2_ingestion_and_canonical_models
        └─> 003_phase3_reconciliation_and_fee_models
              └─> 004_phase4_leakage_detection_models
                    └─> 005_phase4_evidence_and_lineage
                          └─> 006_tenant_financial_history_retention
                                └─> 007_phase5_forensic_investigations (HEAD)
```

### PostgreSQL Migration Patch (`alembic_utils.py`)
Standard Alembic creates `alembic_version.version_num` as `VARCHAR(32)`. Finora's descriptive revision identifiers (e.g., `006_tenant_financial_history_retention` = 38 chars) would cause standard PostgreSQL migrations to fail.
- **Remediation:** `app/core/alembic_utils.py` executes `ensure_version_column_capacity(connection, length=128)` and `patch_alembic_version_table(length=128)` on engine initialization.
- **Alembic Config:** Added `path_separator = os` in `alembic.ini` to eliminate deprecation warnings on Windows.

---

## 4. Connection Pooling & Production PostgreSQL Configuration

Configured in `app/core/database.py` and `app/core/config.py`:
```python
engine_kwargs = {
    "pool_pre_ping": True,       # Tests connection liveness before checkout
    "pool_size": 20,              # Persistent connection pool size
    "max_overflow": 10,           # Burst capacity above pool_size
    "pool_timeout": 30,           # Seconds to wait before raising TimeoutError
    "pool_recycle": 1800,         # Recycles connections every 30 minutes to prevent stale TCP sockets
}
if settings.DB_SSL_MODE:
    engine_kwargs["connect_args"] = {"sslmode": settings.DB_SSL_MODE}  # e.g., 'require' or 'verify-full'
```

---

## 5. Backup & Disaster Recovery Verification Drill

Tested via `backend/tests/test_phase7_backup_restore.py`:
1. **Primary Seed:** Seeded canonical orders and payments with exact `Decimal("1500.5000")` values.
2. **Snapshot Creation:** Executed `DatabaseBackupManager.backup_sqlite()`, generating atomic snapshot and SHA-256 JSON manifest.
3. **Catastrophic Purge:** Executed `DELETE FROM canonical_orders` and `DELETE FROM canonical_payments`. Verified 0 records remained in primary database.
4. **Restoration Drill:** Executed `DatabaseBackupManager.restore_sqlite()` with SHA-256 checksum validation.
5. **Parity Check:** Query confirmed 10/10 orders and 10/10 payments restored with 100% data integrity and exact Decimal values (`Decimal("1500.5000")`, `Decimal("28.5000")`).

### Operational Recovery Targets
- **Recovery Point Objective (RPO):** $\le 1$ hour via automated hourly snapshots; $< 5$ minutes with WAL-G continuous archiving.
- **Recovery Time Objective (RTO):** $\le 15$ minutes for automated restoration.

---

## 6. PostgreSQL Migration & Rollback Runbook

### Running Migrations to Head
```bash
cd backend
python -m alembic upgrade head
```

### Checking Current Migration Revision
```bash
cd backend
python -m alembic current
```

### Disaster Recovery Restore Command (PostgreSQL)
```bash
pg_restore \
  --dbname=postgresql://finora_user:password@localhost:5432/finora_prod \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --verbose \
  finora_pg_backup_<timestamp>.dump
```
