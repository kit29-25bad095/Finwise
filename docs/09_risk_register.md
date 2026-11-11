# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine
# Document 09: System Risk Register & Operational Mitigations

**Project Name:** Finora  
**Document Reference:** FINORA-RISK-REG-V2  
**Classification:** Enterprise Risk Assessment  
**Author:** Principal Software Architect, Senior Financial Systems Engineer  
**Status:** Under Formal Architectural Review (Phase 0)  
**Date:** November 2026  

---

## 1. Risk Scoring Methodology

- **Probability (P):** 1 (Rare) to 5 (Almost Certain)
- **Impact (I):** 1 (Negligible) to 5 (Catastrophic)
- **Risk Score (R):** $P \times I$ (1 to 25)
  - **15–25:** Critical (Mandatory architectural blocker)
  - **8–14:** Moderate (Requires formal mitigation plan)
  - **1–7:** Low (Standard monitoring)

---

## 2. Comprehensive Risk Register

```
+-------------------------------------------------------------------------------------------------------------------+
|                                            FINORA RISK REGISTER                                                   |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| ID | RISK EVENT         | CAT | P | I | R  | ARCHITECTURAL MITIGATION           | CONTINGENCY PLAN               |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| R1 | False accusations  | FIN | 3 | 5 | 15 | Two-tier verification pipeline;    | Human approval mandatory;      |
|    | of leakage against |     |   |   |    | tolerance threshold (₹0.05);       | claims tagged "POTENTIALLY     |
|    | payment gateway.   |     |   |   |    | Indian banking calendar validation.| RECOVERABLE" until verified.   |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| R2 | Misallocation of   | FIN | 3 | 5 | 15 | Candidate scoring engine; anti-    | Halts auto-allocation; routes  |
|    | equal-amount bank  |     |   |   |    | collision thresholding (< 0.15     | candidates to Human Review     |
|    | credits.           |     |   |   |    | delta flagged as AMBIGUOUS).       | Queue with side-by-side diff.  |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| R3 | Cross-tenant data  | SEC | 2 | 5 | 10 | PostgreSQL Row-Level Security;     | Automated penetration tests    |
|    | leakage via IDOR.  |     |   |   |    | JWT-bound tenant ID; zero client   | in CI/CD pipeline blocking PR  |
|    |                    |     |   |   |    | trust on path parameters.          | merge on boundary leak.        |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| R4 | AI hallucinates    | AI  | 3 | 4 | 12 | Citation verification gateway;     | Fallback to "INCONCLUSIVE";    |
|    | transaction IDs or |     |   |   |    | zero numbers in LLM context;       | SecOps alerted; dispute draft  |
|    | dispute rationale. |     |   |   |    | native JSON schema validation.     | withheld until human sign-off. |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| R5 | Memory crash on    | OPS | 4 | 3 | 12 | Streaming multipart CSV parser;    | Worker isolates failed batch;  |
|    | large (50MB+) CSV  |     |   |   |    | 50MB file size cap; chunked batch  | quaratines bad rows in table;  |
|    | upload ingestion.  |     |   |   |    | ingestion in background RQ worker. | surfaces row-level error log.  |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| R6 | Rerun reconciliation| OPS| 3 | 4 | 12 | Immutable append-only run model;   | Atomic DB transaction rollback;|
|    | corrupts prior     |     |   |   |    | allocations versioned; distributed | historical Run N allocations   |
|    | audit state.       |     |   |   |    | Redis lock per tenant during runs. | remain active if N+1 fails.    |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| R7 | External AI        | AI  | 3 | 3 | 9  | Abstract LLM Gateway Adapter;      | Deterministic reconciliation   |
|    | provider outage or |     |   |   |    | support for Gemini & OpenAI;       | proceeds unimpeded; AI summary |
|    | rate-limit spike.  |     |   |   |    | graceful degradation.              | deferred until API recovers.   |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
| R8 | CSV formula / DDE  | SEC | 2 | 4 | 8  | Sanitizer prepends single quote    | Exported CSVs escape all       |
|    | spreadsheet attack |     |   |   |    | to leading formula chars on        | formula characters by default. |
|    | on claim export.   |     |   |   |    | ingestion and before export.       |                                |
+----+--------------------+-----+---+---+----+------------------------------------+--------------------------------+
```

---
*(End of Document 09 — System Risk Register)*
