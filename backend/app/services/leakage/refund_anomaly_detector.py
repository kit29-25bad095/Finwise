import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.models.canonical import CanonicalRefund, CanonicalPayment, CanonicalOrder
from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity
from app.services.leakage.base_detector import BaseLeakageDetector, LeakageFinding, EvidenceItemDraft


class RefundAnomalyDetector(BaseLeakageDetector):
    """
    DETECTOR 4: Duplicate and Unauthorized Refunds
    Detects duplicate refund debits, cumulative refunds exceeding original captures,
    orphan/unauthorized refunds, and reference collisions.
    """

    def detect(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[LeakageFinding]:
        # 1. Query all canonical refunds for tenant
        refunds = db.execute(
            select(CanonicalRefund).where(CanonicalRefund.tenant_id == tenant_id)
        ).scalars().all()

        # Query all payments for tenant
        payments = db.execute(
            select(CanonicalPayment).where(CanonicalPayment.tenant_id == tenant_id)
        ).scalars().all()
        payments_by_id = {p.id: p for p in payments}
        payments_by_gateway_id = {p.gateway_payment_id: p for p in payments if p.gateway_payment_id}

        # Query orders for return-less refund check
        orders = db.execute(
            select(CanonicalOrder).where(CanonicalOrder.tenant_id == tenant_id)
        ).scalars().all()
        orders_by_ref = {o.order_reference: o for o in orders if o.order_reference}

        findings: List[LeakageFinding] = []

        # -------------------------------------------------------------------
        # CHECK 1: Duplicate Refund References & Collision
        # -------------------------------------------------------------------
        refunds_by_ref: Dict[str, List[CanonicalRefund]] = defaultdict(list)
        for r in refunds:
            if r.gateway_refund_id:
                refunds_by_ref[r.gateway_refund_id.strip()].append(r)

        processed_collision_refs = set()
        for ref_id, ref_list in refunds_by_ref.items():
            if len(ref_list) > 1:
                processed_collision_refs.add(ref_id)
                # Check statuses: distinguish legitimate retry (e.g. failed attempt) from duplicate execution
                successful_executions = [
                    r for r in ref_list
                    if r.status and r.status.lower() in ("processed", "settled", "success")
                ]

                if len(successful_executions) > 1:
                    # True Duplicate Financial Debit
                    duplicate_total = sum(r.refund_amount for r in successful_executions[1:])
                    primary_r = successful_executions[0]
                    findings.append(
                        LeakageFinding(
                            detector_type=DetectorType.REFUND_ANOMALY,
                            exception_type=LeakageExceptionType.DUPLICATE_REFUND,
                            severity=ExceptionSeverity.CRITICAL if duplicate_total >= Decimal("5000.0000") else ExceptionSeverity.HIGH,
                            severity_reason=f"Gateway executed {len(successful_executions)} successful debits for the identical refund ID '{ref_id}'.",
                            source_entity_type="canonical_refunds",
                            source_entity_id=primary_r.id,
                            source_reference=ref_id,
                            order_reference=primary_r.order_reference,
                            gateway_name="RAZORPAY",
                            expected_amount=primary_r.refund_amount,
                            actual_amount=sum(r.refund_amount for r in successful_executions),
                            leakage_amount=duplicate_total,
                            recoverable_amount=duplicate_total,
                            currency=primary_r.currency,
                            calculation_breakdown={
                                "gateway_refund_id": ref_id,
                                "total_executions_count": len(successful_executions),
                                "primary_refund_amount": str(primary_r.refund_amount),
                                "duplicate_debit_amount": str(duplicate_total),
                                "execution_ids": [str(r.id) for r in successful_executions],
                            },
                            explanation=(
                                f"Duplicate refund execution detected for gateway refund reference '{ref_id}'. "
                                f"{len(successful_executions)} separate processed entries recorded, totaling "
                                f"₹{sum(r.refund_amount for r in successful_executions)} instead of ₹{primary_r.refund_amount}. "
                                f"Duplicate financial leakage: ₹{duplicate_total}."
                            ),
                            evidence_items=[
                                EvidenceItemDraft(
                                    evidence_type="REFUND_EVENT",
                                    entity_type="canonical_refunds",
                                    entity_id=r.id,
                                    source_batch_id=r.batch_id,
                                    source_row_index=r.source_row_index,
                                    details={
                                        "gateway_refund_id": r.gateway_refund_id,
                                        "gateway_payment_id": r.gateway_payment_id,
                                        "refund_amount": str(r.refund_amount),
                                        "status": r.status,
                                        "processed_at": r.processed_at.isoformat() if r.processed_at else None,
                                    }
                                )
                                for r in successful_executions
                            ]
                        )
                    )
                else:
                    # Amounts differ or different payment target -> Collision
                    first_r = ref_list[0]
                    amounts = {r.refund_amount for r in ref_list}
                    if len(amounts) > 1:
                        findings.append(
                            LeakageFinding(
                                detector_type=DetectorType.REFUND_ANOMALY,
                                exception_type=LeakageExceptionType.REFUND_REFERENCE_COLLISION,
                                severity=ExceptionSeverity.MEDIUM,
                                severity_reason=f"Reference collision: multiple refund entries with ID '{ref_id}' report differing amounts.",
                                source_entity_type="canonical_refunds",
                                source_entity_id=first_r.id,
                                source_reference=ref_id,
                                order_reference=first_r.order_reference,
                                gateway_name="RAZORPAY",
                                expected_amount=first_r.refund_amount,
                                actual_amount=sum(r.refund_amount for r in ref_list),
                                leakage_amount=Decimal("0.0000"),
                                recoverable_amount=Decimal("0.0000"),
                                currency=first_r.currency,
                                calculation_breakdown={
                                    "gateway_refund_id": ref_id,
                                    "entry_count": len(ref_list),
                                    "conflicting_amounts": [str(a) for a in amounts],
                                },
                                explanation=(
                                    f"Refund reference collision: {len(ref_list)} imported records share ID '{ref_id}' "
                                    f"with conflicting amounts ({', '.join(f'₹{a}' for a in amounts)}). Requires audit."
                                ),
                                evidence_items=[
                                    EvidenceItemDraft(
                                        evidence_type="REFUND_EVENT",
                                        entity_type="canonical_refunds",
                                        entity_id=r.id,
                                        source_batch_id=r.batch_id,
                                        source_row_index=r.source_row_index,
                                        details={
                                            "gateway_refund_id": r.gateway_refund_id,
                                            "refund_amount": str(r.refund_amount),
                                            "status": r.status,
                                        }
                                    )
                                    for r in ref_list
                                ]
                            )
                        )

        # -------------------------------------------------------------------
        # CHECK 2: Cumulative Refunds Exceeding Original Capture (Excess Refund)
        # -------------------------------------------------------------------
        refunds_by_payment: Dict[str, List[CanonicalRefund]] = defaultdict(list)
        for r in refunds:
            if r.gateway_payment_id:
                refunds_by_payment[r.gateway_payment_id.strip()].append(r)

        for pay_id, p_refunds in refunds_by_payment.items():
            payment = payments_by_gateway_id.get(pay_id)
            if not payment:
                continue

            # Only evaluate successful / processed refunds
            successful_refunds = [
                r for r in p_refunds
                if r.status and r.status.lower() in ("processed", "settled", "success")
            ]
            total_refunded = sum(r.refund_amount for r in successful_refunds)

            if total_refunded > payment.captured_amount:
                excess_amount = total_refunded - payment.captured_amount
                primary_r = successful_refunds[0]
                findings.append(
                    LeakageFinding(
                        detector_type=DetectorType.REFUND_ANOMALY,
                        exception_type=LeakageExceptionType.EXCESS_REFUND,
                        severity=ExceptionSeverity.CRITICAL if excess_amount >= Decimal("5000.0000") else ExceptionSeverity.HIGH,
                        severity_reason=f"Cumulative processed refunds of ₹{total_refunded} exceed original capture ₹{payment.captured_amount}.",
                        source_entity_type="canonical_payments",
                        source_entity_id=payment.id,
                        source_reference=payment.gateway_payment_id,
                        order_reference=payment.order_reference,
                        gateway_name=payment.gateway_name,
                        expected_amount=payment.captured_amount,
                        actual_amount=total_refunded,
                        leakage_amount=excess_amount,
                        recoverable_amount=excess_amount,
                        currency=payment.currency,
                        calculation_breakdown={
                            "captured_amount": str(payment.captured_amount),
                            "total_refunded_amount": str(total_refunded),
                            "excess_refund_leakage": str(excess_amount),
                            "refund_count": len(successful_refunds),
                            "refund_references": [r.gateway_refund_id for r in successful_refunds],
                        },
                        explanation=(
                            f"Excess refund detected for payment '{pay_id}'. Original captured amount was ₹{payment.captured_amount}, "
                            f"but {len(successful_refunds)} processed refund(s) totaled ₹{total_refunded}. "
                            f"Over-refunded leakage quantum: ₹{excess_amount}."
                        ),
                        evidence_items=[
                            EvidenceItemDraft(
                                evidence_type="PAYMENT_CAPTURE",
                                entity_type="canonical_payments",
                                entity_id=payment.id,
                                source_batch_id=payment.batch_id,
                                source_row_index=payment.source_row_index,
                                details={
                                    "gateway_payment_id": payment.gateway_payment_id,
                                    "captured_amount": str(payment.captured_amount),
                                    "captured_at": payment.captured_at.isoformat(),
                                }
                            ),
                            *[
                                EvidenceItemDraft(
                                    evidence_type="REFUND_EVENT",
                                    entity_type="canonical_refunds",
                                    entity_id=r.id,
                                    source_batch_id=r.batch_id,
                                    source_row_index=r.source_row_index,
                                    details={
                                        "gateway_refund_id": r.gateway_refund_id,
                                        "refund_amount": str(r.refund_amount),
                                        "processed_at": r.processed_at.isoformat() if r.processed_at else None,
                                    }
                                )
                                for r in successful_refunds
                            ]
                        ]
                    )
                )

        # -------------------------------------------------------------------
        # CHECK 3: Orphan / Unauthorized Refunds (No Matching Capture in Database)
        # -------------------------------------------------------------------
        for r in refunds:
            if not r.gateway_payment_id or r.gateway_payment_id.strip() not in payments_by_gateway_id:
                # Refund has no corresponding capture in merchant gateway ledger
                if r.status and r.status.lower() in ("processed", "settled", "success"):
                    findings.append(
                        LeakageFinding(
                            detector_type=DetectorType.REFUND_ANOMALY,
                            exception_type=LeakageExceptionType.UNAUTHORIZED_REFUND,
                            severity=ExceptionSeverity.HIGH,
                            severity_reason=f"Processed refund ₹{r.refund_amount} has no matching payment capture in canonical ledger.",
                            source_entity_type="canonical_refunds",
                            source_entity_id=r.id,
                            source_reference=r.gateway_refund_id,
                            order_reference=r.order_reference,
                            gateway_name="RAZORPAY",
                            expected_amount=Decimal("0.0000"),
                            actual_amount=r.refund_amount,
                            leakage_amount=r.refund_amount,
                            recoverable_amount=r.refund_amount,
                            currency=r.currency,
                            calculation_breakdown={
                                "gateway_refund_id": r.gateway_refund_id,
                                "gateway_payment_id": r.gateway_payment_id,
                                "refund_amount": str(r.refund_amount),
                                "status": r.status,
                                "reason": "No captured payment found matching gateway_payment_id."
                            },
                            explanation=(
                                f"Orphan/unauthorized refund '{r.gateway_refund_id}' for ₹{r.refund_amount} "
                                f"references gateway payment '{r.gateway_payment_id}', which does not exist in captured records. "
                                f"Potential unauthorized fund debit."
                            ),
                            evidence_items=[
                                EvidenceItemDraft(
                                    evidence_type="REFUND_EVENT",
                                    entity_type="canonical_refunds",
                                    entity_id=r.id,
                                    source_batch_id=r.batch_id,
                                    source_row_index=r.source_row_index,
                                    details={
                                        "gateway_refund_id": r.gateway_refund_id,
                                        "gateway_payment_id": r.gateway_payment_id,
                                        "refund_amount": str(r.refund_amount),
                                        "raw_source_data": r.raw_source_data,
                                    }
                                )
                            ]
                        )
                    )

        return findings
