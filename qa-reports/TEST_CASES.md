# Finora — Test Cases

**QA Date:** 2026-11-13  
**QA Lead:** Autonomous QA Engine

---

## Module 1: Authentication

| TC ID | Test Name | Type | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-AUTH-01 | Register with valid email/password/name/tenant | Functional | HTTP 201 + access_token | HTTP 201 + token | ✅ PASS |
| TC-AUTH-02 | Register with duplicate email | Negative | HTTP 400 | HTTP 400 | ✅ PASS |
| TC-AUTH-03 | Register with reserved TLD (.test) | Negative | HTTP 422 (email validation) | HTTP 422 | ✅ PASS |
| TC-AUTH-04 | Register missing required field (full_name) | Negative | HTTP 422 | HTTP 422 | ✅ PASS |
| TC-AUTH-05 | Login with correct credentials | Functional | HTTP 200 + JWT token | HTTP 200 + token | ✅ PASS |
| TC-AUTH-06 | Login with wrong password | Security | HTTP 401 | HTTP 401 | ✅ PASS |
| TC-AUTH-07 | Login with non-existent email | Security | HTTP 401 | HTTP 401 | ✅ PASS |
| TC-AUTH-08 | Access protected route with valid JWT | Functional | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-AUTH-09 | Access protected route with invalid JWT | Security | HTTP 401 | HTTP 401 | ✅ PASS |
| TC-AUTH-10 | Access protected route with no token | Security | HTTP 401 | HTTP 401 | ✅ PASS |
| TC-AUTH-11 | Rate limiting (5 failed logins → lockout) | Security | 60s lockout | PASS (test suite) | ✅ PASS |
| TC-AUTH-12 | GET /auth/me returns current user profile | Functional | email matches | email matches | ✅ PASS |

---

## Module 2: Dashboard API

| TC ID | Test Name | Type | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-DASH-01 | GET /dashboard/overview returns financial summary | Functional | HTTP 200, dict with keys | HTTP 200, 15+ keys | ✅ PASS |
| TC-DASH-02 | GET /dashboard/ai-investigations returns PENDING_CONFIGURATION | Functional | HTTP 200, status=PENDING | HTTP 200, PENDING | ✅ PASS |
| TC-DASH-03 | GET /dashboard/review-queue returns list | Functional | HTTP 200, list | HTTP 200, list | ✅ PASS |
| TC-DASH-04 | GET /dashboard/fee-analytics returns dict | Functional | HTTP 200, dict | HTTP 200, dict | ✅ PASS |
| TC-DASH-05 | GET /dashboard/audit-logs returns list | Functional | HTTP 200, list | HTTP 200, list | ✅ PASS |
| TC-DASH-06 | GET /dashboard/leakage-findings | Functional | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-DASH-07 | Dashboard endpoints respect tenant isolation | Security | Only own data | Only own data (test suite) | ✅ PASS |
| TC-DASH-08 | POST migrations not applied → 500 (BUG-001) | Regression | HTTP 500 found | HTTP 500 found, then FIXED | ✅ FIXED |

---

## Module 3: Data Ingestion

| TC ID | Test Name | Type | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-ING-01 | Upload valid Shopify CSV | Functional | Batch created, records ingested | PASS (test suite) | ✅ PASS |
| TC-ING-02 | Upload CSV with missing headers | Negative | Error batch, row-level errors | PASS | ✅ PASS |
| TC-ING-03 | Upload duplicate file (same hash) | Negative | Duplicate detected | PASS | ✅ PASS |
| TC-ING-04 | Upload valid Razorpay payments CSV | Functional | Records ingested | PASS | ✅ PASS |
| TC-ING-05 | Upload valid Razorpay settlements CSV | Functional | Records ingested | PASS | ✅ PASS |
| TC-ING-06 | Upload valid HDFC bank statement CSV | Functional | Records ingested | PASS | ✅ PASS |
| TC-ING-07 | CSV formula injection (DDE) | Security | Sanitized/rejected | Sanitized (test suite) | ✅ PASS |
| TC-ING-08 | Tenant isolation on ingestion | Security | Cross-tenant blocked | PASS | ✅ PASS |
| TC-ING-09 | Auditor cannot upload files (RBAC) | RBAC | HTTP 403 | PASS | ✅ PASS |
| TC-ING-10 | Cancel an in-progress batch | Functional | Batch cancelled | PASS | ✅ PASS |
| TC-ING-11 | Export batch errors to CSV | Functional | CSV download | PASS | ✅ PASS |

---

## Module 4: Financial Reconciliation

