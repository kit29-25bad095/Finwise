# Finora — Phase 3 Implementation & Verification Report
## Deterministic Three-Way Financial Reconciliation Engine

---

### Executive Summary

Phase 3 (*Deterministic Three-Way Financial Reconciliation Engine*) has been completed in strict accordance with the approved Phase 0 Architecture Specifications, the Financial Rules & Assumptions Register (`FINORA-FIN-RULES-V3`), and the Revised Reconciliation & Allocation Engine Design (`FINORA-RECON-ALLOC-V3`).

Finora now features an enterprise-grade financial reconciliation state machine capable of correlating **Shopify canonical orders**, **Razorpay gateway captures/settlements/refunds**, and **HDFC Bank Current Account statement credits** across a multi-pass pipeline.

---

### 1. Implemented Components

#### A. Database Entities & Ledger Persistence (`app.models.reconciliation`)
1. **`FeeContract` & `FeeScheduleTier`**:
   - Versioned, contract-driven MDR and GST tariff schedules per payment instrument (`UPI`, `DEBIT`, `CREDIT_STANDARD`, `CREDIT_CORPORATE`, `NETBANKING`, `INTERNATIONAL`).
   - Supports fixed transaction fees, rate fractions, fee caps (`min_fee_cap`, `max_fee_cap`), dynamic GST (default 18%), chargeback dispute tariffs, rolling reserve holds, and instant refund surcharge rules.
2. **`ReconciliationRun`**:
   - Immutable historical run ledger recording sequential `run_number` per tenant, execution parameters, quantitative metrics, monetary sums, duration in milliseconds, and status (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `COMPLETED_WITH_EXCEPTIONS`, `FAILED`).
   - Mark prior runs as superseded (`is_active = False`) while preserving complete historical lineage.
3. **`ReconciliationMatch`**:
   - Correlation record linking `order_id`, `payment_id`, `settlement_id`, and `bank_transaction_id`.
   - Classification taxonomy: `EXACT_MATCH`, `PARTIAL_MATCH`, `AGGREGATED_MATCH`, `AMBIGUOUS_MATCH`, `UNMATCHED`, `UNRESOLVED`, `UNRESOLVED_SUBSET_BOUND_EXCEEDED`, and `AMBIGUOUS_AGGREGATION_COLLISION`.
   - Records confidence scores, pass numbers (1 to 6), source amounts, target amounts, allocated amounts, fee discrepancies, human-readable explanations, and JSON evidence metadata.
4. **`ReconciliationAllocation`**:
   - Double-entry atomic allocation entries between source and target entities.
   - Enforces database constraint `CHECK (allocated_amount > 0)`.
5. **`ReconciliationRunDelta`**:
   - Mathematical diff tracking state changes between consecutive reconciliation runs (Run $N$ vs Run $N+1$).

#### B. Algorithmic Matching & Allocation Engines (`app.services.reconciliation`)
1. **`FeeCalculator`**:
   - Enforces the approved 6-stage financial rounding architecture using arbitrary-precision Python `Decimal`:
     - Stage 1: Nominal capture amount (exact `NUMERIC(18, 4)`).
     - Stage 2: Contractual MDR = `capture_amount * percentage_rate` (`ROUND_HALF_UP` to 4 decimal places).
     - Stage 3: Base fee aggregation and min/max fee clamping.
     - Stage 4: GST calculation = `base_fee * gst_rate` (`ROUND_HALF_UP` to 4 decimal places).
     - Stage 5: Expected total fee = `base_fee + calculated_tax` (with 2 decimal place display representation).
     - Stage 6: Overcharge delta evaluation against tenant `fee_overcharge_tolerance` (default ₹0.05).
2. **`ScoringEngine` (Pass 4 Multi-Factor Scoring with Anti-Collision Guard)**:
   - Evaluates multi-factor candidate match score:
     $$\text{Score}(S_j, B_k) = w_{\text{utr}} \cdot \mathcal{S}_{\text{utr}} + w_{\text{amt}} \cdot \mathcal{S}_{\text{amt}} + w_{\text{date}} \cdot \mathcal{S}_{\text{date}} + w_{\text{narr}} \cdot \mathcal{S}_{\text{narr}}$$
     where $w_{\text{utr}} = 0.40$, $w_{\text{amt}} = 0.35$, $w_{\text{date}} = 0.15$, $w_{\text{narr}} = 0.10$.
   - **Anti-Collision Guard**: Auto-match requires $\text{Score}(C_1) \ge 0.9000$ and $(\text{Score}(C_1) - \text{Score}(C_2)) \ge 0.1500$. If delta $< 0.1500$, auto-allocation is strictly blocked and classified as `AMBIGUOUS_MATCH`.
