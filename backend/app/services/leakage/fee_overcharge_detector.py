import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.models.canonical import CanonicalPayment
from app.models.reconciliation import FeeContract, FeeScheduleTier
from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity
from app.services.leakage.base_detector import BaseLeakageDetector, LeakageFinding, EvidenceItemDraft
from app.services.leakage.calendar_service import normalize_to_ist
from app.services.leakage.contract_resolver import (
    ContractResolver,
    ContractResolutionStatus,
    TierResolutionStatus,
)
from app.services.reconciliation.fee_calculator import round_half_up


class FeeOverchargeDetector(BaseLeakageDetector):
    """
    DETECTOR 3: Contractual Fee Overcharges
    Compares actual gateway fee and tax deductions against the merchant's versioned
    FeeContract and tariff schedule, strictly adhering to non-negotiable tax configuration
    and deterministic contract lineage without arbitrary tier fallback.
    """

    def detect(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[LeakageFinding]:
        params = parameters or {}
        fee_tolerance = Decimal(str(params.get("fee_overcharge_tolerance", "0.05")))

        # Query all captured payments for tenant
        payments = db.execute(
            select(CanonicalPayment).where(
                and_(
                    CanonicalPayment.tenant_id == tenant_id,
                    CanonicalPayment.status == "captured"
                )
            )
        ).scalars().all()

        findings: List[LeakageFinding] = []

        for p in payments:
            reported_fee = p.reported_fee or Decimal("0.0000")
            reported_tax = p.reported_tax or Decimal("0.0000")
            reported_total = reported_fee + reported_tax

            # Capture date in Indian Standard Time (IST)
            capture_date = normalize_to_ist(p.captured_at).date()

            # Resolve contract and tier deterministically using shared resolver
            resolution = ContractResolver.resolve_contract_and_tier(
                db=db,
                tenant_id=tenant_id,
                gateway_name=p.gateway_name,
                capture_date=capture_date,
                payment_method=p.payment_method,
                card_type=p.card_type,
                card_network=p.card_network,
            )

            # ---------------------------------------------------------------
            # 1. No contract configured for tenant / gateway / date
            # ---------------------------------------------------------------
            if resolution.status == ContractResolutionStatus.NO_CONTRACT_CONFIGURED:
                if reported_total > Decimal("0.0000"):
                    findings.append(
                        LeakageFinding(
                            detector_type=DetectorType.FEE_OVERCHARGE,
                            exception_type=LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING,
                            severity=ExceptionSeverity.MEDIUM,
                            severity_reason=f"No fee contract configured for gateway '{p.gateway_name}' covering capture date {capture_date}.",
                            source_entity_type="canonical_payments",
                            source_entity_id=p.id,
                            source_reference=p.gateway_payment_id,
                            order_reference=p.order_reference,
                            gateway_name=p.gateway_name,
                            expected_amount=Decimal("0.0000"),
                            actual_amount=reported_total,
                            leakage_amount=Decimal("0.0000"),
                            recoverable_amount=Decimal("0.0000"),
                            currency=p.currency,
                            calculation_breakdown={
                                "reported_fee": str(reported_fee),
                                "reported_tax": str(reported_tax),
                                "reported_total": str(reported_total),
                                "capture_date": capture_date.isoformat(),
                                "reason": resolution.anomaly_reason or "No contract configured covering capture date.",
                                "leakage_amount": "0.0000",
                                "recoverable_amount": "0.0000",
                            },
                            explanation=(
                                f"Payment '{p.gateway_payment_id}' incurred reported fees of ₹{reported_fee} + tax ₹{reported_tax} "
                                f"(total ₹{reported_total}), but no active FeeContract is configured covering capture date {capture_date}. "
                                f"Contract configuration required."
                            ),
                            evidence_items=[
                                EvidenceItemDraft(
                                    evidence_type="PAYMENT_CAPTURE",
                                    entity_type="canonical_payments",
                                    entity_id=p.id,
                                    source_batch_id=p.batch_id,
                                    source_row_index=p.source_row_index,
                                    details={
                                        "gateway_payment_id": p.gateway_payment_id,
                                        "captured_amount": str(p.captured_amount),
                                        "reported_fee": str(reported_fee),
                                        "reported_tax": str(reported_tax),
                                        "payment_method": p.payment_method,
                                        "capture_date": capture_date.isoformat(),
                                    }
                                )
                            ],
                            contract_id=None,
                            contract_version=None
                        )
                    )
                continue

            # ---------------------------------------------------------------
            # 2. Contract lineage ambiguity (conflicting versions / overlaps)
            # ---------------------------------------------------------------
            if resolution.status == ContractResolutionStatus.LINEAGE_AMBIGUITY:
                if reported_total > Decimal("0.0000"):
                    findings.append(
                        LeakageFinding(
                            detector_type=DetectorType.FEE_OVERCHARGE,
                            exception_type=LeakageExceptionType.FEE_CALCULATION_DISCREPANCY,
                            severity=ExceptionSeverity.HIGH,
                            severity_reason=f"Contract lineage ambiguity for gateway '{p.gateway_name}': {resolution.anomaly_reason}",
                            source_entity_type="canonical_payments",
                            source_entity_id=p.id,
                            source_reference=p.gateway_payment_id,
                            order_reference=p.order_reference,
                            gateway_name=p.gateway_name,
                            expected_amount=Decimal("0.0000"),
                            actual_amount=reported_total,
                            leakage_amount=Decimal("0.0000"),
                            recoverable_amount=Decimal("0.0000"),
                            currency=p.currency,
                            calculation_breakdown={
                                "reported_total": str(reported_total),
                                "capture_date": capture_date.isoformat(),
                                "lineage_status": "UNRESOLVED_LINEAGE_AMBIGUITY",
                                "anomaly_reason": resolution.anomaly_reason,
                                "conflicting_contracts": resolution.conflicting_contracts,
                                "leakage_amount": "0.0000",
                                "recoverable_amount": "0.0000",
                            },
                            explanation=(
                                f"Payment '{p.gateway_payment_id}' on {capture_date} cannot be evaluated because "
                                f"conflicting contracts or version dates exist for gateway '{p.gateway_name}': "
                                f"{resolution.anomaly_reason}. Manual contract reconciliation required."
                            ),
                            evidence_items=[
                                EvidenceItemDraft(
                                    evidence_type="PAYMENT_CAPTURE",
                                    entity_type="canonical_payments",
                                    entity_id=p.id,
                                    source_batch_id=p.batch_id,
                                    source_row_index=p.source_row_index,
                                    details={
                                        "gateway_payment_id": p.gateway_payment_id,
                                        "captured_amount": str(p.captured_amount),
                                        "reported_fee": str(reported_fee),
                                        "reported_tax": str(reported_tax),
                                        "payment_method": p.payment_method,
                                    }
                                )
                            ],
                            contract_id=None,
                            contract_version=None
                        )
                    )
                continue

            # ---------------------------------------------------------------
            # 3. Contract resolved, evaluate tier resolution
            # ---------------------------------------------------------------
            contract = resolution.contract
            if resolution.tier_status == TierResolutionStatus.TIER_NOT_FOUND:
                if reported_total > Decimal("0.0000"):
                    findings.append(
                        LeakageFinding(
                            detector_type=DetectorType.FEE_OVERCHARGE,
                            exception_type=LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING,
                            severity=ExceptionSeverity.MEDIUM,
                            severity_reason=f"Contract '{contract.contract_name}' lacks tariff tier for method '{p.payment_method}'.",
                            source_entity_type="canonical_payments",
                            source_entity_id=p.id,
                            source_reference=p.gateway_payment_id,
                            order_reference=p.order_reference,
                            gateway_name=p.gateway_name,
                            expected_amount=Decimal("0.0000"),
                            actual_amount=reported_total,
                            leakage_amount=Decimal("0.0000"),
                            recoverable_amount=Decimal("0.0000"),
                            currency=p.currency,
                            calculation_breakdown={
                                "contract_id": str(contract.id),
                                "contract_name": contract.contract_name,
                                "contract_version": contract.version,
                                "reported_total": str(reported_total),
                                "payment_method": p.payment_method,
                                "tier_status": "TIER_NOT_FOUND",
                                "reason": resolution.anomaly_reason,
                                "leakage_amount": "0.0000",
                                "recoverable_amount": "0.0000",
                            },
                            explanation=(
                                f"Contract '{contract.contract_name}' (v{contract.version}) has no tariff tier "
                                f"configured for payment method '{p.payment_method}'. Tariff definition required."
                            ),
                            evidence_items=[
                                EvidenceItemDraft(
                                    evidence_type="PAYMENT_CAPTURE",
                                    entity_type="canonical_payments",
                                    entity_id=p.id,
                                    source_batch_id=p.batch_id,
                                    source_row_index=p.source_row_index,
                                    details={
                                        "gateway_payment_id": p.gateway_payment_id,
                                        "captured_amount": str(p.captured_amount),
                                        "reported_fee": str(reported_fee),
                                        "reported_tax": str(reported_tax),
                                        "payment_method": p.payment_method,
                                    }
                                )
                            ],
                            contract_id=contract.id,
                            contract_version=contract.version
                        )
                    )
                continue

            if resolution.tier_status == TierResolutionStatus.INSTRUMENT_AMBIGUOUS:
                if reported_total > Decimal("0.0000"):
                    findings.append(
                        LeakageFinding(
                            detector_type=DetectorType.FEE_OVERCHARGE,
                            exception_type=LeakageExceptionType.FEE_CALCULATION_DISCREPANCY,
                            severity=ExceptionSeverity.MEDIUM,
                            severity_reason=f"Ambiguous card instrument for payment '{p.gateway_payment_id}': missing card_type.",
                            source_entity_type="canonical_payments",
                            source_entity_id=p.id,
                            source_reference=p.gateway_payment_id,
                            order_reference=p.order_reference,
                            gateway_name=p.gateway_name,
                            expected_amount=Decimal("0.0000"),
                            actual_amount=reported_total,
                            leakage_amount=Decimal("0.0000"),
                            recoverable_amount=Decimal("0.0000"),
                            currency=p.currency,
                            calculation_breakdown={
                                "contract_id": str(contract.id),
                                "contract_name": contract.contract_name,
                                "contract_version": contract.version,
                                "reported_total": str(reported_total),
                                "payment_method": p.payment_method,
                                "tier_status": "INSTRUMENT_AMBIGUOUS",
                                "reason": resolution.anomaly_reason,
                                "leakage_amount": "0.0000",
                                "recoverable_amount": "0.0000",
                            },
                            explanation=(
                                f"Payment '{p.gateway_payment_id}' has method '{p.payment_method}' but lacks card_type. "
                                f"Contract '{contract.contract_name}' has separate Debit and Credit tiers; "
                                f"tier cannot be established without instrument evidence. Zero leakage calculated."
                            ),
                            evidence_items=[
                                EvidenceItemDraft(
                                    evidence_type="PAYMENT_CAPTURE",
                                    entity_type="canonical_payments",
                                    entity_id=p.id,
                                    source_batch_id=p.batch_id,
                                    source_row_index=p.source_row_index,
                                    details={
                                        "gateway_payment_id": p.gateway_payment_id,
                                        "captured_amount": str(p.captured_amount),
                                        "reported_fee": str(reported_fee),
                                        "reported_tax": str(reported_tax),
                                        "payment_method": p.payment_method,
                                    }
                                )
                            ],
                            contract_id=contract.id,
                            contract_version=contract.version
                        )
                    )
                continue

            # ---------------------------------------------------------------
            # 4. Verified Contract and Verified Tier -> Compute Expected Fees
            # ---------------------------------------------------------------
            selected_tier = resolution.tier
            capture_amount = p.captured_amount
            pct_rate = selected_tier.percentage_rate
            fixed_fee = selected_tier.fixed_fee_per_txn or Decimal("0.0000")
            gst_rate = contract.gst_rate  # Strictly from contract!

            unrounded_mdr = round_half_up(capture_amount * pct_rate, 4)
            base_fee = unrounded_mdr + fixed_fee
            if selected_tier.min_fee_cap is not None:
                base_fee = max(selected_tier.min_fee_cap, base_fee)
            if selected_tier.max_fee_cap is not None:
                base_fee = min(selected_tier.max_fee_cap, base_fee)

            calculated_tax = round_half_up(base_fee * gst_rate, 4)
            expected_total_fee = base_fee + calculated_tax

            # Overcharge Delta
            overcharge_delta = reported_total - expected_total_fee

            # Evaluate with tolerance
            if overcharge_delta > fee_tolerance:
                # Check if entire fee was unauthorized (e.g. 0% tier charged)
                is_unauthorized = (expected_total_fee == Decimal("0.0000") and reported_total > Decimal("0.0000"))
                exception_type = (
                    LeakageExceptionType.UNAUTHORIZED_FEE
                    if is_unauthorized
                    else LeakageExceptionType.FEE_OVERCHARGE
                )

                # Determine severity based on financial quantum and rate divergence
                if overcharge_delta >= Decimal("500.0000"):
                    severity = ExceptionSeverity.CRITICAL
                    severity_reason = f"Fee overcharge delta of ₹{overcharge_delta} on single transaction."
                elif overcharge_delta >= Decimal("100.0000"):
                    severity = ExceptionSeverity.HIGH
                    severity_reason = f"Contractual MDR/tax overcharge of ₹{overcharge_delta}."
                elif overcharge_delta >= Decimal("10.0000"):
                    severity = ExceptionSeverity.MEDIUM
                    severity_reason = f"Gateway deduction exceeds contractual schedule by ₹{overcharge_delta}."
                else:
                    severity = ExceptionSeverity.LOW
                    severity_reason = f"Minor fee overcharge delta ₹{overcharge_delta} exceeding tolerance ₹{fee_tolerance}."

                explanation = (
                    f"Payment capture '{p.gateway_payment_id}' (amount: ₹{capture_amount}, method: {p.payment_method}) "
                    f"was debited ₹{reported_total} (fee: ₹{reported_fee}, tax: ₹{reported_tax}). "
                    f"Under contract '{contract.contract_name}' v{contract.version} ({selected_tier.instrument_type} @ "
                    f"{pct_rate * 100}% + ₹{fixed_fee}, GST {gst_rate * 100}%), expected fee is ₹{expected_total_fee} "
                    f"(base: ₹{base_fee}, tax: ₹{calculated_tax}). Contractual overcharge: ₹{overcharge_delta}."
                )

                calculation_breakdown = {
                    "captured_amount": str(capture_amount),
                    "percentage_rate": str(pct_rate),
                    "fixed_fee": str(fixed_fee),
                    "unrounded_mdr": str(unrounded_mdr),
                    "base_fee": str(base_fee),
                    "contractual_gst_rate": str(gst_rate),
                    "calculated_tax": str(calculated_tax),
                    "expected_total_fee": str(expected_total_fee),
                    "reported_fee": str(reported_fee),
                    "reported_tax": str(reported_tax),
                    "reported_total": str(reported_total),
                    "overcharge_delta": str(overcharge_delta),
                    "fee_tolerance_applied": str(fee_tolerance),
                    "contract_id": str(contract.id),
                    "contract_version": contract.version,
                    "tier_instrument": selected_tier.instrument_type,
                }

                evidence_items = [
                    EvidenceItemDraft(
                        evidence_type="PAYMENT_CAPTURE",
                        entity_type="canonical_payments",
                        entity_id=p.id,
                        source_batch_id=p.batch_id,
                        source_row_index=p.source_row_index,
                        details={
                            "gateway_payment_id": p.gateway_payment_id,
                            "captured_amount": str(p.captured_amount),
                            "reported_fee": str(reported_fee),
                            "reported_tax": str(reported_tax),
                            "payment_method": p.payment_method,
                        }
                    ),
                    EvidenceItemDraft(
                        evidence_type="FEE_CONTRACT_TIER",
                        entity_type="fee_contracts",
                        entity_id=contract.id,
                        details={
                            "contract_name": contract.contract_name,
                            "version": contract.version,
                            "instrument_type": selected_tier.instrument_type,
                            "percentage_rate": str(pct_rate),
                            "fixed_fee_per_txn": str(fixed_fee),
                            "gst_rate": str(gst_rate),
                        }
                    )
                ]

                findings.append(
                    LeakageFinding(
                        detector_type=DetectorType.FEE_OVERCHARGE,
                        exception_type=exception_type,
                        severity=severity,
                        severity_reason=severity_reason,
                        source_entity_type="canonical_payments",
                        source_entity_id=p.id,
                        source_reference=p.gateway_payment_id,
                        order_reference=p.order_reference,
                        gateway_name=p.gateway_name,
                        expected_amount=expected_total_fee,
                        actual_amount=reported_total,
                        leakage_amount=overcharge_delta,
                        recoverable_amount=overcharge_delta,
                        currency=p.currency,
                        calculation_breakdown=calculation_breakdown,
                        explanation=explanation,
                        evidence_items=evidence_items,
                        contract_id=contract.id,
                        contract_version=contract.version
                    )
                )

        return findings
