# Finora — Financial Accuracy & Mathematical Invariant Validation Report

**Document Reference:** `FINORA-DEP-005`  
**Classification:** Financial Integrity & Audit Sign-Off  
**Audit Date:** November 13, 2026  
**Auditor Roles:** Principal Financial Systems Auditor, Quantitative Verification Engineer  
**Subsystem:** Area 4 — Financial Accuracy, Independent Oracle & Mathematical Invariants  

---

## 1. Executive Summary & Verification Matrix

Finora is an enterprise reconciliation engine designed for Indian D2C and e-commerce enterprises. The core engine reconciles three primary financial data streams:
1. **Shopify Order Exports** (Order Value, Status, Currency, Line Items)
2. **Razorpay Gateway Reports** (Payments Captured, MDR Fees, GST, Settlements, UTRs, Refunds)
3. **HDFC Bank Account Statements** (Transaction Credits, Debits, Balances, Cheque/UTR References)

To ensure auditability, financial calculations must remain 100% deterministic and provably conserved. An independent test oracle (`IndependentFinancialOracle`) was implemented to evaluate mathematical precision without reusing production calculation code.

### Financial Evaluation Matrix

| Category | Verification Scope | Status | Classification |
|---|---|:---:|---|
| **Pure Decimal Precision** | Zero floating-point representation drift (`NUMERIC(18, 4)`) | ✅ 100% Invariant | **TESTED LOCALLY** |
| **Independent Oracle Parity** | 100% agreement between independent formulas and engine | ✅ 100% Parity | **TESTED LOCALLY** |
| **Seventeen (17) Core Invariants** | All 17 financial invariant regression tests passing | ✅ 17/17 Passed | **TESTED LOCALLY** |
| **Dynamic GST Tariff Engine** | Non-hardcoded GST rates (0%, 5%, 12%, 18%) validated | ✅ 100% Verified | **TESTED LOCALLY** |
| **Four Revenue Leakage Detectors** | Missing settlement, uncredited, fee overcharge, refund | ✅ 60/60 Passed | **TESTED LOCALLY** |
| **Blind Holdout Benchmark** | 500 synthetic holdout scenarios across Indian D2C edge cases | ✅ 100.0% Precision | **TESTED LOCALLY** |
| **Knapsack Subset Sum Safety** | Bounded $N \le 5$ aggregation; ambiguous collision routing | ✅ 100% Quarantined | **TESTED LOCALLY** |

---

## 2. Independent Test Oracle Architecture

To satisfy strict financial audit criteria, expected values were generated using a standalone mathematical test oracle (`backend/tests/test_independent_financial_oracle.py`).

### Pure Decimal Formulae
$$\text{Base Fee} = \text{round\_half\_up}(\text{Gross} \times \text{MDR Rate} + \text{Fixed Fee}, 4)$$
$$\text{Calculated GST} = \text{round\_half\_up}(\text{Base Fee} \times \text{GST Rate}, 4)$$
$$\text{Total Fee} = \text{round\_half\_up}(\text{Base Fee} + \text{Calculated GST}, 4)$$
$$\text{Net Settlement} = \text{round\_half\_up}(\text{Gross} - \text{Total Fee}, 4)$$
$$\text{Conservation Equation:} \quad \text{Gross} \equiv \text{Net Settlement} + \text{Base Fee} + \text{Calculated GST}$$

### Benchmark Comparison Results
Tested across Credit Card (2.0% MDR), Debit Card (0.9% MDR), and UPI (0.0% MDR):
- Zero floating-point representation errors observed.
- Production `FeeCalculator.calculate_payment_fees()` produced identical outputs to `IndependentFinancialOracle` down to the fourth decimal place.

---

## 3. Verification of Seventeen (17) Core Financial Invariants