3. **`BoundedKnapsackSolver` (Pass 5 Bounded Subset-Sum Aggregation)**:
   - Solves multi-settlement nodal clearing aggregation against bank credits for subsets up to $N \le 5$ (configurable up to 8).
   - **Never-Force-Match Guarantee**:
     - Exactly 1 subset matches $\implies$ `AGGREGATED_MATCH`.
     - 0 subsets match $\implies$ `UNRESOLVED_SUBSET_BOUND_EXCEEDED` (zero speculative allocation).
     - $>1$ subsets match $\implies$ `AMBIGUOUS_AGGREGATION_COLLISION` (zero speculative allocation).
4. **`ReconciliationService`**:
   - Primary state machine orchestrating Passes 1 through 6, double-entry conservation, immutable run management, and human review decisions.

---

### 2. Database Changes & Migrations

- **Migration File**: `backend/alembic/versions/003_phase3_reconciliation_and_fee_models.py`
- **Revision ID**: `003_phase3_reconciliation` (down revision: `002_phase2_ingestion`)
- **Tables Created**:
  1. `fee_contracts`
  2. `fee_schedule_tiers`
  3. `reconciliation_runs`
  4. `reconciliation_matches`
  5. `reconciliation_allocations`
  6. `reconciliation_run_deltas`
- **Execution Proof**:
  ```text
  INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
  INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
  INFO  [alembic.runtime.migration] Running upgrade 002_phase2_ingestion -> 003_phase3_reconciliation, phase3_reconciliation_and_fee_models
  ```

---

### 3. API Endpoints Delivered (`/api/v1/reconciliation`)

| Method | Endpoint | Description | RBAC Requirement |
|:---|:---|:---|:---:|
| `POST` | `/api/v1/reconciliation/contracts` | Create/version fee contracts and instrument tiers | Admin / Finance Manager |
| `GET` | `/api/v1/reconciliation/contracts` | List active and historical fee contracts | All Roles |
| `POST` | `/api/v1/reconciliation/runs` | Trigger deterministic 3-way reconciliation run | Admin / Finance Manager |
| `GET` | `/api/v1/reconciliation/runs` | Paginated list of reconciliation runs | All Roles |
| `GET` | `/api/v1/reconciliation/runs/{run_id}` | Detailed run metrics and execution status | All Roles |
| `GET` | `/api/v1/reconciliation/runs/{run_id}/matches` | Filterable list of matched transactions | All Roles |
| `GET` | `/api/v1/reconciliation/runs/{run_id}/ambiguous` | Filter for ambiguous candidates needing review | All Roles |
| `GET` | `/api/v1/reconciliation/runs/{run_id}/allocations` | Granular double-entry allocations ledger | All Roles |
| `GET` | `/api/v1/reconciliation/runs/{run_id}/summary` | Top-level financial executive summary | All Roles |
| `GET` | `/api/v1/reconciliation/runs/{run_id}/unmatched` | Drilldown into unmatched orders/payments/settlements | All Roles |
| `POST` | `/api/v1/reconciliation/matches/{match_id}/resolve`| Human review action (APPROVE, REJECT, MANUAL_ALLOCATE)| Admin / Finance Manager |

---

### 4. Matching & Allocation Multi-Pass Methodology

