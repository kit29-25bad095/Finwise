import uuid
from decimal import Decimal
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.models.canonical import CanonicalPayment
from app.models.reconciliation import FeeContract
from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity
from app.services.leakage.base_detector import BaseLeakageDetector, LeakageFinding, EvidenceItemDraft
from app.services.leakage.calendar_service import BankingCalendarService, CalendarType, normalize_to_ist
from app.services.leakage.contract_resolver import (
    ContractResolver,
    ContractResolutionStatus,
    TierResolutionStatus,
)
from app.services.reconciliation.fee_calculator import round_half_up


class MissingSettlementDetector(BaseLeakageDetector):
    """
    DETECTOR 1: Missing Gateway Settlement
    Identifies successful payment captures that have not been included in any settlement batch
    past their contractual settlement due date and grace period.
    Strictly isolates observed gross exposure from verified net recovery, eliminates
    unverified fee deduction fallbacks, and prohibits invented turnaround SLAs.
    """

    def detect(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[LeakageFinding]:
        params = parameters or {}
        cutoff_time_str = params.get("settlement_cutoff_time", "23:00")
        grace_period_days = int(params.get("grace_period_days", 1))
        as_of_date: date = params.get("as_of_date") or datetime.now(timezone.utc).date()

        # Calendar configuration (default: GATEWAY_STANDARD fallback)
        raw_calendar_profile = params.get("calendar_profile", "GATEWAY_STANDARD")
        is_fallback_calendar = "calendar_profile" not in params
        try:
            calendar_type = CalendarType(raw_calendar_profile)
        except Exception:
            calendar_type = CalendarType.GATEWAY_STANDARD

        provider_holidays: Optional[Set[date]] = None
        if "provider_holidays" in params:
            provider_holidays = {
                datetime.strptime(d, "%Y-%m-%d").date() if isinstance(d, str) else d
                for d in params["provider_holidays"]
            }

        # Method specific settlement delays: e.g. UPI=1, card=2, netbanking=2, wallet=2
        default_delays: Dict[str, int] = {
            "upi": 1,
            "card": 2,
            "netbanking": 2,
            "wallet": 2,
        }
        delay_map: Optional[Dict[str, int]] = params.get("settlement_delays", default_delays)

        # Query eligible captured payments with remaining unallocated balance
        payments = db.execute(
            select(CanonicalPayment).where(
                and_(
                    CanonicalPayment.tenant_id == tenant_id,
                    CanonicalPayment.status == "captured",
                    CanonicalPayment.captured_amount > Decimal("0.0000"),
                    CanonicalPayment.unallocated_balance > Decimal("0.0000")
                )
            )
        ).scalars().all()

        findings: List[LeakageFinding] = []

        for p in payments:
            capture_date = normalize_to_ist(p.captured_at).date()
            if as_of_date <= capture_date:
                # Capture occurred today or in the future: within normal clearing window, not overdue
                continue

            method_key = (p.payment_method or "").strip().lower()

            # ---------------------------------------------------------------
            # CASE D: Unknown Settlement SLA (T+N)
            # An unknown turnaround SLA must never be replaced by an invented T+2.
            # ---------------------------------------------------------------
            if delay_map is None or method_key not in delay_map:
                findings.append(
                    LeakageFinding(
                        detector_type=DetectorType.MISSING_SETTLEMENT,
                        exception_type=LeakageExceptionType.CONTRACT_CONFIGURATION_MISSING,
                        severity=ExceptionSeverity.MEDIUM,
                        severity_reason=(
                            f"No contractual settlement turnaround SLA (T+N) configured for "
                            f"gateway '{p.gateway_name}' and method '{p.payment_method}'."
                        ),
                        source_entity_type="canonical_payments",
                        source_entity_id=p.id,
                        source_reference=p.gateway_payment_id,
                        order_reference=p.order_reference,
                        gateway_name=p.gateway_name,
                        expected_amount=Decimal("0.0000"),
                        actual_amount=p.unallocated_balance,
                        leakage_amount=Decimal("0.0000"),
                        recoverable_amount=Decimal("0.0000"),
                        currency=p.currency,
                        calculation_breakdown={
                            "observed_unsettled_amount": str(p.unallocated_balance),
                            "sla_status": "UNCONFIGURED_SLA",
                            "reason": (
                                f"Missing contractual turnaround days (T+N) for method '{p.payment_method}'. "
                                f"Overdue calculation halted to prevent false positive assertion."
                            ),
                            "calendar_profile": calendar_type.value,
                            "leakage_amount": "0.0000",
                            "recoverable_amount": "0.0000",
                        },
                        explanation=(
                            f"Capture '{p.gateway_payment_id}' (amount: ₹{p.captured_amount}, method: {p.payment_method}) "
                            f"has no contractual settlement turnaround (T+N) configured. Settlement SLA configuration required."
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
                                    "unallocated_balance": str(p.unallocated_balance),
                                    "payment_method": p.payment_method,
                                }
                            )
                        ],
                        contract_id=None,
                        contract_version=None
                    )
                )
                continue

            turnaround_days = delay_map[method_key]

            # Compute settlement due date using the configured calendar profile
            day_0 = BankingCalendarService.get_day_zero(
                captured_at=p.captured_at,
                cutoff_time_str=cutoff_time_str,
                calendar_type=calendar_type,
                provider_holidays=provider_holidays,
            )
            due_date = BankingCalendarService.add_business_days(
                start_date=day_0,
                business_days=turnaround_days,
                calendar_type=calendar_type,
                provider_holidays=provider_holidays,
            )

            # Check if overdue
            overdue_date = BankingCalendarService.add_business_days(
                start_date=due_date,
                business_days=grace_period_days,
                calendar_type=calendar_type,
                provider_holidays=provider_holidays,
            )

            is_past_due = as_of_date > due_date
            is_past_grace = as_of_date > overdue_date

            if not is_past_due:
                # Still within normal settlement window (not an anomaly)
                continue

            unsettled_amount = p.unallocated_balance
            is_partial = unsettled_amount < p.captured_amount

            # Classify exception type
            if is_past_grace:
                exception_type = (
                    LeakageExceptionType.PARTIALLY_MISSING_SETTLEMENT
                    if is_partial
                    else LeakageExceptionType.MISSING_SETTLEMENT
                )
            else:
                exception_type = LeakageExceptionType.SETTLEMENT_OVERDUE

            # Calculate days overdue
            days_overdue = (as_of_date - due_date).days

            # Determine severity
            if days_overdue >= 14 or unsettled_amount >= Decimal("50000.0000"):
                severity = ExceptionSeverity.CRITICAL
                severity_reason = f"Capture is {days_overdue} days overdue with high unsettled quantum of ₹{unsettled_amount}."
            elif days_overdue >= 7 or unsettled_amount >= Decimal("10000.0000"):
                severity = ExceptionSeverity.HIGH
                severity_reason = f"Settlement is {days_overdue} days overdue exceeding SLA grace period."
            elif days_overdue >= 2 or unsettled_amount >= Decimal("1000.0000"):
                severity = ExceptionSeverity.MEDIUM
                severity_reason = f"Settlement overdue by {days_overdue} business days."
            else:
                severity = ExceptionSeverity.LOW
                severity_reason = f"Settlement recently passed due date by {days_overdue} day(s)."

            # ---------------------------------------------------------------
            # Contract & Tier Verification for Net Recovery Deduction
            # ---------------------------------------------------------------
            capture_date = normalize_to_ist(p.captured_at).date()
            resolution = ContractResolver.resolve_contract_and_tier(
                db=db,
                tenant_id=tenant_id,
                gateway_name=p.gateway_name,
                capture_date=capture_date,
                payment_method=p.payment_method,
                card_type=p.card_type,
                card_network=p.card_network,
            )

            # CASE C: Contract Lineage Ambiguity
            if resolution.status == ContractResolutionStatus.LINEAGE_AMBIGUITY:
                findings.append(
                    LeakageFinding(
                        detector_type=DetectorType.MISSING_SETTLEMENT,
                        exception_type=LeakageExceptionType.FEE_CALCULATION_DISCREPANCY,
                        severity=ExceptionSeverity.HIGH,
                        severity_reason=f"Contract lineage ambiguity for gateway '{p.gateway_name}': {resolution.anomaly_reason}",
                        source_entity_type="canonical_payments",
                        source_entity_id=p.id,
                        source_reference=p.gateway_payment_id,
                        order_reference=p.order_reference,
                        gateway_name=p.gateway_name,
                        expected_amount=Decimal("0.0000"),
                        actual_amount=unsettled_amount,
                        leakage_amount=Decimal("0.0000"),
                        recoverable_amount=Decimal("0.0000"),
                        currency=p.currency,
                        calculation_breakdown={
                            "observed_gross_amount": str(unsettled_amount),
                            "lineage_status": "UNRESOLVED_AMBIGUITY",
                            "anomaly_reason": resolution.anomaly_reason,
                            "conflicting_contracts": resolution.conflicting_contracts,
                            "calendar_profile": calendar_type.value,
                            "is_fallback_calendar": is_fallback_calendar,
                            "leakage_amount": "0.0000",
                            "recoverable_amount": "0.0000",
                        },
                        explanation=(
                            f"Capture '{p.gateway_payment_id}' on {capture_date} is overdue, but fee contract lineage "
                            f"for gateway '{p.gateway_name}' is ambiguous ({resolution.anomaly_reason}). "
                            f"Zero calculated leakage and zero recovery established until contracts are reconciled."
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
                                    "unallocated_balance": str(unsettled_amount),
                                    "payment_method": p.payment_method,
                                }
                            )
                        ],
                        contract_id=None,
                        contract_version=None
                    )
                )
                continue

            # CASE A vs CASE B: Contractual Fee Calculation
            gross_unsettled_amount = unsettled_amount
            contractual_fee_deduction: Decimal = Decimal("0.0000")
            verified_recoverable_amount: Decimal = Decimal("0.0000")
            fee_deduction_metadata: Dict[str, Any] = {}

            if (
                resolution.status == ContractResolutionStatus.RESOLVED
                and resolution.tier_status == TierResolutionStatus.RESOLVED
            ):
                # CASE A: Verified contract and verified tier
                contract = resolution.contract
                tier = resolution.tier
                pct_rate = tier.percentage_rate
                fixed_fee = tier.fixed_fee_per_txn or Decimal("0.0000")
                gst_rate = contract.gst_rate

                unrounded_mdr = round_half_up(p.captured_amount * pct_rate, 4)
                base_fee = unrounded_mdr + fixed_fee
                if tier.min_fee_cap is not None:
                    base_fee = max(tier.min_fee_cap, base_fee)
                if tier.max_fee_cap is not None:
                    base_fee = min(tier.max_fee_cap, base_fee)

                calculated_tax = round_half_up(base_fee * gst_rate, 4)
                contractual_fee_deduction = base_fee + calculated_tax
                verified_recoverable_amount = max(Decimal("0.0000"), gross_unsettled_amount - contractual_fee_deduction)

                fee_deduction_metadata = {
                    "status": "VERIFIED_CONTRACT_APPLIED",
                    "contract_id": str(contract.id),
                    "contract_name": contract.contract_name,
                    "contract_version": contract.version,
                    "tier_id": str(tier.id),
                    "instrument_type": tier.instrument_type,
                    "percentage_rate": str(pct_rate),
                    "gst_rate": str(gst_rate),
                    "deduction_amount": str(contractual_fee_deduction),
                }
                contract_id = contract.id
                contract_version = contract.version
            else:
                # CASE B: Contract or tier cannot be verified
                # Do NOT use DEFAULT_2_PERCENT or tiers[0]. Set deduction to 0.0000.
                contractual_fee_deduction = Decimal("0.0000")
                verified_recoverable_amount = Decimal("0.0000")
                fee_deduction_metadata = {
                    "status": "UNVERIFIED_CONTRACT_FEE_OMITTED",
                    "deduction_amount": "0.0000",
                    "reason": (
                        resolution.anomaly_reason
                        or "No authenticated contract tier available; hypothetical fee deduction omitted."
                    ),
                }
                contract_id = resolution.contract.id if resolution.contract else None
                contract_version = resolution.contract.version if resolution.contract else None

            leakage_amount = gross_unsettled_amount
            recoverable_amount = verified_recoverable_amount

            explanation = (
                f"Capture '{p.gateway_payment_id}' for ₹{p.captured_amount} (method: {p.payment_method or 'unknown'}) "
                f"captured on {p.captured_at.strftime('%Y-%m-%d %H:%M UTC')} had settlement due on {due_date.isoformat()} "
                f"(T+{turnaround_days} using calendar '{calendar_type.value}'). As of {as_of_date.isoformat()}, "
                f"gross unsettled balance is ₹{gross_unsettled_amount} ({days_overdue} days overdue). "
                f"Verified recoverable amount: ₹{verified_recoverable_amount}."
            )

            calculation_breakdown = {
                "captured_amount": str(p.captured_amount),
                "gross_unsettled_amount": str(gross_unsettled_amount),
                "unallocated_balance": str(unsettled_amount),
                "settled_amount": str(p.captured_amount - unsettled_amount),
                "captured_at": p.captured_at.isoformat(),
                "cutoff_time": cutoff_time_str,
                "calendar_profile": calendar_type.value,
                "is_fallback_calendar": is_fallback_calendar,
                "day_0": day_0.isoformat(),
                "turnaround_days": turnaround_days,
                "due_date": due_date.isoformat(),
                "overdue_date_with_grace": overdue_date.isoformat(),
                "as_of_date": as_of_date.isoformat(),
                "days_overdue": days_overdue,
                "is_partial_settlement": is_partial,
                "contractual_fee_deduction": fee_deduction_metadata,
                "verified_recoverable_amount": str(verified_recoverable_amount),
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
                        "gateway_order_id": p.gateway_order_id,
                        "order_reference": p.order_reference,
                        "captured_amount": str(p.captured_amount),
                        "captured_at": p.captured_at.isoformat(),
                        "payment_method": p.payment_method,
                        "raw_source_data": p.raw_source_data,
                    }
                )
            ]

            findings.append(
                LeakageFinding(
                    detector_type=DetectorType.MISSING_SETTLEMENT,
                    exception_type=exception_type,
                    severity=severity,
                    severity_reason=severity_reason,
                    source_entity_type="canonical_payments",
                    source_entity_id=p.id,
                    source_reference=p.gateway_payment_id,
                    order_reference=p.order_reference,
                    gateway_name=p.gateway_name,
                    expected_amount=p.captured_amount,
                    actual_amount=p.captured_amount - unsettled_amount,
                    leakage_amount=leakage_amount,
                    recoverable_amount=recoverable_amount,
                    currency=p.currency,
                    calculation_breakdown=calculation_breakdown,
                    explanation=explanation,
                    evidence_items=evidence_items,
                    contract_id=contract_id,
                    contract_version=contract_version
                )
            )

        return findings
