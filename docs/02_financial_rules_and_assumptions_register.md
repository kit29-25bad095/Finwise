# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine
# Document 02: Financial Rules, Banking Domain Logic & Assumptions Register (Configurable Architecture)

**Project Name:** Finora  
**Document Reference:** FINORA-FIN-RULES-V3  
**Classification:** Financial Domain Specification  
**Author:** Senior Financial Systems Engineer, FinTech Security Architect  
**Status:** Under Formal Architectural Review (Phase 0 - Revision 3)  
**Date:** November 2026  

---

## 1. Executive Summary & Design Principles

Financial reconciliation engines fail when real-world banking rules, cutoffs, and contract tariffs are hardcoded as static global constants. 

Finora strictly enforces the principle of **Configurable Financial Determinism**:
- All settlement schedules, holiday calendars, cutoffs, and settlement delays are **fully configurable by provider, merchant bank, and contract**.
- All fees (MDR, GST, refund fees, chargeback deductions, reserves) are **derived dynamically from versioned merchant contracts**, never from hardcoded universal rates.
- Financial tolerances and rounding models are **explicitly defined, configurable per tenant, and traceable at every stage of the calculation pipeline**.
- The AI layer is **100% provider- and model-agnostic**, interacting through an abstract schema-enforced gateway.

---

## 2. Detailed Corrections across the Core Areas

---

### AREA 1: Configurable Banking Calendars, Cutoffs, and Settlement Schedules

#### 1.1 Architectural Correction
Do not assume one universal Indian banking calendar or a fixed 23:00 IST cutoff.
- **Provider-Specific Settlement Cutoffs:** Different gateways execute batch settlements on distinct schedules:
  - Razorpay: Default 23:00 IST daily batch cutoff (or merchant-specific custom batch e.g. 18:00 IST).
  - Cashfree: Intraday settlement batches (e.g. 09:00, 13:00, 19:00 IST) or on-demand cycles.
  - PayU / Stripe India: Midnight 00:00 or 19:00 IST cutoffs.
- **Branch- & State-Specific Banking Calendars:** Bank accounts registered in Mumbai observe Maharashtra state holidays, while accounts in Bengaluru observe Karnataka holidays under the Negotiable Instruments Act Section 25.
- **Contractual Turnaround Schedule ($T_{\text{contract}}$):** Fully configurable per payment method and gateway contract ($T+0$ instant, $T+1$ express, $T+2$ standard, $T+3$ extended).

#### 1.2 Technical Implementation Model
```
[Merchant Tenant Settings]
        ├── Primary Clearing Hub: [RBI Mumbai RTGS / State Branch Override]
        ├── Custom Merchant Holiday Exceptions: [List of Dates]
        └── Provider Gateway Configurations:
             ├── Razorpay: Cutoff Time = 23:00 IST, Settlement Window = T+2
             └── Cashfree: Cutoff Time = 18:00 IST, Settlement Window = T+1
```
The due-date calculation function is parameterized:
$$\text{DueDate}(P_i) = \text{CalculateSettlementDueDate}(P_i.\text{captured\_at}, \mathcal{C}_{\text{provider\_cutoff}}, \mathcal{T}_{\text{calendar\_profile}}, T_{\text{contractual\_days}})$$

---

### AREA 2: Contract-Driven Refund Fee Policies & Surcharges

#### 2.1 Architectural Correction
Do not apply universal assumptions about whether refund fees or taxes are refunded or charged.
All refund fee liabilities are evaluated dynamically against the merchant's active `FeeContract`:
- **Standard (Normal) Refund Policy:** 
  - `retain_mdr`: `true` (Gateway keeps original MDR; net payout debited by gross refund amount).
  - `refund_service_fee`: `false` (Gateway does not refund original MDR or GST).
- **Instant Refund Surcharge Schedule:**
  - Evaluated against contract version:
    - Fixed fee per instant refund: $F_{\text{instant}}$ (e.g. ₹5.00, ₹10.00, or ₹0.00).
    - Percentage fee: $R_{\text{instant}}$ (e.g. 0.20%, 0.25%, or 0.00%).
    - Payer model: `MERCHANT_ABSORBED` vs `CUSTOMER_DEDUCTED`.
- **Contractual Refund Fee Credit:** If an enterprise contract explicitly stipulates fee credit upon refund, the engine applies the contractual credit formula rather than a static non-refundable rule.

---

### AREA 3: 100% Contract-Specific MDR, GST, Reserves & Adjustment Modeling

#### 3.1 Architectural Correction
No fee, tax rate, chargeback tariff, or reserve hold is hardcoded. All values are queried from the active `FeeScheduleVersion` matching the transaction timestamp.

#### 3.2 Dynamic Contract Hierarchy
$$\text{FeeContract} \longrightarrow \text{FeeScheduleVersion} \longrightarrow \text{PaymentMethodTier} \longrightarrow \text{VolumeTier}$$