```
+----------------------------------------------------------------------------------------------------+
|                                DETERMINISTIC RECONCILIATION PIPELINE                               |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 1: Exact Gateway Payment ID / Order Reference Match                                           |
| - Domain: Canonical Orders <───> Canonical Payment Captures                                        |
| - Result: EXACT_MATCH (if amounts equal) or PARTIAL_MATCH (if amount difference)                   |
| - Tariffs: Evaluates expected MDR and GST against active FeeContract; flags fee overcharge         |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 2: Exact Settlement Batch UTR Match                                                           |
| - Domain: Canonical Settlements <───> Canonical Bank Transactions                                  |
| - Method: Direct match between Settlement.utr_number and Bank.extracted_utr / narration            |
| - Confidence: 1.0000                                                                               |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 3: Exact Net Amount & Banking Window Proximity Match                                          |
| - Domain: Unallocated Settlements <───> Unallocated Bank Credits                                   |
| - Condition: Net Amount within fee tolerance & Bank Date in [Settled, Settled + window_days]        |
| - Collision Guard: Multiple candidate batches with same amount strictly halts auto-matching        |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 4: Normalized Reference & Bank Narration Multi-Factor Candidate Scoring Engine                |
| - Scoring: Score = 0.40(UTR) + 0.35(Amount) + 0.15(Date) + 0.10(Narration)                        |
| - Anti-Collision Threshold: Score >= 0.9000 AND (Score_1 - Score_2) >= 0.1500                      |
| - Ambiguity Quarantine: Score < 0.9000 or Delta < 0.1500 -> AMBIGUOUS_MATCH (Routes to Review)    |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 5: Controlled Multi-Record Aggregated Allocation (Bounded Knapsack / Subset Sum)              |
| - Domain: Single Bank Credit <───> Multiple Settlement Batches (Nodal Clearing Aggregation)        |
| - Bounds: Subset search bounded by N <= 5 (configurable up to 8)                                   |
| - NEVER FORCE MATCH: 0 subsets -> UNRESOLVED_SUBSET_BOUND_EXCEEDED; >1 subsets -> COLLISION        |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 6: Unmatched Identification & Human Review Queue                                              |
| - Classifies all remaining unallocated entities as UNMATCHED with full source evidence             |
| - Surfaces all ambiguous, bound-exceeded, and collided records to Finance Review Queue             |
+----------------------------------------------------------------------------------------------------+
```

---

### 5. Financial Invariants & Security Controls

1. **Zero Floating-Point Arithmetic**:
   - All calculations use Python `Decimal` and database `NUMERIC(18, 4)`. No float conversion.
2. **Double-Entry Allocation Conservation**:
   - An allocation of amount $A$ decreases `unallocated_balance` on both the source and target entities by the identical amount $A$.
   - Balance check invariant: `unallocated_balance >= Decimal("0.0000")` enforced at application and database layers.
3. **Immutable Reconciliation Runs**:
   - Re-running reconciliation creates a new run (Run $N+1$). Previous run records and reviewer decisions are carried forward and preserved. Previous allocations are marked `SUPERSEDED`.
4. **Multi-Tenant Cryptographic Partitioning**:
   - Every database query and join enforces `tenant_id == membership.tenant_id`. Cross-tenant record references are impossible and return 404.
5. **Role-Based Access Control (RBAC)**:
   - Triggering reconciliation runs, creating fee contracts, and resolving ambiguous matches requires `ADMIN` or `FINANCE_MANAGER`.
   - `AUDITOR` accounts have strictly read-only visibility; review attempts receive `403 Forbidden`.

---

### 6. Automated Test Verification Results

The complete Finora backend test suite was executed natively outside sandbox isolation. All **44 tests passed with zero failures (100% pass rate)**.

