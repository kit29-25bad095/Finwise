# Finora Phase 7 — Pilot Operations & Financial Playbook

**Document ID:** `FINORA-DOC-020`  
**Classification:** Financial Operations & Standard Operating Procedures (SOP)  
**Status:** READY FOR PILOT USE  
**Author:** Principal FinTech Architect & Financial Systems Auditor  
**Audience:** Finance Controllers, Operations Managers, Accounting Auditors, Merchant Success Teams

---

## 1. Merchant Onboarding & Configuration

### 1.1 Tenant Registration & Gateway Linking
1. Navigate to [`http://localhost:3100/login`](http://localhost:3100/login) (or your production URL).
2. The Tenant Administrator creates the company workspace (e.g. `Alpha D2C Brands`).
3. Define the base operational currency: **INR (₹)**.
4. Set daily gateway cutoff times:
   - Razorpay default: `23:00` IST
   - Other gateways: `18:00` IST
5. Define the knapsack bounded search size: default $N=5$.
6. Define contractual fee tolerance: default $\epsilon = ₹0.05$.

### 1.2 Versioned Fee Contract Setup
Navigate to **Contract & Fee Analytics** (`/dashboard/contracts`):
1. Input active payment gateway (e.g. `RAZORPAY`).
2. Input active contract start date and version identifier.
3. Configure **Contractual GST Rate** (e.g. `0.1800` for 18%, `0.0500` for 5%, or `0.0000` for zero-rated).
4. Define instrument-specific tariff tiers:
   - **UPI:** 0.00% MDR, ₹0.00 fixed fee.
   - **Debit Cards (RuPay):** 0.00% MDR.
   - **Debit Cards (Mastercard / Visa):** 0.90% MDR.
   - **Credit Cards (Standard):** 1.85% to 2.00% MDR.
   - **Net Banking:** ₹15.00 fixed fee or 1.50% MDR.
5. Save contract. Contract is cryptographically versioned and immutably pinned to future reconciliation runs.

---

## 2. Daily Financial Reconciliation Workflow

```
[Step 1: Daily Ingestion]
        Export CSV statements from Shopify, Razorpay, and HDFC Bank.
        Upload via Data Ingestion portal.
        DDE formula sanitizer scrubs all inputs automatically.
        │
        ▼
[Step 2: Trigger Reconciliation Run]
        Navigate to /dashboard/reconciliation.
        Click "Trigger Run N+1".
        Multi-pass deterministic engine executes Passes 1 through 6.
        │
        ▼
[Step 3: Review Execution Results]
        Inspect matched volume vs. unmatched discrepancies.
        Review accuracy percentage on Executive Overview.
        │
        ▼
[Step 4: Resolve Human Review Queue]
        Navigate to /dashboard/exceptions.
        Evaluate ambiguous collisions and combinatorial aggregations.
        Finance Managers execute APPROVE, REJECT, or MANUAL_ALLOCATE with mandatory notes.
        │
        ▼
[Step 5: Monitor Revenue Leakage]
        Navigate to /dashboard/leakage-detection.
        Review 4 core detector findings (Missing settlements, Fee overcharges, etc.).
        Inspect AI root-cause dossiers and export dispute claim files.
```

---

## 3. Human Review Standard Operating Procedures (SOP)

When the reconciliation engine encounters multiple equal-amount candidates or bounded subset combinations, it quarantines the records in the **Review Queue** (`/dashboard/exceptions`).

### 3.1 Resolving Combinatorial Collisions (`AMBIGUOUS_AGGREGATION_COLLISION`)
- **Condition:** Multiple distinct combinations of settlement batches equal the bank credit amount within tolerance.
- **Action Required:**
  1. Inspect the candidate settlements displayed in the Review Queue.
  2. Cross-reference the settlement dates with the bank nodal account statement.
  3. Select the verified settlement IDs and click **Manual Allocate**.
  4. Enter a mandatory audit rationale (e.g., *"Confirmed settlement batch SETL-8822 cleared via UTR ending in 9912 per HDFC nodal statement confirmation"*).
  5. The action is permanently recorded in the immutable audit ledger.

### 3.2 Resolving Fee Overcharges
- **Condition:** Gateway deducted MDR + GST exceeding versioned contract tariff by $> ₹0.05$.
- **Action Required:**
  1. Open the Finding in **Revenue Leakage Monitoring**.
  2. Inspect the mathematical breakdown: `Reported Fee` vs. `Contractual Fee` = `Overcharge Delta`.
  3. Generate the dispute dossier.
  4. Submit the dispute to the payment gateway partner manager for credit note issuance.

---

## 4. Incident Response & Data Retention

### 4.1 Ingestion Error Handling
- If a CSV contains malformed dates or missing columns, the engine isolates bad rows in `source_row_errors` and continues processing valid rows.
- The Finance Manager can download the rejected row errors CSV, correct the rows, and re-upload. The engine matches existing records idempotently.

### 4.2 Immutable Audit Trail & Retention Policy
- Financial records, allocations, and review logs are **never hard-deleted**.
- In the event of tenant deactivation, records are soft-deactivated (`Tenant.is_active = False`) and retained in compliance with Indian corporate and tax laws (minimum 8 years under the Companies Act and GST regulations).
