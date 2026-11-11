# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine
# Document 04: Revised Reconciliation and Allocation Engine Design (Configurable Bounds & Anti-Collision)

**Project Name:** Finora  
**Document Reference:** FINORA-RECON-ALLOC-V3  
**Classification:** Financial Engine Specification  
**Author:** Senior Financial Systems Engineer, Principal Software Architect  
**Status:** Under Formal Architectural Review (Phase 0 - Revision 3)  
**Date:** November 2026  

---

## 1. Executive Summary & Design Principles

The Finora Reconciliation & Allocation Engine is a pure, deterministic state machine bridging Shopify Orders, Gateway Settlements, and Bank Transactions.

### Non-Negotiable Financial Laws
- **Double-Entry Balance Conservation:** An allocation increases `allocated_amount` on both source and target records while decrementing `unallocated_balance` by the identical quantum.
- **Zero-Speculation Guarantee:** The engine **never forces a match**. If algorithmic confidence is split, or if search bounds are exceeded, the engine quarantines the transaction and defers to human review.
- **Configurable Parameters:** All weights, bounds, thresholds, and calendars are configurable per tenant and contract.

---

## 2. Multi-Pass Reconciliation Pipeline

```
+----------------------------------------------------------------------------------------------------+
|                                DETERMINISTIC RECONCILIATION PIPELINE                               |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 1: Exact Gateway Payment ID / Order Reference Match                                           |
| - Domain: Orders <───> Payment Captures                                                            |
| - Method: Direct Index Lookup on (tenant_id, gateway_payment_id) or (order_reference)              |
| - Confidence Score: 1.0000 (Deterministic Identity)                                                |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 2: Exact Settlement Batch UTR Match                                                           |
| - Domain: Settlement Batches <───> Bank Transactions                                               |
| - Method: Exact string match between Settlement.utr_number and Bank.extracted_utr                  |
| - Validation: Settlement.net_settlement_amount == Bank.credit_amount                               |
| - Confidence Score: 1.0000 (Deterministic Identity)                                                |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 3: Exact Net Amount & Banking Window Proximity Match                                          |
| - Domain: Unallocated Settlement Batches <───> Unallocated Bank Transactions                       |
| - Condition: Net Amount match within configurable banking window [T, T + window_days]              |
| - Collision Guard: Fails if multiple candidate batches share identical amount in window           |
| - Confidence Score: 0.9500                                                                         |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 4: Normalized Reference & Bank Narration Fuzzy Token Match                                    |
| - Multi-Factor Candidate Scoring Engine (Formula below)                                            |
| - Threshold: Auto-match if Score >= min_match_score AND Score Delta >= min_collision_delta         |
| - Otherwise: Routes to Pass 6 (Human Review)                                                       |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 5: Controlled Multi-Record Aggregated Allocation (Bounded Knapsack / Subset Sum)              |
| - Domain: Single Bank Credit <───> Multiple Settlement Batches                                     |
| - Bounds: Configurable max items N (default N=5, max N=8). Bounded subset search.                  |
| - NEVER FORCE MATCH: If sum cannot be matched within N items, or if multiple subsets match:        |
|   --> ZERO auto-allocation. Transition to UNRESOLVED_SUBSET_BOUND_EXCEEDED.                         |
|   --> Routes directly to Pass 6 (Human Review).                                                    |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| PASS 6: Ambiguity Isolation & Human Review Queue                                                   |
| - Conflicting candidates, near-score collisions, and bound-exceeded subsets.                       |
| - Action: Zero auto-allocation. Surfaces side-by-side candidates in Finance Review Queue.          |
+----------------------------------------------------------------------------------------------------+
```

---

## 3. Multi-Factor Candidate Scoring Engine (Pass 4)

When bank statements truncate UTRs or combine reference numbers with generic narrations:
$$\text{Score}(S_j, B_k) = w_{\text{utr}} \cdot \mathcal{S}_{\text{utr}} + w_{\text{amt}} \cdot \mathcal{S}_{\text{amt}} + w_{\text{date}} \cdot \mathcal{S}_{\text{date}} + w_{\text{narr}} \cdot \mathcal{S}_{\text{narr}}$$

