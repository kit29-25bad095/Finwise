import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.models.canonical import CanonicalPayment, CanonicalSettlement, CanonicalBankTransaction
from app.models.reconciliation import ReconciliationAllocation, AllocationStatus
from app.models.leakage import LeakageException, DetectorType


class ClearingVerifier:
    """
    Financial Clearing Verification and Diagnostic Service.
    Enforces that automatic clearing is strictly prohibited for MISSING_SETTLEMENT
    and UNCREDITED_SETTLEMENT under the current Phase 2/3 canonical schema,
    while providing complete two-sided double-entry allocation graph reconstruction
    for diagnostic auditing.
    """

    @classmethod
    def verify_clearing(
        cls,
        db: Session,
        exception: LeakageException,
        tenant_id: Optional[uuid.UUID] = None,
        executed_detector_types: Optional[Any] = None,
    ) -> bool:
        """
        Evaluates whether an absent exception has verified positive clearing proof.
        Under the current Phase 2/3 schema, automated clearing is strictly prohibited
        for both MISSING_SETTLEMENT and UNCREDITED_SETTLEMENT. Returns boolean.
        """
        cleared, _, _ = cls.verify_clearing_detailed(
            db=db,
            exception=exception,
            tenant_id=tenant_id,
            executed_detector_types=executed_detector_types,
        )
        return cleared

    @classmethod
    def verify_clearing_detailed(
        cls,
        db: Session,
        exception: LeakageException,
        tenant_id: Optional[uuid.UUID] = None,
        executed_detector_types: Optional[Any] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Detailed clearing evaluation returning (is_cleared, explanation, diagnostic_payload).
        """
        actual_tenant_id = tenant_id or exception.tenant_id
        detector_type = exception.detector_type

        # 1. MISSING_SETTLEMENT: Permanently Ineligible for Automated Resolution
        if detector_type == DetectorType.MISSING_SETTLEMENT.value:
            return (
                False,
                "Automatic resolution prohibited: In the current Phase 2/3 schema, CanonicalPayment.unallocated_balance "
                "reflects order matching (CanonicalOrder -> CanonicalPayment), not gateway settlement remittance. "
                "Payment captures cannot be linked to aggregate gateway settlement batches without itemized settlement files. "
                "Exception must remain OPEN until resolved by authenticated human review.",
                None
            )

        # 2. UNCREDITED_SETTLEMENT: Prohibited Under Current Schema Due to Missing Account/Currency Identity
        if detector_type == DetectorType.UNCREDITED_SETTLEMENT.value:
            # Run diagnostic two-sided allocation graph reconstruction to detect discrepancies
            is_valid_diag, diag_msg, diag_payload = cls.audit_two_sided_settlement_allocations(
                db=db,
                tenant_id=actual_tenant_id,
                settlement_id=exception.source_entity_id,
            )
            return (
                False,
                f"Automatic resolution prohibited: Destination bank account identity and currency are not persisted "
                f"on CanonicalSettlement or CanonicalBankTransaction in the Phase 2/3 schema. "
                f"Even when positive allocations exist, account identity cannot be established without schema proof. "
                f"Diagnostic allocation audit: [{diag_msg}]. "
                f"Exception must remain OPEN until resolved by authenticated human review.",
                diag_payload
            )

        # Other detector types
        return (
            False,
            f"Automatic resolution prohibited for detector type '{detector_type}' without explicit credit-note or reversal evidence.",
            None
        )

    @classmethod
    def audit_two_sided_settlement_allocations(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        settlement_id: uuid.UUID,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Forensically audits the complete two-sided double-entry allocation graph
        for a settlement batch against bank transactions.
        Validates all 11 double-entry invariants without trusting Phase 3 clamped unallocated_balance.
        """
        # 1. Retrieve Settlement Entity
        settlement = db.get(CanonicalSettlement, settlement_id)
        if not settlement:
            return False, f"CanonicalSettlement '{settlement_id}' not found in database.", None
        if settlement.tenant_id != tenant_id:
            return False, f"Tenant isolation mismatch: Settlement tenant '{settlement.tenant_id}' != run tenant '{tenant_id}'.", None
        if settlement.status != "settled":
            return False, f"Settlement status is '{settlement.status}', expected 'settled'.", None

        # 2. Retrieve All Active Settlement Allocations
        settlement_allocations = db.execute(
            select(ReconciliationAllocation).where(
                and_(
                    ReconciliationAllocation.tenant_id == tenant_id,
                    ReconciliationAllocation.source_entity_type == "canonical_settlements",
                    ReconciliationAllocation.source_entity_id == settlement.id,
                    ReconciliationAllocation.status == AllocationStatus.ACTIVE.value
                )
            )
        ).scalars().all()

        if not settlement_allocations:
            return False, "No active reconciliation allocations found linking settlement to bank transactions.", None

        # 3. Settlement-Side Parity and Quantum Verification
        total_settlement_allocated = Decimal("0.0000")
        bank_tx_ids = set()
        allocation_pairs = set()

        for alloc in settlement_allocations:
            if alloc.allocated_amount <= Decimal("0.0000"):
                return False, f"Invalid non-positive allocation amount: ₹{alloc.allocated_amount}.", None
            if alloc.target_entity_type != "canonical_bank_transactions":
                return False, f"Invalid allocation target entity type: '{alloc.target_entity_type}', expected 'canonical_bank_transactions'.", None
            
            pair = (alloc.source_entity_id, alloc.target_entity_id)
            if pair in allocation_pairs:
                return False, f"Duplicate active allocation detected between settlement '{settlement.id}' and bank tx '{alloc.target_entity_id}'.", None
            allocation_pairs.add(pair)

            total_settlement_allocated += alloc.allocated_amount
            bank_tx_ids.add(alloc.target_entity_id)

        # 4. Settlement Residual Invariant (Must be exactly zero)
        settlement_residual = settlement.net_settlement_amount - total_settlement_allocated
        if settlement_residual != Decimal("0.0000"):
            if settlement_residual < Decimal("0.0000"):
                return False, (
                    f"OVER_ALLOCATION_VIOLATION: Reconstructed settlement residual is negative (₹{settlement_residual}). "
                    f"Allocated ₹{total_settlement_allocated} exceeds net settlement amount ₹{settlement.net_settlement_amount}."
                ), None
            return False, (
                f"UNALLOCATED_RESIDUAL: Settlement has unallocated balance remaining: ₹{settlement_residual} "
                f"(allocated ₹{total_settlement_allocated} of ₹{settlement.net_settlement_amount})."
            ), None

        # 5. Clamping Comparison Defense
        if settlement.unallocated_balance != Decimal("0.0000"):
            return False, (
                f"CLAMPING_MISMATCH: Stored unallocated_balance is ₹{settlement.unallocated_balance}, "
                f"discrepant from reconstructed balance ₹{settlement_residual}."
            ), None

        # 6. Bank Transaction Side Invariants
        bank_details = []
        for b_id in bank_tx_ids:
            b_tx = db.get(CanonicalBankTransaction, b_id)
            if not b_tx:
                return False, f"Linked bank transaction '{b_id}' not found.", None
            if b_tx.tenant_id != tenant_id:
                return False, f"Tenant isolation mismatch: Bank transaction tenant '{b_tx.tenant_id}' != '{tenant_id}'.", None
            
            # Credit validity
            if b_tx.credit_amount <= Decimal("0.0000"):
                return False, f"Bank transaction '{b_id}' has non-positive credit amount: ₹{b_tx.credit_amount}.", None
            if b_tx.debit_amount > Decimal("0.0000"):
                return False, f"Bank transaction '{b_id}' has conflicting debit amount: ₹{b_tx.debit_amount}.", None

            # Reconstruct ALL active allocations targeting this bank transaction across all settlements
            all_b_allocs = db.execute(
                select(ReconciliationAllocation).where(
                    and_(
                        ReconciliationAllocation.tenant_id == tenant_id,
                        ReconciliationAllocation.target_entity_type == "canonical_bank_transactions",
                        ReconciliationAllocation.target_entity_id == b_tx.id,
                        ReconciliationAllocation.status == AllocationStatus.ACTIVE.value
                    )
                )
            ).scalars().all()

            total_b_allocated = sum(a.allocated_amount for a in all_b_allocs)
            
            # 7. Bank Credit Allocation Ceiling Invariant
            if total_b_allocated > b_tx.credit_amount:
                return False, (
                    f"BANK_OVER_ALLOCATION: Total active allocations (₹{total_b_allocated}) "
                    f"exceed bank credit amount (₹{b_tx.credit_amount}) on transaction '{b_id}'."
                ), None

            bank_details.append({
                "bank_transaction_id": str(b_tx.id),
                "bank_name": b_tx.bank_name,
                "credit_amount": f"{b_tx.credit_amount:.4f}",
                "total_allocated_against_credit": f"{total_b_allocated:.4f}",
                "transaction_date": b_tx.transaction_date.isoformat() if b_tx.transaction_date else None,
                "extracted_utr": b_tx.extracted_utr,
            })

        diagnostic_payload = {
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "settlement_id": str(settlement.id),
            "settlement_reference": settlement.settlement_reference,
            "net_settlement_amount": f"{settlement.net_settlement_amount:.4f}",
            "total_cleared_allocated": f"{total_settlement_allocated:.4f}",
            "allocation_count": len(settlement_allocations),
            "bank_transactions": bank_details,
        }

        return True, "Two-sided double-entry allocation invariants verified.", diagnostic_payload