| TC ID | Test Name | Type | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-REC-01 | Exact order-to-payment matching | Financial | Match created | PASS | ✅ PASS |
| TC-REC-02 | Partial payment matching with discrepancy | Financial | Partial match flagged | PASS | ✅ PASS |
| TC-REC-03 | Unmatched order/payment visibility | Financial | Both visible in unmatched | PASS | ✅ PASS |
| TC-REC-04 | Settlement-to-bank exact UTR match | Financial | Match created | PASS | ✅ PASS |
| TC-REC-05 | Collision guard blocks auto-match | Financial | Ambiguous flagged | PASS | ✅ PASS |
| TC-REC-06 | Bounded knapsack subset allocation | Financial | Exact subset matched | PASS | ✅ PASS |
| TC-REC-07 | Knapsack bound exceeded → no forced match | Financial | Unresolved, not forced | PASS | ✅ PASS |
| TC-REC-08 | Decimal precision — no float rounding | Financial | Exact Decimal math | PASS | ✅ PASS |
| TC-REC-09 | Dynamic GST rates (never hardcoded 18%) | Financial | Varies by contract | PASS | ✅ PASS |
| TC-REC-10 | Balance conservation in allocations | Financial | Sum conserved | PASS | ✅ PASS |
| TC-REC-11 | Idempotent reruns — no duplicates | Financial | Same result on rerun | PASS | ✅ PASS |
| TC-REC-12 | Manual review allocation and reversal | Functional | RBAC-gated approval | PASS | ✅ PASS |
| TC-REC-13 | Contract versioning and historical runs | Financial | Historical run uses old contract | PASS | ✅ PASS |
| TC-REC-14 | Hypothesis property-based fee rounding | Property | Rounding invariants hold | PASS | ✅ PASS |
| TC-REC-15 | Tenant isolation on reconciliation | Security | Cross-tenant blocked | PASS | ✅ PASS |

---

## Module 5: Revenue Leakage Detection

| TC ID | Test Name | Type | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-LEAK-01 | Missing settlement detector (fully missing) | Financial | Leakage flagged | PASS | ✅ PASS |
| TC-LEAK-02 | Missing settlement (partially missing) | Financial | Partial flag | PASS | ✅ PASS |
| TC-LEAK-03 | Settlement overdue but within grace period | Financial | No flag | PASS | ✅ PASS |
| TC-LEAK-04 | Fresh capture not flagged prematurely | Financial | No flag | PASS | ✅ PASS |
| TC-LEAK-05 | Uncredited settlement — full statement missing | Financial | Leakage flagged | PASS | ✅ PASS |
| TC-LEAK-06 | Uncredited — amount mismatch | Financial | Mismatch flagged | PASS | ✅ PASS |
| TC-LEAK-07 | Duplicate refund detection | Financial | Duplicate flagged | PASS | ✅ PASS |
| TC-LEAK-08 | Retry record not flagged as duplicate | Financial | No false positive | PASS | ✅ PASS |
| TC-LEAK-09 | Excess cumulative refund detection | Financial | Flagged | PASS | ✅ PASS |
| TC-LEAK-10 | Orphan/unauthorized refund | Financial | Flagged | PASS | ✅ PASS |
| TC-LEAK-11 | Fee overcharge detection (MDR) | Financial | Overcharge flagged | PASS | ✅ PASS |
| TC-LEAK-12 | No invented fee deduction without contract | Financial | Zero deduction | PASS | ✅ PASS |
| TC-LEAK-13 | Leakage idempotency (rerun preserves review) | Functional | Review status preserved | PASS | ✅ PASS |
| TC-LEAK-14 | Evidence immutability (cannot mutate) | Data Integrity | ORM blocks mutation | PASS | ✅ PASS |
| TC-LEAK-15 | Evidence deterministic fingerprint | Data Integrity | Same hash on replay | PASS | ✅ PASS |

---

## Module 6: AI Investigation

