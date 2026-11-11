# Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine
# Document 03: Updated Database Schema & Entity-Relationship Architecture

**Project Name:** Finora  
**Document Reference:** FINORA-DB-ERD-V2  
**Classification:** Database Architecture Specification  
**Author:** PostgreSQL Database Architect, Principal Software Architect  
**Status:** Under Formal Architectural Review (Phase 0)  
**Date:** November 2026  

---

## 1. Executive Summary & Design Philosophy

The database design of Finora enforces five non-negotiable architectural mandates:

1. **PostgreSQL as Authoritative Source of Truth:** Redis is used solely for worker coordination and distributed locks. Every financial state, allocation, and audit log is persisted in PostgreSQL with strict relational integrity.
2. **Arbitrary Precision for Financial Balances:** Zero floating-point columns. All monetary balances, allocations, fees, and rates use `NUMERIC(18, 4)` (or `NUMERIC(8, 6)` for fractional percentage rates).
3. **Tenant Boundary Enforcement:** Every table contains an indexed `tenant_id` foreign key. Row-Level Security (RLS) policies and composite unique constraints enforce absolute tenant isolation.
4. **Immutable Append-Only Audit & Allocation Ledger:** Allocations, run deltas, and audit entries are immutable. State changes are recorded as new rows or version transitions (`ACTIVE` vs `SUPERSEDED`).
5. **Full Provenance & Lineage:** Every normalized financial record references `upload_id` and `source_row_index` to trace directly back to the physical source CSV.

---

## 2. Updated Entity-Relationship Diagram (Mermaid)

```mermaid
erDiagram
    TENANTS ||--o{ USERS : employs
    TENANTS ||--o{ TENANT_MEMBERSHIPS : binds
    USERS ||--o{ TENANT_MEMBERSHIPS : belongs_to
    
    TENANTS ||--o{ UPLOADS : ingests
    UPLOADS ||--o{ SOURCE_ROW_ERRORS : records_errors
    
    TENANTS ||--o{ ORDERS : owns
    UPLOADS ||--o{ ORDERS : sources
    ORDERS ||--o{ PAYMENT_CAPTURES : receives
    UPLOADS ||--o{ PAYMENT_CAPTURES : sources
    
    PAYMENT_CAPTURES ||--o{ REFUND_EVENTS : incurs
    UPLOADS ||--o{ REFUND_EVENTS : sources
    
    TENANTS ||--o{ SETTLEMENT_BATCHES : receives
    UPLOADS ||--o{ SETTLEMENT_BATCHES : sources
    SETTLEMENT_BATCHES ||--o{ SETTLEMENT_ITEMS : contains
    PAYMENT_CAPTURES ||--o{ SETTLEMENT_ITEMS : links_capture
    REFUND_EVENTS ||--o{ SETTLEMENT_ITEMS : links_refund
    
    TENANTS ||--o{ CANONICAL_ADJUSTMENTS : incurs
    UPLOADS ||--o{ CANONICAL_ADJUSTMENTS : sources
    SETTLEMENT_BATCHES ||--o{ CANONICAL_ADJUSTMENTS : deducts
    
    TENANTS ||--o{ BANK_TRANSACTIONS : owns
    UPLOADS ||--o{ BANK_TRANSACTIONS : sources
    
    TENANTS ||--o{ FEE_CONTRACTS : negotiates
    FEE_CONTRACTS ||--o{ FEE_SCHEDULE_VERSIONS : versions
    
    TENANTS ||--o{ RECONCILIATION_RUNS : executes
    RECONCILIATION_RUNS ||--o{ ALLOCATIONS : produces
    RECONCILIATION_RUNS ||--o{ RUN_DELTAS : records_diff
    
    SETTLEMENT_BATCHES ||--o{ ALLOCATIONS : target_settlement
    BANK_TRANSACTIONS ||--o{ ALLOCATIONS : source_bank
    
    RECONCILIATION_RUNS ||--o{ EXCEPTIONS : surfaces
    EXCEPTIONS ||--o{ EVIDENCE_ITEMS : backed_by
    EXCEPTIONS ||--o{ AI_INVESTIGATIONS : investigated_by
    EXCEPTIONS ||--o{ DISPUTES : claims
    
    TENANTS ||--o{ AUDIT_LOGS : audits
    USERS ||--o{ AUDIT_LOGS : actions

    TENANTS {
        uuid id PK
        string name
        string slug
        string default_currency
        string settlement_cutoff_time
        timestamp created_at
    }

    USERS {
        uuid id PK
        string email
        string hashed_password
        string full_name
        boolean is_active
        timestamp created_at
    }

    TENANT_MEMBERSHIPS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string role
        timestamp created_at
    }

    UPLOADS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string source_type
        string filename
        string file_hash_sha256
        int row_count
        string status
        timestamp uploaded_at
    }

    ORDERS {
        uuid id PK
        uuid tenant_id FK
        uuid upload_id FK
        int source_row_index
        string order_reference
        numeric gross_amount
        numeric net_tax_amount
        string currency
        string fulfillment_status
        string financial_status
        timestamp order_timestamp
    }

    PAYMENT_CAPTURES {
        uuid id PK
        uuid tenant_id FK
        uuid order_id FK
        uuid upload_id FK
        int source_row_index
        string gateway_name
        string gateway_payment_id
        string gateway_order_id
        string payment_method
        numeric captured_amount
        numeric reported_fee
        numeric reported_tax
        string currency
        string status
        timestamp captured_at
        numeric unallocated_balance
    }

    REFUND_EVENTS {
        uuid id PK
        uuid tenant_id FK
        uuid payment_capture_id FK
        uuid upload_id FK
        int source_row_index
        string gateway_refund_id
        string refund_mode
        numeric refund_amount
        numeric surcharge_amount
        string status
        timestamp initiated_at
        timestamp processed_at
    }

    SETTLEMENT_BATCHES {
        uuid id PK
        uuid tenant_id FK
        uuid upload_id FK
        int source_row_index
        string gateway_name
        string settlement_reference
        string utr_number
        numeric gross_amount
        numeric total_fee
        numeric total_tax
        numeric total_refunds
        numeric total_adjustments
        numeric net_settlement_amount
        numeric unallocated_balance
        string status
        timestamp settled_at
    }

    CANONICAL_ADJUSTMENTS {
        uuid id PK
        uuid tenant_id FK
        uuid settlement_batch_id FK
        uuid upload_id FK
        int source_row_index
        string adjustment_type
        string reference_id
        numeric amount
        string description
        timestamp posted_at
    }

    BANK_TRANSACTIONS {
        uuid id PK
        uuid tenant_id FK
        uuid upload_id FK
        int source_row_index
        string bank_reference
        string extracted_utr
        date transaction_date
        date value_date
        numeric credit_amount
        numeric debit_amount
        string raw_narration
        numeric unallocated_balance
    }

    ALLOCATIONS {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        uuid settlement_batch_id FK
        uuid bank_transaction_id FK
        numeric allocated_amount
        string match_pass
        numeric match_confidence_score
        string allocation_status
        timestamp created_at
    }

    EXCEPTIONS {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        string exception_type
        string severity
        numeric discrepancy_amount
        numeric potentially_recoverable_amount
        numeric verified_recoverable_amount
        numeric claimed_amount
        numeric recovered_amount
        string lifecycle_status
        uuid primary_entity_id
        string primary_entity_type
        timestamp created_at
    }

    EVIDENCE_ITEMS {
        uuid id PK
        uuid tenant_id FK
        uuid exception_id FK
        string evidence_type
        uuid source_entity_id
        string source_entity_type
        jsonb metadata
        timestamp linked_at
    }

    AI_INVESTIGATIONS {
        uuid id PK
        uuid tenant_id FK
        uuid exception_id FK
        string provider
        string model
        string qualitative_confidence
        jsonb hypotheses
        jsonb missing_evidence
        text plain_english_summary
        text dispute_draft
        timestamp conducted_at
    }

    DISPUTES {
        uuid id PK
        uuid tenant_id FK
        uuid exception_id FK
        uuid approved_by_user_id FK
        numeric claimed_amount
        string dispute_reference
        string status
        timestamp approved_at
        timestamp exported_at
    }

    AUDIT_LOGS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string action
        string target_entity_type
        uuid target_entity_id
        jsonb previous_state
        jsonb new_state
        string user_rationale
        string ip_address
        timestamp performed_at
    }
```