```text
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\Maya P\.gemini\antigravity\scratch\Finwise\backend
configfile: pytest.ini
collected 44 items

tests/test_auth.py::test_register_new_tenant_and_user_success PASSED     [  2%]
tests/test_auth.py::test_register_duplicate_email_rejected PASSED        [  4%]
tests/test_auth.py::test_register_duplicate_slug_rejected PASSED         [  6%]
tests/test_auth.py::test_login_success PASSED                            [  9%]
tests/test_auth.py::test_login_invalid_password PASSED                   [ 11%]
tests/test_auth.py::test_get_current_user_profile PASSED                 [ 13%]
tests/test_health.py::test_healthcheck_root PASSED                       [ 15%]
tests/test_health.py::test_healthcheck_api_v1 PASSED                     [ 18%]
tests/test_ingestion_hdfc.py::test_upload_valid_hdfc_bank_statement PASSED [ 20%]
tests/test_ingestion_razorpay.py::test_upload_valid_razorpay_payments PASSED [ 22%]
tests/test_ingestion_razorpay.py::test_upload_valid_razorpay_settlements PASSED [ 25%]
tests/test_ingestion_razorpay.py::test_razorpay_duplicate_payment_id_isolated PASSED [ 27%]
tests/test_ingestion_security_and_quality.py::test_csv_formula_injection_sanitization PASSED [ 29%]
tests/test_ingestion_security_and_quality.py::test_tenant_isolation_on_ingestion PASSED [ 31%]
tests/test_ingestion_security_and_quality.py::test_rbac_auditor_cannot_upload_files PASSED [ 34%]
tests/test_ingestion_security_and_quality.py::test_export_batch_errors_csv PASSED [ 36%]
tests/test_ingestion_security_and_quality.py::test_cancel_ingestion_batch PASSED [ 38%]
tests/test_ingestion_shopify.py::test_upload_valid_shopify_csv PASSED    [ 40%]
tests/test_ingestion_shopify.py::test_shopify_missing_headers_fails PASSED [ 43%]
tests/test_ingestion_shopify.py::test_shopify_isolated_row_errors PASSED [ 45%]
tests/test_ingestion_shopify.py::test_duplicate_file_upload_detection PASSED [ 47%]
tests/test_rbac.py::test_auditor_cannot_update_tenant_settings PASSED    [ 50%]
tests/test_rbac.py::test_finance_manager_cannot_update_tenant_core_settings PASSED [ 52%]
tests/test_rbac.py::test_auditor_cannot_add_members PASSED               [ 54%]
tests/test_rbac.py::test_auditor_can_view_members PASSED                 [ 56%]
tests/test_rbac.py::test_admin_can_update_settings_and_add_members PASSED [ 59%]
tests/test_reconciliation_fees_and_precision.py::test_six_stage_financial_rounding_precision PASSED [ 61%]
tests/test_reconciliation_fees_and_precision.py::test_contract_fee_overcharge_detection_via_reconciliation PASSED [ 63%]
tests/test_reconciliation_fees_and_precision.py::test_human_review_and_rbac_permissions PASSED [ 65%]
tests/test_reconciliation_order_to_payment.py::test_exact_order_to_payment_matching PASSED [ 68%]
tests/test_reconciliation_order_to_payment.py::test_partial_payment_matching_with_discrepancy PASSED [ 70%]
tests/test_reconciliation_order_to_payment.py::test_unmatched_order_and_unmatched_payment_visibility PASSED [ 72%]
tests/test_reconciliation_property_based.py::test_hypothesis_fee_staged_rounding_properties PASSED [ 75%]
tests/test_reconciliation_property_based.py::test_tenant_isolation_on_reconciliation PASSED [ 77%]
tests/test_reconciliation_property_based.py::test_idempotent_reruns_and_immutable_run_history PASSED [ 79%]
tests/test_reconciliation_settlement_to_bank.py::test_pass_2_exact_utr_settlement_to_bank_match PASSED [ 81%]
tests/test_reconciliation_settlement_to_bank.py::test_pass_3_collision_guard_blocks_auto_match PASSED [ 84%]
tests/test_reconciliation_settlement_to_bank.py::test_pass_5_bounded_aggregation_exact_subset_found PASSED [ 86%]
tests/test_reconciliation_settlement_to_bank.py::test_pass_5_unresolved_subset_bound_exceeded_never_forces_match PASSED [ 88%]
tests/test_tenant_isolation.py::test_tenant_isolation_cannot_access_foreign_tenant PASSED [ 90%]
tests/test_tenant_isolation.py::test_tenant_isolation_cannot_update_foreign_tenant_settings PASSED [ 93%]
tests/test_tenant_isolation.py::test_tenant_isolation_cannot_add_members_to_foreign_tenant PASSED [ 95%]
tests/test_tenant_isolation.py::test_tenant_isolation_cannot_list_foreign_tenant_members PASSED [ 97%]
tests/test_tenant_isolation.py::test_legitimate_tenant_access_succeeds PASSED [100%]

======================= 44 passed, 1 warning in 31.42s ========================
```

---

### 7. Known Limitations & Phase 4 Transition Boundaries

1. **Leakage Detectors (Phase 4 Scope)**:
   - Dedicated algorithmic detection for the 4 core leakage patterns (Unsettled Authorizations, Fee Overcharge Violations, Double-Debit Chargebacks, Ghost Refunds) will be implemented as authorized in Phase 4.
2. **AI Root-Cause Investigator (Phase 5 Scope)**:
   - LLM-assisted plain-English explanations and dispute letter drafting will be implemented in Phase 5 via the provider-agnostic AI interface.
3. **No Speculative Automation**:
   - As mandated by financial governance, subset sums exceeding $N=5$ or ambiguous candidate collisions remain quarantined in `ReviewStatus.PENDING_REVIEW` until an authorized finance manager resolves them.