| TC ID | Test Name | Type | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-AI-01 | Missing API key → PENDING_CONFIGURATION | Functional | Graceful degradation | PASS | ✅ PASS |
| TC-AI-02 | Invalid API key → fails fast | Error Handling | LLMProviderError | PASS | ✅ PASS |
| TC-AI-03 | Rate limit retry and recovery | Resilience | Retry with backoff | PASS | ✅ PASS |
| TC-AI-04 | Timeout handling and exhaustion | Resilience | Timeout error returned | PASS | ✅ PASS |
| TC-AI-05 | Successful response parsing | Functional | Valid analysis returned | PASS | ✅ PASS |
| TC-AI-06 | Prompt guardrails — read-only enforced | Safety | No calculations in prompt | PASS | ✅ PASS |
| TC-AI-07 | Ungrounded output filtered | Safety | Hallucinated IDs stripped | PASS | ✅ PASS |
| TC-AI-08 | Dashboard status = PENDING when no key | Integration | PENDING_CONFIGURATION | PASS (live API) | ✅ PASS |
| TC-AI-09 | Live Gemini API connectivity | Integration | Live HTTP response | SKIP (no key) | 🔵 BLOCKED |
| TC-AI-10 | Mock adapter — valid response | Mock | Structured response | PASS | ✅ PASS |
| TC-AI-11 | Mock adapter — simulated timeout | Mock | Timeout error | PASS | ✅ PASS |

---

## Module 7: Security

| TC ID | Test Name | Type | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-SEC-01 | OWASP headers present | Security | X-Frame, X-CT, CSP | All present (live) | ✅ PASS |
| TC-SEC-02 | SQL injection via URL parameter | Security | No injection | HTTP 200, no data leak | ✅ PASS |
| TC-SEC-03 | CSV DDE formula injection | Security | Sanitized | PASS | ✅ PASS |
| TC-SEC-04 | AI prompt injection | Security | Escaped | PASS | ✅ PASS |
| TC-SEC-05 | Cross-tenant data isolation | Security | Blocked | PASS | ✅ PASS |
| TC-SEC-06 | RBAC role enforcement (3 roles) | Security | Correct 403s | PASS | ✅ PASS |
| TC-SEC-07 | Sensitive data log redaction | Security | Key patterns redacted | PASS | ✅ PASS |
| TC-SEC-08 | Evidence immutability (ORM-level) | Integrity | Mutation blocked | PASS | ✅ PASS |
| TC-SEC-09 | Forensic data deletion blocked | Integrity | FK constraint | PASS | ✅ PASS |

---

## Module 8: End-to-End API (Live Server)

| TC ID | Test Name | Expected | Actual | Status |
|---|---|---|---|---|
| TC-E2E-01 | Register → Login → Auth/Me flow | 201, 200, 200 | 201, 200, 200 | ✅ PASS |
| TC-E2E-02 | Dashboard overview after login | HTTP 200, dict | HTTP 200, dict | ✅ PASS |
| TC-E2E-03 | AI investigations shows PENDING | HTTP 200, PENDING | HTTP 200, PENDING | ✅ PASS |
| TC-E2E-04 | Leakage summary accessible | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-E2E-05 | Recon runs list (empty tenant) | HTTP 200, [] | HTTP 200, [] | ✅ PASS |
| TC-E2E-06 | Review queue accessible | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-E2E-07 | Fee analytics accessible | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-E2E-08 | Audit logs accessible | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-E2E-09 | Bad JWT → 401 | HTTP 401 | HTTP 401 | ✅ PASS |
| TC-E2E-10 | No auth → 401 | HTTP 401 | HTTP 401 | ✅ PASS |
| TC-E2E-11 | Wrong password → 401 | HTTP 401 | HTTP 401 | ✅ PASS |
| TC-E2E-12 | SQL injection in param | HTTP 200 (safe) | HTTP 200 | ✅ PASS |
| TC-E2E-13 | OWASP headers live | All present | All present | ✅ PASS |
| TC-E2E-14 | Duplicate email → 400 | HTTP 400 | HTTP 400 | ✅ PASS |
| TC-E2E-15 | Leakage exceptions list | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-E2E-16 | Reconciliation contracts | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-E2E-17 | Tenants endpoint | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-E2E-18 | Leakage runs list | HTTP 200 | HTTP 200 | ✅ PASS |
| TC-E2E-19 | Health liveness probe | ALIVE | ALIVE | ✅ PASS |
| TC-E2E-20 | Health readiness probe | READY, CONNECTED | READY, CONNECTED | ✅ PASS |

---

## Summary

| Module | Total | PASS | FAIL | BLOCKED |
|---|---|---|---|---|
| Authentication | 12 | 12 | 0 | 0 |
| Dashboard API | 8 | 8 | 0 | 0 |
| Data Ingestion | 11 | 11 | 0 | 0 |
| Financial Reconciliation | 15 | 15 | 0 | 0 |
| Revenue Leakage | 15 | 15 | 0 | 0 |
| AI Investigation | 11 | 10 | 0 | 1 |
| Security | 9 | 9 | 0 | 0 |
| End-to-End API | 20 | 20 | 0 | 0 |
| **TOTAL** | **101** | **100** | **0** | **1** |