---

## 3. Detailed Entity Definitions & Technical Design Choices

### 3.1 Resolving Prior Missing Entities
In this revised schema, we have explicitly introduced four essential entities that were missing from the initial design:
1. **`CANONICAL_ADJUSTMENTS`:** Captures chargebacks, dispute fees (e.g. ₹500 + GST), reserve withholdings, and gateway billing corrections. This bridges the gap between gross captures and net bank credits.
2. **`SETTLEMENT_ITEMS`:** Bridges individual captures and refunds to their parent settlement batch, tracking line-item level settlement fulfillment.
3. **`SOURCE_ROW_ERRORS`:** Quarantines malformed or unmappable CSV rows during ingestion without halting the pipeline, recording exact line numbers and parse failures.
4. **`RUN_DELTAS`:** Stores the exact mathematical diff between consecutive reconciliation runs (newly matched, broken matches, new exceptions).

### 3.2 Allocation Invariant & Concurrency Control
```sql
-- Enforcing non-negative unallocated balance at database level
ALTER TABLE bank_transactions 
ADD CONSTRAINT chk_bank_tx_unallocated_non_negative 
CHECK (unallocated_balance >= 0);

ALTER TABLE settlement_batches 
ADD CONSTRAINT chk_settlement_unallocated_non_negative 
CHECK (unallocated_balance >= 0);

-- Composite Unique Index to prevent duplicate active allocations
CREATE UNIQUE INDEX uq_active_allocations 
ON allocations (tenant_id, settlement_batch_id, bank_transaction_id) 
WHERE allocation_status = 'ACTIVE';
```

During execution of reconciliation passes, affected rows in `settlement_batches` and `bank_transactions` are locked using:
```sql
SELECT id, unallocated_balance 
FROM bank_transactions 
WHERE id = :bank_tx_id AND tenant_id = :tenant_id 
FOR UPDATE;
```
This guarantees that concurrent background workers or reruns can never execute simultaneous competing allocations.

---

## 4. Tenant Isolation Strategy

### 4.1 Row-Level Security (RLS) Architecture
Every query executed by the application sets the PostgreSQL session configuration variable:
```sql
SET LOCAL app.current_tenant_id = 'c4b8e21a-...';
```
PostgreSQL Row-Level Security policy on all financial tables:
```sql
CREATE POLICY tenant_isolation_policy ON orders
FOR ALL
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
```
Even in the event of an application-level bug or missed `WHERE` clause, the database kernel strictly forbids cross-tenant data leakage.

---
*(End of Document 03 — Updated Database Schema & ER Architecture)*
