# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine
# Document 05: Mathematical Specifications for the Four Core Leakage Detectors (Configurable Calendars & Contracts)

**Project Name:** Finora  
**Document Reference:** FINORA-DETECTORS-V3  
**Classification:** Financial Algorithmic Specification  
**Author:** Senior Financial Systems Engineer, FinTech Security Architect  
**Status:** Under Formal Architectural Review (Phase 0 - Revision 3)  
**Date:** November 2026  

---

## 1. Executive Summary

Finora's leakage detection engine consists of four decoupled, testable mathematical detector modules. Every detector operates as a pure deterministic function:
$$\mathcal{D}_k: (\mathcal{L}_{\text{canonical}}, \mathcal{C}_{\text{contract}}, \mathcal{T}_{\text{calendar\_config}}, \Theta_{\text{tolerance\_config}}) \longrightarrow \text{List}[\text{LeakageException}]$$

Detectors do not use heuristics or AI inferences to flag leakages. All checks rely on deterministic mathematical deltas substantiated by explicit database evidence references.

---

## 2. DETECTOR 1: Missing Gateway Settlement

### 2.1 Trigger Conditions
A payment capture $P_i$ satisfies:
1. $P_i.\text{status} = \text{'captured'}$
2. $P_i.\text{captured\_amount} > 0$
3. $P_i.\text{unallocated\_balance} > 0$
4. $\text{CurrentDate} > \text{SettlementDueDate}(P_i, \text{Contract}, \text{Calendar}) + \text{GracePeriod}$

### 2.2 Mathematical Formulas
$$\text{CutoffTime} = \text{GetProviderCutoff}(P_i.\text{gateway\_name}, \text{Contract}) \quad \text{[e.g. 23:00 IST, 18:00 IST]}$$

$$\text{Day}_0 = \begin{cases} 
\text{Date}(P_i.\text{captured\_at}), & \text{if Time}(P_i.\text{captured\_at}) < \text{CutoffTime} \\
\text{NextBusinessDay}(\text{Date}(P_i.\text{captured\_at}), \mathcal{T}_{\text{merchant\_bank\_calendar}}), & \text{otherwise}
\end{cases}$$

$$\text{SettlementDueDate}(P_i) = \text{AddBusinessDays}(\text{Day}_0, T_{\text{contractual\_delay}}, \mathcal{T}_{\text{merchant\_bank\_calendar}})$$

$$\Delta_{\text{Settlement}}(P_i) = P_i.\text{captured\_amount} - \sum_{s \in \text{SettlementItems}(P_i)} s.\text{settled\_gross\_amount}$$

$$\text{PotentialRecovery}(P_i) = \Delta_{\text{Settlement}}(P_i) - \text{ContractualMDR}(P_i) - \text{ContractualGST}(P_i)$$

### 2.3 Calendar & Cutoff Configuration Parameters
- $\mathcal{T}_{\text{merchant\_bank\_calendar}}$: State-specific banking holidays + RBI RTGS clearing rules.
- $T_{\text{contractual\_delay}}$: Dynamically queried from active contract version for $P_i.\text{payment\_method}$ (e.g. $T+1, T+2$).

---

## 3. DETECTOR 2: Settlement Not Credited to Bank

### 3.1 Trigger Conditions
A settlement batch $S_j$ satisfies:
1. $S_j.\text{status} = \text{'settled'}$ (Gateway reports transfer complete with assigned UTR)
2. $S_j.\text{net\_settlement\_amount} > 0$
3. $S_j.\text{unallocated\_balance} > 0$
4. $\text{CurrentDate} > \text{ExpectedBankCreditDate}(S_j) + \text{GracePeriod}$

### 3.2 Mathematical Formulas
$$\text{ExpectedBankCreditDate}(S_j) = \text{AddBusinessDays}(\text{Date}(S_j.\text{settled\_at}), \text{Contract}.\text{bank\_credit\_clearance\_days}, \mathcal{T}_{\text{bank\_calendar}})$$

$$\Delta_{\text{Bank}}(S_j) = S_j.\text{net\_settlement\_amount} - \sum_{a \in \text{Allocations}(S_j)} a.\text{allocated\_amount}$$

### 3.3 Confidence Classification & Gap Defense
- **HIGH CONFIDENCE:** Bank statement upload has zero date gaps spanning $[\text{settled\_at}, \text{ExpectedCreditDate} + 3\text{ days}]$ and UTR is confirmed missing.
- **EVIDENCE PENDING (Statement Gap):** Incomplete bank statements detected. Financial claim suppressed; upload prompt generated.

---

## 4. DETECTOR 3: Contractual Fee Overcharge

### 4.1 Trigger Conditions
For captured payment $P_i$, reported gateway deduction deviates from the active contract schedule by more than the configurable tolerance $\epsilon$:
$$\Delta_{\text{FeeOvercharge}}(P_i) > \epsilon_{\text{tenant\_tolerance}}$$

### 4.2 Stage-by-Stage Mathematical Formulation
1. **Contractual MDR Calculation:**
   $$\text{MDR}(P_i) = \text{Round}\left(P_i.\text{captured\_amount} \times R_{\text{contract\_method\_rate}}, 4\right)$$
2. **Base Fee with Fixed Charges & Clamping:**
   $$\text{BaseFee}(P_i) = \max\left(\text{MinCap}, \min\left(\text{MaxCap}, \text{MDR}(P_i) + F_{\text{contract\_fixed\_fee}}\right)\right)$$
3. **GST Calculation:**
   $$\text{GST}(P_i) = \text{Round}\left(\text{BaseFee}(P_i) \times \text{Contract}.\text{gst\_rate}, 4\right)$$
4. **Contractual Expected Total Fee:**
   $$\text{ExpectedTotalFee}(P_i) = \text{BaseFee}(P_i) + \text{GST}(P_i)$$
5. **Overcharge Evaluation:**
   $$\Delta_{\text{FeeOvercharge}}(P_i) = (P_i.\text{reported\_fee} + P_i.\text{reported\_tax}) - \text{ExpectedTotalFee}(P_i)$$
   - If $\Delta_{\text{FeeOvercharge}}(P_i) > \epsilon_{\text{tenant\_tolerance}}$: **Raise Exception** (Discrepancy Amount = $\Delta_{\text{FeeOvercharge}}$).
   - If $0 < \Delta_{\text{FeeOvercharge}}(P_i) \le \epsilon_{\text{tenant\_tolerance}}$: **Record Rounding Drift** (No Exception).

---

## 5. DETECTOR 4: Duplicate or Unauthorized Refund

### 5.1 Trigger Conditions
Identifies any of four refund anomalies:
1. **Duplicate Gateway Refund Reference:** Duplicate `gateway_refund_id` imported across batches.
2. **Cumulative Refund Exceeding Capture:**
   $$\sum_{k} R_{i,k}.\text{refund\_amount} > P_i.\text{captured\_amount}$$
3. **Orphan Refund:** Gateway debits a refund with no associated captured payment.
4. **Unauthorized Return-less Refund:** Gateway records successful refund on an order whose Shopify status is `fulfilled` with zero returns or cancellations requested.

### 5.2 Mathematical Formulas
$$\Delta_{\text{ExcessRefund}}(P_i) = \max\left(0, \sum_{k} R_{i,k}.\text{refund\_amount} - P_i.\text{captured\_amount}\right)$$

---
*(End of Document 05 — Four Leakage Detector Specifications V3)*
