import uuid
from decimal import Decimal
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func

from app.models.canonical import CanonicalSettlement, CanonicalBankTransaction
from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity
from app.services.leakage.base_detector import BaseLeakageDetector, LeakageFinding, EvidenceItemDraft
from app.services.leakage.calendar_service import BankingCalendarService, CalendarType, normalize_to_ist


class UncreditedSettlementDetector(BaseLeakageDetector):
    """
    DETECTOR 2: Settlement Not Credited to Bank
    Identifies gateway payouts/settlements that have not been credited to the merchant's bank account
    past their expected clearing window, with bank statement completeness defense.
    Strictly applies RBI bank clearing calendar rules (Sundays and 2nd/4th Saturdays closed).
    """

    def detect(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[LeakageFinding]:
        params = parameters or {}
        clearing_window_days = int(params.get("bank_clearing_window_days", 1))
        grace_period_days = int(params.get("grace_period_days", 1))
        as_of_date: date = params.get("as_of_date") or datetime.now(timezone.utc).date()

        bank_holidays: Optional[Set[date]] = None
        if "bank_holidays" in params:
            bank_holidays = {
                datetime.strptime(d, "%Y-%m-%d").date() if isinstance(d, str) else d
                for d in params["bank_holidays"]
            }

        # 1. Inspect bank statement coverage (Completeness Defense)
        bank_date_stats = db.execute(
            select(
                func.min(CanonicalBankTransaction.transaction_date),
                func.max(CanonicalBankTransaction.transaction_date),
                func.count(CanonicalBankTransaction.id)
            ).where(CanonicalBankTransaction.tenant_id == tenant_id)
        ).first()

        bank_min_date: Optional[date] = bank_date_stats[0] if bank_date_stats else None
        bank_max_date: Optional[date] = bank_date_stats[1] if bank_date_stats else None
        bank_tx_count: int = bank_date_stats[2] if bank_date_stats else 0

        # Query eligible settlements with remaining unallocated balance
        settlements = db.execute(
            select(CanonicalSettlement).where(
                and_(
                    CanonicalSettlement.tenant_id == tenant_id,
                    CanonicalSettlement.status == "settled",
                    CanonicalSettlement.net_settlement_amount > Decimal("0.0000"),
                    CanonicalSettlement.unallocated_balance > Decimal("0.0000")
                )
            )
        ).scalars().all()

        findings: List[LeakageFinding] = []

        for s in settlements:
            settlement_date = normalize_to_ist(s.settled_at).date()

            # Expected bank credit date under RBI bank clearing rail
            expected_credit_date = BankingCalendarService.add_business_days(
                start_date=settlement_date,
                business_days=clearing_window_days,
                calendar_type=CalendarType.BANK_CLEARING,
                bank_holidays=bank_holidays,
            )
            overdue_credit_date = BankingCalendarService.add_business_days(
                start_date=expected_credit_date,
                business_days=grace_period_days,
                calendar_type=CalendarType.BANK_CLEARING,
                bank_holidays=bank_holidays,
            )

            # Bank Statement Completeness Check
            # If bank statement does not reach the overdue date, we cannot assert that money is missing!
            statement_gap = False
            if bank_tx_count == 0 or bank_max_date is None or bank_max_date < expected_credit_date:
                statement_gap = True

            if as_of_date <= expected_credit_date:
                # Within normal clearing window
                continue

            uncredited_amount = s.unallocated_balance
            is_partial = uncredited_amount < s.net_settlement_amount

            # Check if there is a bank credit with the exact same UTR but different amount (amount mismatch)
            mismatch_candidate = None
            if s.utr_number:
                mismatch_candidate = db.execute(
                    select(CanonicalBankTransaction).where(
                        and_(
                            CanonicalBankTransaction.tenant_id == tenant_id,
                            CanonicalBankTransaction.extracted_utr == s.utr_number,
                            CanonicalBankTransaction.credit_amount > Decimal("0.0000")
                        )
                    )
                ).scalars().first()

            # Calculate days overdue
            days_overdue = (as_of_date - expected_credit_date).days

            # Classify exception type and severity
            if mismatch_candidate and mismatch_candidate.credit_amount != s.net_settlement_amount:
                exception_type = LeakageExceptionType.SETTLEMENT_AMOUNT_MISMATCH
                severity = ExceptionSeverity.HIGH
                severity_reason = (
                    f"Bank credit with matching UTR '{s.utr_number}' was credited for ₹{mismatch_candidate.credit_amount}, "
                    f"diverging from expected net payout ₹{s.net_settlement_amount}."
                )
            elif statement_gap:
                # Bank statements missing or not imported up to expected credit date
                exception_type = LeakageExceptionType.AMBIGUOUS_BANK_CREDIT
                severity = ExceptionSeverity.LOW
                severity_reason = (
                    f"Bank statements are only imported up to {bank_max_date.isoformat() if bank_max_date else 'N/A'}. "
                    f"Cannot verify bank credit until bank statement upload covering {expected_credit_date.isoformat()} is imported."
                )
            elif as_of_date > overdue_credit_date:
                exception_type = (
                    LeakageExceptionType.PARTIALLY_UNCREDITED_SETTLEMENT
                    if is_partial
                    else LeakageExceptionType.UNCREDITED_SETTLEMENT
                )
                if days_overdue >= 14 or uncredited_amount >= Decimal("100000.0000"):
                    severity = ExceptionSeverity.CRITICAL
                    severity_reason = f"Gateway settlement payout has been missing from bank account for {days_overdue} days (quantum: ₹{uncredited_amount})."
                elif days_overdue >= 7 or uncredited_amount >= Decimal("25000.0000"):
                    severity = ExceptionSeverity.HIGH
                    severity_reason = f"Settlement uncredited past bank clearing SLA by {days_overdue} days."
                else:
                    severity = ExceptionSeverity.MEDIUM
                    severity_reason = f"Settlement uncredited past SLA grace period by {days_overdue} day(s)."
            else:
                # In grace period
                exception_type = LeakageExceptionType.AMBIGUOUS_BANK_CREDIT
                severity = ExceptionSeverity.LOW
                severity_reason = f"Settlement recently passed clearing date by {days_overdue} day(s); within grace period."

            explanation = (
                f"Settlement batch '{s.settlement_reference}' (UTR: {s.utr_number or 'N/A'}, net payout: ₹{s.net_settlement_amount}) "
                f"settled on {settlement_date.isoformat()} had expected bank credit on {expected_credit_date.isoformat()} "
                f"(clearing window: {clearing_window_days} business day(s) via '{CalendarType.BANK_CLEARING.value}'). "
            )
            if statement_gap:
                explanation += (
                    f"Notice: Bank statement coverage ends at {bank_max_date.isoformat() if bank_max_date else 'N/A'}, "
                    f"which does not cover the expected credit window. Import subsequent bank statements to verify receipt."
                )
            else:
                explanation += f"Uncredited amount: ₹{uncredited_amount} ({days_overdue} days overdue)."

            calculation_breakdown = {
                "net_settlement_amount": str(s.net_settlement_amount),
                "unallocated_balance": str(uncredited_amount),
                "credited_amount": str(s.net_settlement_amount - uncredited_amount),
                "utr_number": s.utr_number,
                "settled_at": s.settled_at.isoformat(),
                "calendar_profile": CalendarType.BANK_CLEARING.value,
                "expected_credit_date": expected_credit_date.isoformat(),
                "as_of_date": as_of_date.isoformat(),
                "days_overdue": days_overdue,
                "is_partial_credit": is_partial,
                "bank_statements_cover_window": not statement_gap,
                "bank_statement_max_date": bank_max_date.isoformat() if bank_max_date else None,
                "mismatch_bank_credit": str(mismatch_candidate.credit_amount) if mismatch_candidate else None,
            }

            evidence_items = [
                EvidenceItemDraft(
                    evidence_type="SETTLEMENT_BATCH",
                    entity_type="canonical_settlements",
                    entity_id=s.id,
                    source_batch_id=s.batch_id,
                    source_row_index=s.source_row_index,
                    details={
                        "settlement_reference": s.settlement_reference,
                        "utr_number": s.utr_number,
                        "gross_amount": str(s.gross_amount),
                        "total_fee": str(s.total_fee),
                        "total_tax": str(s.total_tax),
                        "net_settlement_amount": str(s.net_settlement_amount),
                        "settled_at": s.settled_at.isoformat(),
                        "raw_source_data": s.raw_source_data,
                    }
                )
            ]

            if mismatch_candidate:
                evidence_items.append(
                    EvidenceItemDraft(
                        evidence_type="BANK_TRANSACTION",
                        entity_type="canonical_bank_transactions",
                        entity_id=mismatch_candidate.id,
                        source_batch_id=mismatch_candidate.batch_id,
                        source_row_index=mismatch_candidate.source_row_index,
                        details={
                            "bank_reference": mismatch_candidate.bank_reference,
                            "extracted_utr": mismatch_candidate.extracted_utr,
                            "raw_narration": mismatch_candidate.raw_narration,
                            "credit_amount": str(mismatch_candidate.credit_amount),
                            "transaction_date": mismatch_candidate.transaction_date.isoformat(),
                        }
                    )
                )

            findings.append(
                LeakageFinding(
                    detector_type=DetectorType.UNCREDITED_SETTLEMENT,
                    exception_type=exception_type,
                    severity=severity,
                    severity_reason=severity_reason,
                    source_entity_type="canonical_settlements",
                    source_entity_id=s.id,
                    source_reference=s.settlement_reference,
                    order_reference=None,
                    gateway_name=s.gateway_name,
                    expected_amount=s.net_settlement_amount,
                    actual_amount=s.net_settlement_amount - uncredited_amount,
                    leakage_amount=uncredited_amount,
                    recoverable_amount=Decimal("0.0000") if statement_gap else uncredited_amount,
                    currency="INR",
                    calculation_breakdown=calculation_breakdown,
                    explanation=explanation,
                    evidence_items=evidence_items,
                    contract_id=None,
                    contract_version=None
                )
            )

        return findings
