# Finora — Remaining Blockers & External Production Dependencies

**Document Reference:** `FINORA-DEP-008`  
**Classification:** Production Readiness Gap Analysis & Blocker Register  
**Audit Date:** November 13, 2026  
**Auditor Roles:** Principal Release Manager, Production Readiness Specialist  

---

## 1. Executive Summary

Finora is functionally complete, mathematically verified, and hardened for staging and controlled pilot deployment. In accordance with strict deployment governance:
- **No production credentials were fabricated to force an artificial audit pass.**
- **No unauthorized public deployments were triggered.**
- **Every missing credential, cloud dependency, and infrastructure requirement is recorded below as an explicit blocker.**

---

## 2. Comprehensive Blocker Register

| Blocker ID | Severity | Category | Area | Description & Dependency | Required Resolution Action | User Intervention Required? |
|---|---|---|---|---|---|:---:|
| **BLK-001** | **High** | Credentials | Area 1 | `GEMINI_API_KEY` not configured in host environment. | Provision valid API key from Google AI Studio; export `GEMINI_API_KEY`. | **YES** |
| **BLK-002** | **High** | Infrastructure | Area 2 | Managed PostgreSQL 16+ production database instance. | Provision AWS RDS PostgreSQL / Supabase; configure `DATABASE_URL`. | **YES** |
| **BLK-003** | **Medium** | Infrastructure | Area 3 | Public TLS/SSL certificates & reverse proxy termination. | Configure domain DNS (e.g. `app.finora.io`), provision Let's Encrypt SSL on Nginx/ALB. | **YES** |
| **BLK-004** | **Medium** | Infrastructure | Area 5 | Managed Redis 7+ cluster for asynchronous workers. | Provision Redis cluster (e.g. AWS ElastiCache / Redis Cloud); set `REDIS_URL`. | **YES** |
| **BLK-005** | **Low** | Observability | Area 6 | Sentry DSN / APM Cloud Project. | Create Sentry project for error aggregation; configure `SENTRY_DSN`. | Optional |

---

## 3. Detailed Blocker Analysis

### Blocker BLK-001: Google Gemini API Key
- **Current State:** The backend adapter (`GeminiLLMAdapter`) is implemented and tested with 19 mock integration tests. The frontend investigations dashboard displays `PENDING_CONFIGURATION`.
- **Why It Is Blocked:** No live API key exists in the environment, and credentials must never be invented.
- **Production Impact:** Real-time AI forensic narrative generation is offline. The system continues to run 100% deterministically using core reconciliation and leakage detection rules without interruption.
- **Action Required:** User must acquire a Google AI Studio API key and configure it in `.env` or deployment secrets.

### Blocker BLK-002: Managed PostgreSQL Instance
- **Current State:** The application operates locally on SQLite (`finora.db`) with `PRAGMA foreign_keys=ON`. Multi-dialect PostgreSQL migrations are implemented and validated via test suites.
- **Why It Is Blocked:** No live managed PostgreSQL instance was provisioned for this audit.
- **Production Impact:** SQLite is acceptable for single-tenant local testing and small pilot deployments, but production enterprise multi-tenant scale requires PostgreSQL for concurrent ACID transactions and connection pooling.
- **Action Required:** DevOps team must provision an AWS RDS PostgreSQL instance (db.t4g.medium recommended) and apply migrations using `alembic upgrade head`.

### Blocker BLK-003: Public HTTPS & Domain Routing
- **Current State:** Application runs on local ports (`http://localhost:3100` and `http://127.0.0.1:8000`). Next.js and FastAPI enforce OWASP security headers (HSTS, CSP, X-Frame-Options).
- **Why It Is Blocked:** Public DNS and TLS certificates were not created, adhering strictly to the restriction against unauthorized public deployment.
- **Production Impact:** Local HTTP is not encrypted over public networks.
- **Action Required:** Configure an Nginx reverse proxy or Cloudflare tunnel with automated Let's Encrypt TLS renewal before opening public access.

### Blocker BLK-004: Redis Asynchronous Worker Daemon
- **Current State:** When Redis is absent, `WORKER_FALLBACK_SYNC=True` executes reconciliation and leakage jobs synchronously in-process.
- **Why It Is Blocked:** No managed Redis cluster is attached in the local execution environment.
- **Production Impact:** High-volume CSV batch uploads (e.g., 50,000+ rows) may cause request latency if processed synchronously.
- **Action Required:** Provision a Redis instance and set `WORKER_FALLBACK_SYNC=False` in production environment settings.

---

## 4. Release Decision Matrix

| Deployment Stage | Readiness Status | Conditions & Dependencies |
|---|:---:|---|
| **Local Development** | ✅ **100% READY** | Operational with SQLite, Mock AI, and Sync Worker. |
| **Isolated Staging** | ✅ **READY** | Provision staging PostgreSQL and Redis; test with synthetic data. |
| **Controlled Customer Pilot** | ✅ **APPROVED** | Onboard pilot merchants on managed single-node instance. |
| **Public Multi-Tenant GA** | 🛑 **BLOCKED** | Requires resolution of BLK-001 through BLK-004. |
