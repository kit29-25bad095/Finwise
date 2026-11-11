# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine
# Document 07: Complete Phase-by-Phase Development Roadmap

**Project Name:** Finora  
**Document Reference:** FINORA-ROADMAP-V2  
**Classification:** Technical Execution Plan  
**Author:** Technical Project Planner, Principal Software Architect  
**Status:** Under Formal Architectural Review (Phase 0)  
**Date:** November 2026  

---

## 1. Executive Summary & Timeline Feasibility Analysis

The baseline timeline spans **six engineering weeks (Phases 1 through 7)**. 

### 1.1 Realistic Estimation & Risk Mitigations
- **Ingestion & Normalization (Phase 2):** Real-world CSVs from Indian merchants frequently contain malformed rows, custom headers, or unexpected date formats. *Mitigation:* We budget a dedicated 4-day testing sprint specifically for CSV edge cases.
- **Multi-Pass Matching & Allocation (Phase 3):** Getting property-based tests (Hypothesis) passing with 100% conservation of funds is algorithmically complex. *Mitigation:* Phase 3 backend tasks take priority over UI styling.
- **Timeline Integrity:** Rather than forcing unrealistic delivery dates, we explicitly flag that **Week 6 includes 3 days of buffer for holdout validation and performance tuning**.

---

## 2. Phase-by-Phase Implementation Specifications

---

### PHASE 1: Project Foundation, Tenancy, Auth & DB Schema (Week 1)

- **Objective:** Establish the production-grade modular monolith skeleton, multi-tenant database schema, authentication system, and background worker infrastructure.
- **Features to Develop:**
  - Multi-tenant architecture with PostgreSQL RLS.
  - Asymmetric JWT authentication with refresh token rotation.
  - Role-Based Access Control (Admin, Finance Manager, Auditor).
  - Redis + RQ worker pipeline with job status tracking.
- **Backend Tasks:**
  - Set up FastAPI app with modular router structure (`/api/v1/`).
  - Configure SQLAlchemy async engine and session middleware.
  - Configure RQ worker cluster and Redis connection pools.
  - Implement tenant isolation dependency injection.
- **Frontend Tasks:**
  - Initialize Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui.
  - Implement enterprise dark-navy design system tokens and typography.
  - Build Auth layout, login, and tenant context provider.
- **Database Tasks:**
  - Author initial Alembic migration for all core tables (Tenants, Users, Memberships, Fee Contracts, Audit Logs).
  - Configure RLS policies and composite indexes.
- **AI Tasks:** None.
- **Dependencies:** PostgreSQL, Redis.
- **Testing Requirements:** Unit tests for password hashing and JWT issuance; integration tests verifying cross-tenant access rejection (HTTP 403/404).
- **Deliverables:** Working backend and frontend skeletons; successful database migration; passing tenant isolation test suite.
- **Completion Criteria:** User can register, log in, receive a secure JWT, and access tenant-scoped protected endpoints.

---

### PHASE 2: Data Ingestion Pipeline & Normalization (Week 2)

- **Objective:** Build secure, high-throughput CSV ingestion adapters for Shopify, Razorpay, and Bank Statements with provenance tracking.
- **Features to Develop:**
  - Multipart streaming upload with DDE injection sanitization.
  - Source adapters: `ShopifyAdapter`, `RazorpayAdapter`, `BankStatementAdapter` (HDFC reference).
  - Column mapping preview and header validation.
  - Source row error quarantine and import summary reports.
- **Backend Tasks:**
  - Build upload endpoints with SHA-256 duplicate file detection.
  - Implement RQ ingestion workers for background batch parsing.
  - Build canonical normalization pipeline mapping raw CSV rows to `orders`, `payment_captures`, `settlement_batches`, and `bank_transactions`.
- **Frontend Tasks:**
  - Build Data Ingestion wizard (File dropzone, source selector, header preview, mapping editor).
  - Build Upload History table with status badges and error download links.
- **Database Tasks:**
  - Alembic migrations for `uploads`, `source_row_errors`, and canonical tables.
- **AI Tasks:** None.
- **Dependencies:** Phase 1 completion.
- **Testing Requirements:** Unit tests for each adapter against sample CSVs; DDE injection attack tests; duplicate upload rejection tests.
- **Deliverables:** Complete ingestion pipeline; passing adapter test suite.
- **Completion Criteria:** Successfully ingests 10,000-row sample files from Shopify, Razorpay, and HDFC into canonical tables with zero dropped rows and complete provenance.

---

### PHASE 3: Deterministic Financial Reconciliation & Allocation (Week 3)

- **Objective:** Implement the multi-pass deterministic matching engine, allocation ledger, and immutable run lifecycle.
- **Features to Develop:**
  - Passes 1 through 5 matching engine.
  - Candidate scoring engine (Pass 4) with anti-collision thresholding.
  - Aggregated multi-record allocation (Pass 5 knapsack solver).
  - Immutable reconciliation run execution and versioning.
- **Backend Tasks:**
  - Implement `ReconciliationService` and multi-pass pipeline.
  - Implement row-level locking (`SELECT ... FOR UPDATE`) during allocations.
  - Build reconciliation trigger, progress polling, and cancellation endpoints.
- **Frontend Tasks:**
  - Build Reconciliation Runs dashboard (Run trigger, progress indicator, summary metrics).
  - Build Reconciliation Run Details view with drill-down tables.
- **Database Tasks:**
  - Alembic migration for `reconciliation_runs`, `allocations`, and `run_deltas`.
  - Check constraints for non-negative balances.
- **AI Tasks:** None.
- **Dependencies:** Phase 2 completion.
- **Testing Requirements:** Property-based tests (Hypothesis) proving allocation conservation ($\sum \text{Allocated} \le \text{Nominal}$) and rerun idempotency.
- **Deliverables:** Deterministic matching engine; passing property test suite.
- **Completion Criteria:** 10,000 synthetic transactions reconcile with 100% mathematical precision and zero balance drift.

