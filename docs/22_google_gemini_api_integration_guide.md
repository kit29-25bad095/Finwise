# Finora — Google Gemini API Integration Guide & Forensic AI Governance

**Document Reference:** FINORA-AI-GEMINI-INTEGRATION-V1  
**Target Subsystem:** Phase 5 — AI Forensic Root Cause Investigator & Dispute Claim Draft Generator  
**SDK:** `google-genai` (v2.26.0)  
**Default Model:** `gemini-2.0-flash` (Configurable: `gemini-1.5-pro`, `gemini-1.5-flash`)  
**Status:** Architecture Implemented & Tested (Mocked Contract Verified + Live Connectivity Ready)

---

## 1. Overview & Architectural Boundaries

Finora integrates the Google Gemini API to analyze deterministic revenue leakage exceptions produced by Phase 4 and generate structured, human-readable forensic explanations.

### Strictly Enforced Invariants:
1. **Read-Only Advisory Function:** The AI model is strictly an explanatory advisor. It has zero operational authority to resolve exceptions, auto-approve claims, alter allocations, or execute database updates.
2. **Zero Calculation Rule:** The model is prohibited from computing, estimating, or recalculating any monetary sums, fees, taxes, or leakage amounts. All numbers are computed deterministically by Phase 3 & 4 engines and provided to Gemini as read-only strings.
3. **Zero Evidence Fabrication:** Every citation in Gemini's response must reference an exact, verified evidence ID from the input bundle. Any ungrounded or hallucinated evidence references are stripped by `ConfidenceEvaluator`, and confidence is mathematically downgraded.
4. **Credential Isolation:** The API key (`GEMINI_API_KEY`) is stored strictly server-side in the backend environment. It is never transmitted to the frontend browser, never output in logs, and never committed to version control.
5. **Graceful Degraded State (`PENDING_CONFIGURATION`):** When `GEMINI_API_KEY` is not present, the system operates deterministically with zero interruption, and the dashboard displays `PENDING_CONFIGURATION`.

---

## 2. Configuration & Secure Provisioning

### 2.1 Supported Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Google Gemini API key (recommended) | `None` |
| `AI_API_KEY` | Alternate alias for Gemini or AI provider key | `None` |
| `AI_PROVIDER` | Active AI provider (`gemini` or `mock`) | `gemini` |
| `AI_MODEL` | Target Google GenAI model | `gemini-2.0-flash` |
| `AI_TEMPERATURE` | Generation temperature (low for deterministic consistency) | `0.1` |
| `AI_MAX_TOKENS` | Maximum output token ceiling | `2048` |

### 2.2 Secure Setup Instructions (Safe Credentials Protocol)

To configure your API key without leaking it into shell history or chat logs:

1. Obtain an API key from Google AI Studio: [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
2. Set the environment variable in your terminal session or `.env` file:

**Windows PowerShell:**
```powershell
$env:GEMINI_API_KEY = "your-actual-gemini-api-key"
```

**Linux / macOS Bash:**
```bash
export GEMINI_API_KEY="your-actual-gemini-api-key"
```

**Local `.env` File (Ignored by Git):**
```ini
GEMINI_API_KEY=AIzaSy...your-actual-api-key...
```

*Note: `.env` is listed in `.gitignore` to prevent accidental credential leakage.*

---

## 3. Resilience, Retries & Error Handling

The `GeminiLLMAdapter` implements enterprise-grade resilience:

1. **Explicit Timeout Protection:** Every call to `client.aio.models.generate_content` is wrapped in an `asyncio.timeout(30.0)` guard.
2. **Exponential Backoff on Rate Limits:** Catches HTTP 429 (`RESOURCE_EXHAUSTED` / quota exhaustion) and performs exponential backoff ($2^{\text{attempt}}$ seconds) up to `max_retries` (3 attempts).
3. **Fast-Failure on Client Authentication Errors:** HTTP 400/401/403 or invalid API keys fail immediately without wasting time on retries, raising `LLMProviderError("Gemini API authentication failed: Invalid or expired API key")`.
4. **Structured JSON Parsing:** Extracts and parses structured JSON from `response.text`, cleanly stripping markdown backticks (` ```json `) and isolating the outermost JSON object if preamble text is present.

---

## 4. Anti-Hallucination & Evidence Citation Verification

Before any AI response is saved or displayed:
1. `EvidenceValidator` verifies SHA-256 fingerprints of all input evidence.
2. `ConfidenceEvaluator.evaluate()` audits every hypothesis:
   - Matches cited `supporting_evidence_ids` against `verified_evidence_ids`.
   - Any hallucinated ID is removed from citations.
   - A warning is recorded under `missing_evidence`.
   - Global confidence is deterministically calculated using exact evidence item counts.

---

## 5. Verification & Test Suite

The test suite is organized into distinct categories:

| Test File | Focus | Execution Condition |
| :--- | :--- | :--- |
| `backend/tests/test_gemini_integration.py` | Unit & Contract Tests (Missing key, invalid key fast-fail, rate limits, timeouts, prompt guardrails, ungrounded output filtering, dashboard status) | Always runs (Mocked SDK) |
| `backend/tests/test_gemini_integration.py::test_live_gemini_api_connectivity` | Live End-to-End Google Gemini API connectivity test | Runs ONLY when live `GEMINI_API_KEY` is present in environment |
| `backend/tests/test_forensic_*.py` | 8 dedicated forensic test modules (RBAC, evidence integrity, confidence evaluator, claim drafts, security) | Always runs (100% passing) |