Parameters configurable per contract tier:
- `instrument_type`: `UPI_P2M`, `DOMESTIC_DEBIT_TIER1` ($\le ₹2,000$), `DOMESTIC_DEBIT_TIER2` ($> ₹2,000$), `DOMESTIC_CREDIT_STANDARD`, `DOMESTIC_CREDIT_CORPORATE`, `NETBANKING`, `INTERNATIONAL`.
- `percentage_rate`: e.g. $0.000000$ to $0.035000$.
- `fixed_fee_per_txn`: e.g. ₹0.00 to ₹25.00.
- `min_fee_cap` / `max_fee_cap`.
- `gst_rate`: Dynamic (default: $0.180000$, configurable if tax exemption or SEZ status applies).
- `chargeback_dispute_fee`: Configurable per contract (e.g. ₹500.00, ₹650.00, or ₹1,000.00 + GST).
- `rolling_reserve_percentage`: e.g. $0.00\%$ to $10.00\%$.
- `rolling_reserve_hold_days`: e.g. 90 to 180 days.

---

### AREA 4: Configurable Financial Tolerance & Stage-by-Stage Rounding Architecture

#### 4.1 Architectural Correction
Tolerance $\epsilon$ is **not a hardcoded ₹0.05 constant**. It is a **tenant-configurable parameter** (`tenant.fee_overcharge_tolerance`, default ₹0.05, range ₹0.00 to ₹1.00).

#### 4.2 Calculation Stages & Rounding Rules
To prevent compounding rounding drift, rounding and tolerances are applied at strictly defined boundaries:

```
[Stage 1: Nominal Capture Amount]
  - Stored: Exact NUMERIC(18, 4) from source CSV.
  - Rounding: None.

[Stage 2: Contractual MDR Calculation]
  - Formula: unrounded_mdr = capture_amount * percentage_rate
  - Rounding: ROUND_HALF_UP to 4 decimal places for internal ledgering.

[Stage 3: Base Fee Aggregation]
  - Formula: base_fee = unrounded_mdr + fixed_fee_per_txn
  - Clamping: max(min_fee_cap, min(max_fee_cap, base_fee)) if caps defined.

[Stage 4: Tax (GST) Calculation]
  - Formula: calculated_tax = base_fee * contract_gst_rate
  - Rounding: ROUND_HALF_UP to 4 decimal places.

[Stage 5: Expected Gateway Total Fee]
  - Formula: expected_total_fee = base_fee + calculated_tax
  - Nominal Invoice Representation: ROUND_HALF_UP to 2 decimal places for display/invoicing.

[Stage 6: Overcharge Delta & Tolerance Evaluation]
  - Delta: delta = (reported_fee + reported_tax) - expected_total_fee
  - Evaluation:
      IF delta > tenant.fee_overcharge_tolerance:
          RAISE FeeOverchargeException(discrepancy = delta)
      ELSE IF delta > 0.0000:
          LOG RoundingDrift(delta = delta)  [No Exception Raised]
```

---

### AREA 5: Bounded Knapsack Allocation & Never-Force-Match Guarantee

#### 5.1 Architectural Correction
The search bound $N \le 5$ (configurable: `tenant.max_settlement_aggregation_bound`) is strictly an algorithmic optimization limit to prevent combinatorial explosion ($O(2^M)$).

**CRITICAL FINANCIAL MANDATE:**
- The optimization bound must **NEVER force a match or guess**.
- If a valid subset sum cannot be identified within the configured search bound $N$, or if multiple competing subsets produce identical sums:
  - The engine **HALTS auto-allocation**.
  - Creates zero speculative allocations.
  - Generates an exception with status `UNRESOLVED_SUBSET_BOUND_EXCEEDED` or `AMBIGUOUS_AGGREGATION_COLLISION`.
  - Routes the transaction directly to **Pass 6 (Human Review Queue)** with full candidate details.

---

### AREA 6: Fully Provider-Independent AI Investigation Interface

#### 6.1 Architectural Correction
Zero AI providers, SDKs, or models are hardcoded.

#### 6.2 Abstract Interface Specification
```python
from abc import ABC, abstractmethod
from typing import Dict, Any
from pydantic import BaseModel

class AIInvestigationConfig(BaseModel):
    provider_name: str          # e.g. "gemini", "openai", "anthropic", "mock"
    model_name: str             # e.g. "gemini-1.5-pro", "gpt-4o", "claude-3-5-sonnet"
    api_key_vault_ref: str      # Secure secret vault key reference
    temperature: float = 0.1
    max_tokens: int = 2048
    timeout_seconds: int = 30

class AIInvestigationProvider(ABC):
    @abstractmethod
    async def investigate_discrepancy(
        self, 
        bundle: Dict[str, Any], 
        config: AIInvestigationConfig
    ) -> Dict[str, Any]:
        """
        Executes structured root-cause analysis against evidence bundle.
        Enforces strict JSON schema validation and citation verification.
        """
        pass
```

The system dynamically resolves the provider at runtime via `AIInvestigationProviderFactory`.

---
*(End of Document 02 — Financial Rules and Assumptions Register V3)*