### 3.1 Configurable Weights & Thresholds (Tenant Defaults)
- $w_{\text{utr}} = 0.40$ (UTR / reference token presence)
- $w_{\text{amt}} = 0.35$ (Exact net amount equality)
- $w_{\text{date}} = 0.15$ (Value date proximity to settlement date)
- $w_{\text{narr}} = 0.10$ (Narration token overlap)
- $\text{min\_auto\_match\_score} = 0.9000$
- $\text{min\_collision\_delta} = 0.1500$

### 3.2 Anti-Collision Thresholding Rule
Let $C_1, C_2$ be the highest and second-highest scoring bank candidates for settlement $S_j$:
$$\text{AutoMatch}(S_j, C_1) \iff \text{Score}(S_j, C_1) \ge \text{min\_auto\_match\_score} \land (\text{Score}(S_j, C_1) - \text{Score}(S_j, C_2) \ge \text{min\_collision\_delta})$$

**If the score difference is less than $\text{min\_collision\_delta}$, auto-matching is strictly blocked.** The candidates transition to `AMBIGUOUS_CANDIDATE` and require human review.

---

## 4. Multi-Record Allocation Engine (Pass 5) & The Never-Force-Match Guarantee

### 4.1 Problem Formulation
Payment gateways frequently aggregate multiple distinct settlement batches into a single consolidated bank payout (e.g. nodal clearing for Friday + Saturday + Sunday batches).

### 4.2 Algorithm & Bound Enforcement
Given unallocated bank credit $B_k$ with credit value $V_B$:
1. Query candidate unallocated settlement batches $\mathcal{C} = \{S_1, S_2, \dots, S_m\}$ where:
   $$t(B_k) - \text{max\_search\_window\_days} \le t(S_i) \le t(B_k)$$
2. Search for subset $\mathcal{S}^* \subseteq \mathcal{C}$ such that:
   $$\sum_{S_i \in \mathcal{S}^*} S_i.\text{net\_amount} = V_B \quad \land \quad |\mathcal{S}^*| \le N_{\text{max\_bound}}$$
   *(Default $N_{\text{max\_bound}} = 5$, configurable per tenant up to 8).*

### 4.3 Fallback and Review Routing
- **Case A: Exactly One Unique Subset Found:** Create atomic allocations $A_{i, k}$ for each $S_i \in \mathcal{S}^*$. Decrement balances to zero.
- **Case B: No Subset Found within $N_{\text{max\_bound}}$:** 
  - The engine **DOES NOT force a partial match or approximate allocation**.
  - Mark status as `UNRESOLVED_SUBSET_BOUND_EXCEEDED`.
  - Route $B_k$ and candidate set $\mathcal{C}$ directly to Pass 6 (Human Review).
- **Case C: Multiple Subsets Match $V_B$ (Combinatorial Collision):**
  - Halt auto-allocation immediately.
  - Mark status as `AMBIGUOUS_AGGREGATION_COLLISION`.
  - Route to Pass 6 (Human Review) with both candidate subsets displayed for manual selection.

---

## 5. Immutable Run Versioning & Atomic Transition

Reconciliation runs are immutable. Re-running reconciliation never mutates historical allocations in place:

```
[User Triggers Rerun]
         │
         ▼
[Create Run N+1: Status = 'IN_PROGRESS']
         │
         ▼
[Acquire Distributed Redis Tenant Lock]
         │
         ▼
[Execute Passes 1 through 5 in Transaction]
         │
         ├─────────────────────────────────────────────┐
         ▼                                             ▼
[Success: Atomic State Transition]             [Error / Timeout]
- Mark Run N Allocations -> 'SUPERSEDED'       - Rollback Transaction
- Mark Run N+1 Allocations -> 'ACTIVE'         - Release Redis Lock
- Carry Forward Manual Review Decisions       - Set Run N+1 -> 'FAILED'
- Generate Run Deltas Table                    - Run N remains 'ACTIVE'
- Release Redis Lock
```

---
*(End of Document 04 — Revised Reconciliation & Allocation Engine Design V3)*
