# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine
# Document 10: Decision Register & Governance Approval Matrix

**Project Name:** Finora  
**Document Reference:** FINORA-DECISIONS-V3  
**Classification:** Architectural Governance Sign-off  
**Author:** Principal Software Architect, Senior Financial Systems Engineer  
**Status:** Under Formal Architectural Review (Phase 0 - Revision 3)  
**Date:** November 2026  

---

## 1. Executive Summary & Governance Structure

To avoid conflating user business choices with architectural runtime settings, this register divides all system parameters into three clear categories:
1. **CATEGORY A: Strategic Decisions Requiring User Approval** (Product scope, initial MVP reference target, and acceptance gates).
2. **CATEGORY B: Architect Recommendations for Baseline Scaffolding** (Recommended defaults for Phase 1 code scaffolding, modifiable at any time).
3. **CATEGORY C: Fully Configurable Runtime Parameters** (Parameters built into the schema to be configured per tenant, gateway, bank, and contract without requiring hard architectural lock-in).

---

## 2. CATEGORY A: Strategic Decisions Requiring User Approval

These decisions establish the scope and validation gates for Phase 1. They require explicit confirmation from you before implementation begins:

```
+----+----------------------------------+----------------------------------+----------------------------------+
| #  | DECISION DOMAIN                  | AVAILABLE OPTIONS                | ARCHITECT RECOMMENDATION         |
+----+----------------------------------+----------------------------------+----------------------------------+
| A1 | Initial MVP Bank Statement       | 1. HDFC Bank Current Account CSV | **Option 1: HDFC Bank CSV**      |
|    | Reference Format                 | 2. ICICI Bank Current Account CSV| Most widespread banking format   |
|    |                                  | 3. Generic Custom Mapper Only    | in Indian D2C; custom mapper     |
|    |                                  |                                  | handles alternate formats.       |
+----+----------------------------------+----------------------------------+----------------------------------+
| A2 | Primary AI Provider Driver for   | 1. Google Gemini (1.5 Pro/Flash) | **Option 1: Google Gemini**      |
|    | Phase 5 Integration & Evaluation | 2. OpenAI (GPT-4o / GPT-4o-mini) | Native JSON schema enforcement   |
|    |                                  | 3. Mock Provider Only (No LLM)   | and cost efficiency. Abstract    |
|    |                                  |                                  | interface supports both.         |
+----+----------------------------------+----------------------------------+----------------------------------+
| A3 | Phase 7 Holdout Benchmark Gate   | 1. Match Precision >= 99.8%      | **Option 1: Precision >= 99.8%** |
|    | Acceptance Threshold             | 2. Match Precision >= 99.0%      | High threshold ensures zero      |
|    |                                  | 3. Relaxed Pilot Standard (95%)  | erroneous dispute claims.        |
+----+----------------------------------+----------------------------------+----------------------------------+
| A4 | Authorization to Scaffolding     | 1. Approve Phase 1 Scaffolding   | **Awaiting User Action**         |
|    | Phase 1 (Foundation & Auth)      | 2. Request Further Revisions     |                                  |
+----+----------------------------------+----------------------------------+----------------------------------+
```

---

## 3. CATEGORY B: Architect Recommendations for Baseline Scaffolding

These are recommended defaults for project initialization. They do not lock the architecture:

- **B1. Monolith Project Structure:** Standard FastAPI backend in `/backend/` and Next.js App Router in `/frontend/`.
- **B2. Database Migration Engine:** Alembic with asynchronous PostgreSQL driver (`asyncpg` + `psycopg2` for sync tasks).
- **B3. Background Queue Broker:** Redis with RQ (Redis Queue) for worker distribution.
- **B4. Test Harness:** Pytest + Hypothesis for property-based financial invariant testing.

---

## 4. CATEGORY C: Fully Configurable Runtime Parameters (Safe to Remain Dynamic)

The revised architecture **does not hardcode these values**. They are modeled as configurable database columns in tenant settings, provider adapters, and fee contracts:

```
+----+--------------------------------------+---------------------+---------------------------------------+
| #  | PARAMETER                            | DEFAULT VALUE       | CONFIGURATION SCOPE                   |
+----+--------------------------------------+---------------------+---------------------------------------+
| C1 | Fee Overcharge Tolerance (epsilon)   | ₹0.05 (5 paise)     | Configurable per Tenant (₹0.00–₹1.00) |
+----+--------------------------------------+---------------------+---------------------------------------+
| C2 | Daily Gateway Settlement Cutoff      | 23:00 IST           | Configurable per Provider & Contract  |
+----+--------------------------------------+---------------------+---------------------------------------+
| C3 | Banking Calendar & Clearing Hub      | RBI RTGS (Mumbai)   | Configurable per Merchant Bank Branch |
+----+--------------------------------------+---------------------+---------------------------------------+
| C4 | Knapsack Subset Sum Max Bound (N)    | N = 5 items         | Configurable per Tenant (N = 3 to 8)  |
+----+--------------------------------------+---------------------+---------------------------------------+
| C5 | MDR, Fixed Fees, GST & Caps          | 100% Contract-driven| Defined in versioned Fee Contracts    |
+----+--------------------------------------+---------------------+---------------------------------------+
| C6 | Instant Refund Convenience Fee Surcharge| Contract-driven   | Defined per Gateway Contract Schedule |
+----+--------------------------------------+---------------------+---------------------------------------+
| C7 | Candidate Scoring Weights (Pass 4)   | 0.40/0.35/0.15/0.10 | Configurable per Tenant               |
+----+--------------------------------------+---------------------+---------------------------------------+
```

---
*(End of Document 10 — Decision Register & Governance Approval Matrix V3)*
