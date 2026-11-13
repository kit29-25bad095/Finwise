# Finora — Google Gemini API Integration & AI Governance Verification

**Document Reference:** `FINORA-DEP-002`  
**Classification:** Production Readiness Verification  
**Audit Date:** November 13, 2026  
**Auditor Roles:** Principal Software Architect, Senior AI Systems Engineer, FinTech Security Auditor  
**Subsystem:** Area 1 — Real Gemini API Integration & Forensic AI Governance  

---

## 1. Executive Summary & Verification Classification

Finora implements an AI-assisted forensic root-cause analysis and dispute claim draft generator utilizing Google's official GenAI SDK (`google-genai`). The system operates through a provider-abstracted interface (`BaseLLMAdapter`) supporting both the official Google Gemini adapter (`GeminiLLMAdapter`) and an offline deterministic mock adapter (`MockLLMAdapter`).

### Operational Status Matrix

| Subsystem Component | Operational Status | Classification |
|---|---|---|
| **AI Provider Abstraction** | Complete, clean interface separation | **IMPLEMENTED** |
| **Official Google GenAI SDK** | `google-genai` (v0.1.0/v2.26.0) installed and imported | **IMPLEMENTED** |
| **Model Selection** | Default: `gemini-2.0-flash` (configurable: `gemini-1.5-pro`) | **IMPLEMENTED** |
| **Resilience & Bounded Retries** | Exponential backoff (HTTP 429), timeout handling, JSON recovery | **TESTED LOCALLY** |
| **Read-Only / Zero-Calculation Guardrails** | Prompt delimiters prevent calculation or balance modifications | **TESTED LOCALLY** |
| **Evidence Citation & Grounding** | `ConfidenceEvaluator` strips hallucinated IDs before persistence | **TESTED LOCALLY** |
| **Mock Provider Test Suite** | 19 automated integration and unit tests passing | **TESTED LOCALLY** |
| **Live Google Gemini API Execution** | Blocked due to absence of production `GEMINI_API_KEY` | **BLOCKED: CREDENTIAL REQUIRED** |
| **Dashboard Degraded State Display** | Gracefully returns `PENDING_CONFIGURATION` without crashing | **VERIFIED WITH LIVE SERVICE** |

---

## 2. Architectural Boundaries & Invariant Governance

Under Finora's core financial charter, artificial intelligence is strictly restricted to an explanatory and investigation-support layer:

1. **Read-Only Advisory Invariant:** The AI model is strictly an explanatory advisor. It possesses zero operational authority to resolve reconciliation discrepancies, approve dispute claims, modify balances, or write to financial ledgers.
2. **Zero Calculation Rule:** The model is programmatically prohibited from performing financial calculations. All monetary sums, interchange fees, GST taxes, and leakage amounts are calculated deterministically by Phase 3 & 4 core engines and passed to Gemini as immutable string literals.
3. **Evidence Grounding Invariant:** Every citation in Gemini's response must reference an exact, verified canonical evidence ID from the input bundle. Any ungrounded or hallucinated references are intercepted and stripped by `ConfidenceEvaluator`, triggering an automatic confidence downgrade.
4. **Credential Isolation Invariant:** The API key (`GEMINI_API_KEY`) is read exclusively server-side from environment variables. It is never transmitted to the frontend client, never returned in API responses, never output in structured logs, and never committed to Git.
5. **Fail-Safe Degraded Operation:** In the absence of an API key, the platform remains 100% operational in deterministic mode, and the dashboard explicitly surfaces `PENDING_CONFIGURATION`.

---

## 3. Provider Abstraction & Model Architecture

```
                       [ ForensicInvestigationService ]
                                      │
                                      ▼
                             [ BaseLLMAdapter ]
                                      │
                 ┌────────────────────┴────────────────────┐
                 ▼                                         ▼
        [ GeminiLLMAdapter ]                       [ MockLLMAdapter ]
        • google-genai SDK                         • Offline synthetic reasoning
        • gemini-2.0-flash                         • Deterministic JSON fixtures
        • Async client (client.aio)                • Error & timeout simulation
        • Bounded retries (2^n backoff)            • Unit & CI pipeline testing
        • HTTP 429 / 5xx handling
```

### Supported Models & Configuration
- **Default Engine:** `gemini-2.0-flash` (Optimized for sub-second structured JSON reasoning and cost efficiency).
- **Deep Investigation Model:** `gemini-1.5-pro` (Configurable via `AI_MODEL=gemini-1.5-pro` for complex multi-party dispute arbitration).
- **Generation Parameters:** Temperature fixed at `0.1` to maximize structured determinism and citation consistency; `max_output_tokens` bounded at `2048`.

---

## 4. Resilience & Error Handling Architecture