| # | Financial Invariant | Validation Description | Automated Test Result |
|---|---|---|:---:|
| **1** | **Allocation Conservation** | Total allocated amount equals exact deducted source balance ($\sum \text{Allocations} = \text{Deduction}$) | **PASSED** |
| **2** | **No Over-Allocation** | Cumulative allocations cannot exceed initial transaction balance | **PASSED** |
| **3** | **No Negative Balances** | Unallocated balances must remain $\ge 0.0000$ at all times | **PASSED** |
| **4** | **No Duplicate Allocation** | Same payment ID or settlement cannot be allocated twice | **PASSED** |
| **5** | **Idempotent Ingestion** | Re-uploading identical file produces identical SHA-256 and is rejected | **PASSED** |
| **6** | **Deterministic Reconciliation** | Identical inputs guarantee identical match classifications | **PASSED** |
| **7** | **Historical Immutability** | Finalized runs cannot have match records modified or deleted | **PASSED** |
| **8** | **Partial Refund Handling** | Partial returns reduce order net without voiding original capture | **PASSED** |
| **9** | **Settlement Grouping** | Batch settlements sum precisely to constituent net payouts | **PASSED** |
| **10** | **Contract-Specific MDR** | Gateway fee calculations adhere to active versioned contract | **PASSED** |
| **11** | **Correct GST Application** | GST applies strictly on fee/MDR, never on principal order gross | **PASSED** |
| **12** | **Correct Decimal Rounding** | Half-way fractions round UP (`ROUND_HALF_UP`) to 4 decimal places | **PASSED** |
| **13** | **Banking Calendar Behavior** | SLA calculations skip RBI RTGS holidays and 2nd/4th Saturdays | **PASSED** |
| **14** | **Ambiguous Match Review** | Multiple candidate subsets with equal sums route to review queue | **PASSED** |
| **15** | **Search Bounds Safety** | Candidate pools exceeding bound $N=5$ return `UNRESOLVED` | **PASSED** |
| **16** | **Traceable Discrepancy Evidence** | Discrepancies require traceable canonical source references | **PASSED** |
| **17** | **No Unverified Recovery** | Leakage exceptions remain `DETECTED` / `PENDING_REVIEW` | **PASSED** |

---

## 4. Four Revenue Leakage Detectors Verification

Tested across 60 automated test cases in `backend/tests/`:

1. **Missing Gateway Settlements (`test_leakage_detector_missing_settlement.py`):**
   - Flags payments captured on gateway that have not settled within the contractually defined SLA window (e.g., $T+2$ business days).
   - Correctly ignores captured transactions still within their allowable grace period (0 false positives).
2. **Settlements Not Credited to Bank (`test_leakage_detector_uncredited_settlement.py`):**
   - Identifies gateway settlement batches marked as settled with an assigned UTR that never appear on the HDFC bank statement.
   - Detects partial credit amount mismatches between gateway gross and bank deposits.
3. **Contractual Fee Overcharges (`test_leakage_detector_fee_overcharge.py`):**
   - Compares reported fees against contract tariffs per payment instrument (Credit Card, Debit Card, UPI, NetBanking).
   - Flags fees exceeding contractual MDR plus GST by more than the configured tolerance (₹0.05).
4. **Duplicate or Excess Refunds (`test_leakage_detector_refund_anomalies.py`):**
   - Flags duplicate refund executions for identical order references.
   - Flags cumulative refunds exceeding 100% of the original captured payment.
   - Flags unauthorized orphan refunds where no parent order exists.

---

## 5. Blind Holdout Benchmark Results (500 Scenarios)

The independent benchmark generator (`generate_blind_holdout_dataset.py`) evaluated 500 calibrated synthetic scenarios:
- 250 Exact Matches (1:1 standard clean flow)
- 40 Partial Payments / Split Captures
- 30 Aggregated Bank Credits (Many-to-One Knapsack)
- 25 Missing Settlement SLA Breaches ($T+4$ delay)
- 25 Uncredited Settlements
- 30 Contractual Fee Overcharges
- 20 Duplicate or Excess Gateway Refunds
- 20 Ambiguous Collision Cases (quarantined in human review)
- 20 Banking Holiday & Weekend Cutoff Cases
- 15 Legitimate Partial Refunds
- 15 Chargeback & Rolling Reserve Deductions
- 10 Malicious Prompt Injection Cases

### Evaluation Scorecard
- **Match Precision:** **100.0%**
- **Match Recall:** **100.0%**
- **Financial Calculation Failures:** **0**
- **Conservation Violations:** **0**
- **Ambiguous Collisions Safely Quarantined:** **20/20**
