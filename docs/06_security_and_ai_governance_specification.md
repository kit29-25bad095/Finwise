# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine
# Document 06: Security Architecture, Threat Model & AI Governance Specification (Provider-Agnostic)

**Project Name:** Finora  
**Document Reference:** FINORA-SEC-GOV-V3  
**Classification:** FinTech Security & Governance Specification  
**Author:** FinTech Security Architect, Principal Software Architect  
**Status:** Under Formal Architectural Review (Phase 0 - Revision 3)  
**Date:** November 2026  

---

## 1. Executive Summary & Security Philosophy

Finora handles authoritative financial ledgers, bank transactions, and revenue leakage claims for commercial enterprises. Security, data confidentiality, and algorithmic integrity are tier-one architectural imperatives. 

The security architecture enforces a **Zero-Trust Financial Perimeter**:
- The client browser is untrusted.
- Uploaded CSV files are untrusted data vectors.
- External AI models are untrusted execution environments that must never calculate numbers, access unredacted PII, or execute instructions found in input data.
- **Provider-Independence:** The AI governance layer decouples the core backend from any single AI vendor (Gemini, OpenAI, Anthropic, or private local models).

---

## 2. Updated STRIDE Threat Model

```
+----------------------------------------------------------------------------------------------------+
|                                      STRIDE THREAT MATRIX                                          |
+--------------------+-------------------------------------------+-----------------------------------+
| THREAT CATEGORY    | REAL-WORLD ATTACK SCENARIO                | ARCHITECTURAL MITIGATION          |
+--------------------+-------------------------------------------+-----------------------------------+
| Spoofing           | Forged JWT token accessing another tenant.| RS256 asymmetric signature;       |
|                    | Attacker intercepts session cookie.       | HTTP-only, Secure, SameSite=Strict|
|                    |                                           | cookies; Refresh token rotation.  |
+--------------------+-------------------------------------------+-----------------------------------+
| Tampering          | Modifying CSV balances during upload.     | SHA-256 hash verified on upload;  |
|                    | Tampering with allocation records in DB.  | DB check constraints; immutable   |
|                    |                                           | audit logs; row-level locking.    |
+--------------------+-------------------------------------------+-----------------------------------+
| Repudiation        | Finance user approves an improper claim   | Immutable audit log capturing IP, |
|                    | and denies having taken the action.       | User ID, pre/post state JSON, and |
|                    |                                           | mandatory user rationale.         |
+--------------------+-------------------------------------------+-----------------------------------+
| Information        | Multi-tenant cross-contamination via IDOR | PostgreSQL Row-Level Security;    |
| Disclosure         | Direct S3 object URL access to statements.| Tenant ID bound to JWT only;      |
|                    |                                           | Private S3 buckets + 15m presigned|
+--------------------+-------------------------------------------+-----------------------------------+
| Denial of          | Giga-byte CSV upload crashing backend.    | Streaming multipart upload (50MB  |
| Service            | Regex DoS via catastrophic backtracking.  | hard cap); asynchronous RQ workers|
|                    | Combinatorial knapsack explosion.         | Bound N <= configured search limit|
+--------------------+-------------------------------------------+-----------------------------------+
| Elevation of       | Auditor role modifying fee contracts or   | Strict RBAC middleware; endpoint  |
| Privilege          | bypassing human review gates.             | permission guards at FastAPI layer|
+--------------------+-------------------------------------------+-----------------------------------+
```

---

## 3. CSV Ingestion Security & DDE Formula Injection Defense

### 3.1 DDE / Formula Injection Defense
Malicious users or upstream storefronts can inject spreadsheet execution formulas into order notes, line-item titles, customer names, or bank descriptions.
- **Sanitization Rule:** Any CSV cell starting with `=`, `+`, `-`, `@`, `|`, or `%` has a leading apostrophe (`'`) prepended during parsing:
  ```python
  def sanitize_csv_cell(val: str) -> str:
      if val and val[0] in ('=', '+', '-', '@', '|', '%'):
          return f"'{val}"
      return val
  ```
- **Export Defense:** All exported CSV claim packs and tabular summaries automatically re-apply formula escaping to protect the finance team's desktop spreadsheet software.

---

## 4. Provider-Independent AI Architecture & Governance

```
+----------------------------------------------------------------------------------------------------+
|                                    AI ISOLATION BOUNDARY                                           |
+----------------------------------------------------------------------------------------------------+
                                                  │
  [Internal Financial Ledger]                     │
  - Order details, Captures, Settlements          │
  - Calculated Discrepancy Amount                 │
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PII REDACTION & SANITIZATION GATEWAY                                                               |
| - Replaces Customer Name -> "REDACTED_CUSTOMER"                                                    |
| - Strips Delivery Addresses, Phone Numbers, Emails                                                 |
| - Replaces Card/VPA -> Masked Token (e.g. UPI-**9812)                                              |
| - ZERO free-text Order Notes passed to AI context                                                  |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼ Clean Structured JSON Evidence Bundle
+----------------------------------------------------------------------------------------------------+
| ABSTRACT LLM GATEWAY ADAPTER (AIInvestigationProviderFactory)                                      |
| - Dynamically routes to configured tenant provider:                                                |
|   * GeminiProvider (gemini-1.5-pro, gemini-1.5-flash, etc.)                                        |
|   * OpenAIProvider (gpt-4o, gpt-4o-mini, etc.)                                                     |
|   * AnthropicProvider (claude-3-5-sonnet, etc.)                                                    |
|   * MockProvider (for automated CI testing without external API calls)                             |
| - Enforces native JSON schema (`response_schema` / `response_format`)                              |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼ Structured JSON Response
+----------------------------------------------------------------------------------------------------+
| GROUNDED CITATION VALIDATOR                                                                        |
| - Inspects every cited `evidence_id`, `utr_number`, `transaction_id` in LLM output                 |
| - IF any cited ID does NOT exist in the original input bundle:                                     |
|   --> REJECT response immediately                                                                  |
|   --> Set status = "INCONCLUSIVE (Citation Verification Failed)"                                    |
|   --> Alert SecOps of potential hallucination                                                      |
+----------------------------------------------------------------------------------------------------+
```

---
*(End of Document 06 — Security Architecture & AI Governance Specification V3)*
