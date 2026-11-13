# Finora — QA Project Reconnaissance Report

**Date:** 2026-11-13  
**QA Lead:** Autonomous QA Engine  
**Scope:** Full enterprise QA — Phases 1–15

---

## 1. Repository State

| Item | Value |
|---|---|
| Latest Commit | `9c4898f` feat(gemini): complete real Google Gemini 2.0 API integration |
| Branch | `main` |
| Git Status | Clean (no uncommitted changes) |
| Total Commits | 15+ (Phase 0–8) |

---

## 2. Project Architecture

### Backend
| Component | Technology | Version |
|---|---|---|
| Framework | FastAPI | ≥0.115.0 |
| ASGI Server | Uvicorn | ≥0.30.0 |
| ORM | SQLAlchemy | ≥2.0.30 |
| Migrations | Alembic | ≥1.13.0 (7 migrations) |
| Auth | python-jose JWT + bcrypt | ≥3.3.0 |
| AI | google-genai (Gemini 2.0 Flash) | ≥0.1.0 |
| Background Jobs | RQ + Redis (falls back sync) | ≥1.16.0 |
| Test Framework | pytest + pytest-asyncio + hypothesis | 9.1.1 |
| Database (dev) | SQLite | finora.db |
| Database (prod) | PostgreSQL | async via asyncpg |

### Frontend
| Component | Technology |
|---|---|
| Framework | Next.js 14.2.35 |
| Language | TypeScript (strict) |
| Port | 3100 |
| Pages | 15 dashboard routes + login |

---

## 3. API Inventory (49 endpoints)

### Auth (3)
- POST `/api/v1/auth/register`
- POST `/api/v1/auth/login`
- GET `/api/v1/auth/me`

### Dashboard (6)
- GET `/api/v1/dashboard/overview`
- GET `/api/v1/dashboard/leakage-findings`
- GET `/api/v1/dashboard/review-queue`
- GET `/api/v1/dashboard/fee-analytics`
- GET `/api/v1/dashboard/ai-investigations`
- GET `/api/v1/dashboard/audit-logs`

### Ingestion (10)
- POST `/api/v1/ingestion/upload`
- GET `/api/v1/ingestion/batches`
- GET/DELETE `/api/v1/ingestion/batches/{batch_id}`
- POST `/api/v1/ingestion/batches/{batch_id}/cancel`
- GET `/api/v1/ingestion/batches/{batch_id}/errors`
- GET `/api/v1/ingestion/batches/{batch_id}/errors/export`
- GET `/api/v1/ingestion/canonical/orders`
- GET `/api/v1/ingestion/canonical/payments`
- GET `/api/v1/ingestion/canonical/settlements`
- GET `/api/v1/ingestion/canonical/bank-transactions`

### Reconciliation (9)
- POST/GET `/api/v1/reconciliation/runs`
- GET `/api/v1/reconciliation/runs/{run_id}`
- GET `/api/v1/reconciliation/runs/{run_id}/summary`
- GET `.../matches`, `.../unmatched`, `.../ambiguous`, `.../allocations`
- POST `.../matches/{match_id}/resolve`
- GET/POST `/api/v1/reconciliation/contracts`

### Leakage (8)
- POST/GET `/api/v1/leakage/runs`
- GET `/api/v1/leakage/runs/{run_id}`
- GET `.../runs/{run_id}/snapshots`
- GET `/api/v1/leakage/summary`
- GET/POST `/api/v1/leakage/exceptions`
- GET `.../exceptions/{id}`
- GET `.../exceptions/{id}/evidence`
- POST `.../exceptions/{id}/resolve` / `.../review`

### Forensics (5)
- POST/GET `/api/v1/forensics/exceptions/{id}/investigations`
- GET/PATCH `.../investigations/{id}`
- GET/POST `.../investigations/{id}/evidence`
- GET/POST `.../investigations/{id}/claim-drafts`
- PATCH/DELETE `.../claim-drafts/{draft_id}`

### Tenants (3)
- GET/POST `/api/v1/tenants/`
- GET/PATCH `.../tenants/{id}`
- GET/POST `.../tenants/{id}/members`

### Health (3)
- GET `/health`
- GET `/health/live`
- GET `/health/ready`

---

## 4. Test Suite Inventory

| Test Module | Tests |
|---|---|
| test_auth.py | 6 |
| test_health.py | 2 |
| test_rbac.py | 5 |
| test_tenant_isolation.py | 5 |
| test_dashboard_api.py | 4 |
| test_ingestion_shopify.py | 4 |
| test_ingestion_razorpay.py | 3 |
| test_ingestion_hdfc.py | 1 |
| test_ingestion_security_and_quality.py | 5 |
| test_reconciliation_order_to_payment.py | 3 |
| test_reconciliation_settlement_to_bank.py | 4 |
| test_reconciliation_audit_verification.py | 5 |
| test_reconciliation_property_based.py | 3 |
| test_reconciliation_fees_and_precision.py | 3 |
| test_leakage_api_and_rbac.py | ~8 |
| test_leakage_detector_* (5 files) | ~25 |
| test_leakage_orchestration_and_idempotency.py | 4 |
| test_leakage_lineage_and_evidence.py | ~15 |
| test_leakage_detector_calendar_and_timezone.py | ~4 |
| test_forensic_* (6 files) | ~25 |
| test_gemini_integration.py | 10 |
| test_phase7_security_hardening.py | 10 |
| test_phase7_financial_integrity.py | 5 |
| test_phase7_blind_holdout_benchmark.py | 1 |
| test_phase7_backup_restore.py | ~4 |
| test_alembic_version_length_compatibility.py | ~3 |
| test_tenant_financial_history_retention.py | ~4 |
| **TOTAL** | **203** |

---

## 5. Frontend Page Inventory (15 routes)

| Route | Purpose |
|---|---|
| `/` → redirect | Root → Login |
| `/login` | Authentication |
| `/dashboard` | Executive Overview |
| `/dashboard/reconciliation` | 3-Way Reconciliation |
| `/dashboard/leakage-detection` | Revenue Leakage |
| `/dashboard/investigations` | AI Forensics |
| `/dashboard/upload-history` | File Ingestion History |
| `/dashboard/data-sources` | Data Source Management |
| `/dashboard/reports` | Financial Reports |
| `/dashboard/settings` | Tenant Settings |
| `/dashboard/team` | Team Management |
| `/dashboard/audit` | Audit Logs |
| `/dashboard/transactions` | Transaction View |
| `/dashboard/settlements` | Settlement View |
| `/dashboard/exceptions` | Exceptions |
| `/dashboard/disputes` | Disputes |
| `/dashboard/contracts` | Fee Contracts |

---

## 6. Key Findings

### Pre-QA Issues (discovered during setup):
- **P1 BUG (FIXED):** `finora.db` was at Alembic migration `003` only. Migrations 004–007 were NOT applied. Caused `no such table: forensic_investigations` → HTTP 500 on `/api/v1/dashboard/ai-investigations` and `/api/v1/leakage/summary`.  
  **Fix Applied:** `alembic upgrade head` — applied migrations 004, 005, 006, 007 successfully.

---

*Report generated by autonomous QA execution.*