---

### PHASE 4: Core Leakage Detection Engine (Week 4)

- **Objective:** Implement and validate the four core leakage detectors and the Indian Banking Calendar.
- **Features to Develop:**
  - Indian Banking Calendar service (`IN_BANKING_CALENDAR`).
  - Detector 1: Missing Gateway Settlements.
  - Detector 2: Settlements Not Credited to Bank.
  - Detector 3: Contractual Fee Overcharges (MDR + GST).
  - Detector 4: Duplicate & Unauthorized Refunds.
  - Structured evidence packaging service.
- **Backend Tasks:**
  - Implement pure mathematical detector functions.
  - Implement fee contract rate card evaluation with $\epsilon = ₹0.05$ tolerance.
  - Persist detected discrepancies to `exceptions` table with evidence links.
- **Frontend Tasks:**
  - Build Exception Management dashboard with filtering (severity, type, status).
  - Build Fee Contract Management settings UI.
- **Database Tasks:**
  - Alembic migration for `exceptions`, `evidence_items`, and `fee_schedule_versions`.
- **AI Tasks:** None.
- **Dependencies:** Phase 3 completion.
- **Testing Requirements:** Unit tests for every detector; boundary tests on bank holidays and 2nd/4th Saturdays; fee overcharge tests across all payment methods.
- **Deliverables:** Working detector suite; verified evidence linkage.
- **Completion Criteria:** Detectors catch 100% of injected anomalies in the benchmark test suite without false positives on holiday delays.

---

### PHASE 5: AI Forensic Investigator & Claim Pack Engine (Week 5)

- **Objective:** Deploy the secure AI investigator and automated dispute claim pack generation pipeline.
- **Features to Develop:**
  - Abstract `AIInvestigationProvider` with Google Gemini 1.5 Pro implementation.
  - Structured Pydantic JSON schema output enforcement.
  - PII scrubbing and prompt injection defense wrapper.
  - Grounded evidence citation validator.
  - Dispute Claim Pack generator (CSV & PDF formats).
- **Backend Tasks:**
  - Implement evidence bundle serializing service.
  - Build background LLM investigation dispatcher in RQ worker.
  - Implement citation verification logic.
  - Build PDF generator (WeasyPrint / ReportLab) and CSV exporter.
- **Frontend Tasks:**
  - Build AI Investigation panel with hypotheses, evidence links, and plain-English narrative.
  - Build Dispute Claim Dossier viewer with PDF download and review actions.
- **Database Tasks:**
  - Alembic migration for `ai_investigations` and `disputes`.
- **AI Tasks:** System prompt engineering; structured output schema tuning; hallucination evaluation tests.
- **Dependencies:** Phase 4 completion.
- **Testing Requirements:** AI citation verification test suite; prompt injection penetration tests; PDF export layout checks.
- **Deliverables:** Operational AI investigator; downloadable claim packs.
- **Completion Criteria:** AI correctly diagnoses root causes on test exceptions without hallucinating a single entity reference or changing any monetary value.

---

### PHASE 6: Human Review Workflow, Financial Dashboard & UX (Week 6 - Days 1 to 3)

- **Objective:** Connect the complete end-to-end user experience, human approval lifecycle, and executive dashboard.
- **Features to Develop:**
  - Executive Financial Overview Dashboard (Total Captures, Settled, Discrepancies, Recoverable, Claimed).
  - Exception Review Queue with side-by-side evidence inspection.
  - One-click Claim Approval / Dismissal modal with mandatory user rationale.
  - Immutable audit logging UI for compliance review.
  - Interactive Demo Mode with pre-loaded mock scenarios.
- **Backend Tasks:**
  - Build aggregated dashboard metric queries (`/api/v1/dashboard/metrics`).
  - Implement human review transition endpoints (`/api/v1/exceptions/{id}/review`).
  - Implement immutable audit log querying endpoints.
- **Frontend Tasks:**
  - Assemble high-density Recharts analytics components.
  - Build Exception Review modal with audit reason capture.
  - Build Audit Log viewer with JSON diff inspector.
  - Build Demo Mode toggle with synthetic data loader.
- **Database Tasks:** Performance indexing on dashboard aggregation queries.
- **AI Tasks:** None.
- **Dependencies:** Phase 5 completion.
- **Testing Requirements:** Frontend end-to-end test suite (Playwright); API authorization tests.
- **Deliverables:** Fully integrated web application.
- **Completion Criteria:** User can upload files, run reconciliation, review an AI investigation, approve a claim, and download a signed dispute pack.

---

### PHASE 7: Security Hardening, Holdout Testing & Pilot Readiness (Week 6 - Days 4 to 5)

- **Objective:** Execute blind holdout dataset testing, security penetration audit, and production deployment configuration.
- **Features to Develop:** Production readiness documentation and deployment scripts.
- **Backend Tasks:** Performance profiling, database vacuuming configuration, rate-limiting rules.
- **Frontend Tasks:** Production build optimizations, Lighthouse audit.
- **Database Tasks:** Automated backup/restore validation test.
- **Testing Requirements:**
  - Blind holdout dataset execution (2,500 transactions).
  - Security audit: OWASP Top 10, IDOR, SQL injection, prompt injection verification.
- **Deliverables:** Final deployment package; Pilot Merchant Onboarding Guide; verified benchmark report.
- **Completion Criteria:** 100% pass on security checklist; zero unresolved critical bugs; holdout dataset achieves $\ge 99.5\%$ match precision.

---
*(End of Document 07 — Complete Phase-by-Phase Development Roadmap)*
