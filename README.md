# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine

Finora is an enterprise-grade financial intelligence and revenue recovery platform engineered for Indian mid-sized D2C and e-commerce enterprises (₹15 Lakh to ₹2 Crore monthly GMV).

## Core Principles
1. **NO DISCREPANCY WITHOUT TRACEABILITY:** Every discrepancy links back to source files and exact row numbers.
2. **NO RECOVERY CLAIM WITHOUT EVIDENCE:** Discrepancies do not constitute recoverable loss without contractual, ledger, and banking proof.
3. **NO FINANCIAL CALCULATION DELEGATED TO AI:** All financial calculations, fee evaluations, and allocations are 100% deterministic backend operations. The AI engine is strictly an investigator and dispute dossier generator.

---

## Architecture Overview (Modular Monolith)
- **Backend:** Python + FastAPI + SQLAlchemy 2.0 + Alembic migrations.
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind CSS + Lucide Icons.
- **Database:** PostgreSQL (with SQLite zero-dependency local test fallback) using arbitrary-precision `NUMERIC(18, 4)`.
- **Background Worker:** Redis + RQ with automatic synchronous test fallback.
- **Security:** Multi-tenant cryptographic isolation, JWT authentication, and strict Role-Based Access Control (`ADMIN`, `FINANCE_MANAGER`, `AUDITOR`).

---

## Quick Start (Local Development)

### 1. Backend Setup
```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Run initial database migrations
alembic upgrade head

# Start FastAPI server
uvicorn app.main:app --reload --port 8000
```
- Interactive Swagger API Documentation: `http://localhost:8000/api/v1/docs`
- Healthcheck Endpoint: `http://localhost:8000/health`

### 2. Frontend Setup
```bash
cd frontend

# Install dependencies
npm install

# Build production bundle
npm run build

# Start local Next.js dev server
npm run dev -- -p 3000
```
- Web Application Console: `http://localhost:3000`
- Sign In & Tenant Registration: `http://localhost:3000/login`

### 3. Running Automated Tests
```bash
cd backend
pytest -v
```
All 18 automated tests cover:
- User registration and isolated tenant creation.
- JWT issuance, verification, and expiration.
- Cross-tenant access rejection (HTTP 403 / 404).
- Role-based permissions (`ADMIN`, `FINANCE_MANAGER`, `AUDITOR`).
- System health and database connectivity.

---

## Phase Status
- **Phase 0 (Architecture & Specification):** VERIFIED & COMPLETED
- **Phase 1 (Project Foundation, Tenancy, Auth & DB Schema):** **IMPLEMENTED & VERIFIED**
- **Phase 2 (Data Ingestion Pipeline):** PENDING AUTHORIZATION

For full architectural documentation, inspect the [`docs/`](./docs) directory.