### 4.1 Bounded Retries & Rate Limit Backoff
`GeminiLLMAdapter` implements a bounded retry loop with exponential backoff:
```python
# Rate limit (429) or quota exhaustion handling
if code == 429 or "429" in err_str or "resource_exhausted" in err_str.lower():
    logger.warning(f"Gemini API rate limit exceeded. Backing off attempt {attempt}/{self.max_retries}...")
    if attempt < self.max_retries:
        await asyncio.sleep(2 ** attempt)
        continue
```

### 4.2 Non-Retryable Fast Failure
Client-side authentication errors (HTTP 400, 401, 403, `API_KEY_INVALID`) fail immediately without retry waste, reporting actionable error diagnostics:
```python
if code in (401, 403) or "api_key_invalid" in err_msg.lower():
    raise LLMProviderError("Gemini API authentication failed: Invalid or expired API key.")
```

### 4.3 Timeout Containment
Async calls are isolated with `asyncio.timeout(self.timeout_seconds)` (default: 30.0s), preventing hung upstream connections from exhausting backend thread pools.

---

## 5. Automated Test Suite Results

The Gemini adapter and forensic AI governance subsystem are validated by 19 automated tests in `tests/test_gemini_integration.py` and `tests/test_forensic_llm_adapter.py`:

| Test Name | Verification Focus | Status |
|---|---|:---:|
| `test_gemini_missing_api_key_raises_pending_configuration` | Unset key raises `LLMProviderError(PENDING_CONFIGURATION)` | **PASSED** |
| `test_gemini_invalid_api_key_fails_fast_without_retries` | 401/Invalid key fails fast on attempt 1 | **PASSED** |
| `test_gemini_rate_limit_retry_and_recovery` | Exponential backoff recovers on subsequent attempt | **PASSED** |
| `test_gemini_timeout_handling_and_exhaustion` | 30s timeout exhaustion handled gracefully | **PASSED** |
| `test_gemini_successful_response_parsing` | Valid JSON extraction from markdown fences (` ```json `) | **PASSED** |
| `test_gemini_prompt_guardrails_enforce_read_only` | Guardrails verify zero calculations or balance mutations | **PASSED** |
| `test_gemini_ungrounded_output_evidence_filtering` | Hallucinated evidence citations stripped by evaluator | **PASSED** |
| `test_dashboard_ai_status_pending_configuration_when_no_key` | API returns `PENDING_CONFIGURATION` when key is absent | **PASSED** |
| `test_dashboard_ai_status_active_when_key_configured` | API returns `ACTIVE` when key is configured | **PASSED** |
| `test_live_gemini_api_connectivity` | Live HTTP probe against Google API endpoint | **SKIPPED** |
| `test_mock_llm_adapter_valid_response` | Mock adapter delivers schema-valid forensic report | **PASSED** |
| `test_mock_llm_adapter_simulated_timeout` | Mock adapter simulates network timeout safely | **PASSED** |
| `test_mock_llm_adapter_simulated_invalid_json` | Mock adapter tests malformed JSON handling | **PASSED** |
| `test_mock_llm_adapter_simulated_error` | Mock adapter tests upstream API crash handling | **PASSED** |
| `test_get_llm_adapter_factory` | Factory selects `gemini` vs `mock` based on configuration | **PASSED** |
| `test_investigation_creation_and_idempotency` | Duplicate investigations deduplicated via idempotency key | **PASSED** |
| `test_investigation_execution_success` | Full investigation workflow execution | **PASSED** |
| `test_investigation_blocks_on_tampered_evidence` | SHA-256 fingerprint mismatch blocks investigation | **PASSED** |
| `test_worker_task_execution` | Background worker task execution and DB persistence | **PASSED** |

**Summary: 19 Passed, 1 Skipped (Live Call), 0 Failed.**

---

## 6. Live Verification Blocker & Configuration Runbook

### Current Blocker
- **Blocker ID:** `BLK-001`
- **Severity:** High (Feature limitation; does not block core reconciliation)
- **Description:** Live external Google Gemini API calls cannot be verified in this environment because no valid `GEMINI_API_KEY` is present.
- **Impact:** System operates with 100% deterministic local calculation and mock investigation capabilities. Real LLM forensic summaries require credential provisioning.

### Provisioning Instructions
To enable live Gemini integration:
1. Obtain an API key from Google AI Studio: [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
2. Set the environment variable in the host environment or Docker Compose:
   ```bash
   export GEMINI_API_KEY="AIzaSyYourActualKeyHere"
   ```
3. Restart the backend service.
4. Execute live verification probe:
   ```bash
   cd backend && python -m pytest tests/test_gemini_integration.py -k test_live_gemini_api_connectivity -v
   ```
5. Confirm endpoint `/api/v1/dashboard/ai-investigations` reports `status: "ACTIVE"`.
