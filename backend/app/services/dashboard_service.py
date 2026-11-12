import uuid
import os
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, func, desc

from app.models.tenant import Tenant
from app.models.user import User
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalBankTransaction,
    CanonicalRefund,
)
from app.models.reconciliation import (
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    FeeContract,
    FeeScheduleTier,
    ReconciliationStatus,
    MatchClassification,
    MatchType,
    ReviewStatus,
    AllocationStatus,
)
from app.models.audit import AuditLog
from app.schemas.dashboard import (
    DashboardOverviewResponse,
    ThreeWayFlowOverview,
    FlowStageSummary,
    LeakageTrendItem,
    CategoryLeakageSummary,
    SeverityLeakageSummary,
    LeakageFindingItem,
    LeakageFindingsResponse,
    ReviewQueueItem,
    ReviewQueueCandidate,
    ReviewQueueResponse,
    FeeAnalyticsResponse,
    FeeInstrumentTierAnalytics,
    AIInvestigationStatusResponse,
    AuditLogsResponse,
    AuditLogItem,
)
from app.schemas.reconciliation import FeeContractResponse


class DashboardService:
    @staticmethod
    def get_dashboard_overview(db: Session, tenant_id: uuid.UUID) -> DashboardOverviewResponse:
        tenant = db.get(Tenant, tenant_id)
        tenant_name = tenant.name if tenant else "Finora Enterprise"

        # 1. Total Canonical Quantities & Amounts
        orders_stat = db.execute(
            select(
                func.count(CanonicalOrder.id),
                func.coalesce(func.sum(CanonicalOrder.gross_amount), Decimal("0.0000"))
            ).where(CanonicalOrder.tenant_id == tenant_id)
        ).first()
        total_orders_count = orders_stat[0] or 0
        total_orders_amount = orders_stat[1] or Decimal("0.0000")

        payments_stat = db.execute(
            select(
                func.count(CanonicalPayment.id),
                func.coalesce(func.sum(CanonicalPayment.captured_amount), Decimal("0.0000")),
                func.coalesce(func.sum(CanonicalPayment.unallocated_balance), Decimal("0.0000"))
            ).where(CanonicalPayment.tenant_id == tenant_id)
        ).first()
        total_captured_count = payments_stat[0] or 0
        total_captured_amount = payments_stat[1] or Decimal("0.0000")
        unallocated_payments_amount = payments_stat[2] or Decimal("0.0000")

        settlements_stat = db.execute(
            select(
                func.count(CanonicalSettlement.id),
                func.coalesce(func.sum(CanonicalSettlement.net_settlement_amount), Decimal("0.0000")),
                func.coalesce(func.sum(CanonicalSettlement.unallocated_balance), Decimal("0.0000"))
            ).where(CanonicalSettlement.tenant_id == tenant_id)
        ).first()
        total_settlements_count = settlements_stat[0] or 0
        total_settled_amount = settlements_stat[1] or Decimal("0.0000")
        unallocated_settlements_amount = settlements_stat[2] or Decimal("0.0000")

        bank_stat = db.execute(
            select(
                func.count(CanonicalBankTransaction.id),
                func.coalesce(func.sum(CanonicalBankTransaction.credit_amount), Decimal("0.0000")),
                func.coalesce(func.sum(CanonicalBankTransaction.unallocated_balance), Decimal("0.0000"))
            ).where(CanonicalBankTransaction.tenant_id == tenant_id)
        ).first()
        total_bank_credits_count = bank_stat[0] or 0
        total_bank_credited_amount = bank_stat[1] or Decimal("0.0000")
        unallocated_bank_amount = bank_stat[2] or Decimal("0.0000")

        # 2. Latest Active Reconciliation Run
        latest_run = db.execute(
            select(ReconciliationRun).where(
                ReconciliationRun.tenant_id == tenant_id
            ).order_by(desc(ReconciliationRun.run_number))
        ).scalars().first()

        latest_run_id = latest_run.id if latest_run else None
        latest_run_number = latest_run.run_number if latest_run else None
        latest_run_status = latest_run.status if latest_run else None
        latest_run_timestamp = latest_run.created_at if latest_run else None

        if latest_run:
            reconciled_amount = latest_run.total_matched_bank_amount
            unmatched_amount = latest_run.total_discrepancy_amount
            total_detected_leakage = latest_run.total_discrepancy_amount + latest_run.total_fee_drift_amount
        else:
            reconciled_amount = total_bank_credited_amount - unallocated_bank_amount
            unmatched_amount = unallocated_bank_amount + unallocated_payments_amount
            total_detected_leakage = unallocated_settlements_amount

        # Accuracy percentage calculation
        if total_captured_amount > Decimal("0.0000"):
            accuracy_rate = ((reconciled_amount / total_captured_amount) * Decimal("100.0000")).quantize(Decimal("0.01"))
            if accuracy_rate > Decimal("100.00"):
                accuracy_rate = Decimal("100.00")
        else:
            accuracy_rate = Decimal("100.00") if total_orders_count == 0 else Decimal("0.00")

        # 3. Pending Review Queue Count
        pending_review_count = db.execute(
            select(func.count(ReconciliationMatch.id)).where(
                and_(
                    ReconciliationMatch.tenant_id == tenant_id,
                    ReconciliationMatch.review_status == ReviewStatus.PENDING_REVIEW.value
                )
            )
        ).scalar() or 0

        # 4. Three-Way Flow Summaries
        matched_orders_cnt = latest_run.matched_orders_count if latest_run else 0
        unmatched_orders_cnt = latest_run.unmatched_orders_count if latest_run else total_orders_count
        matched_orders_amt = latest_run.total_order_amount if latest_run else Decimal("0.0000")
        unmatched_orders_amt = total_orders_amount - matched_orders_amt if total_orders_amount >= matched_orders_amt else Decimal("0.0000")

        flow = ThreeWayFlowOverview(
            shopify_orders=FlowStageSummary(
                total_count=total_orders_count,
                total_amount=total_orders_amount,
                matched_count=matched_orders_cnt,
                matched_amount=matched_orders_amt,
                unmatched_count=unmatched_orders_cnt,
                unmatched_amount=unmatched_orders_amt,
            ),
            razorpay_payments=FlowStageSummary(
                total_count=total_captured_count,
                total_amount=total_captured_amount,
                matched_count=latest_run.matched_payments_count if latest_run else (total_captured_count if unallocated_payments_amount == 0 else 0),
                matched_amount=total_captured_amount - unallocated_payments_amount,
                unmatched_count=latest_run.unmatched_payments_count if latest_run else (total_captured_count if unallocated_payments_amount > 0 else 0),
                unmatched_amount=unallocated_payments_amount,
            ),
            gateway_settlements=FlowStageSummary(
                total_count=total_settlements_count,
                total_amount=total_settled_amount,
                matched_count=latest_run.matched_settlements_count if latest_run else (total_settlements_count if unallocated_settlements_amount == 0 else 0),
                matched_amount=total_settled_amount - unallocated_settlements_amount,
                unmatched_count=latest_run.unmatched_settlements_count if latest_run else (total_settlements_count if unallocated_settlements_amount > 0 else 0),
                unmatched_amount=unallocated_settlements_amount,
            ),
            hdfc_bank_credits=FlowStageSummary(
                total_count=total_bank_credits_count,
                total_amount=total_bank_credited_amount,
                matched_count=latest_run.matched_bank_txs_count if latest_run else (total_bank_credits_count if unallocated_bank_amount == 0 else 0),
                matched_amount=total_bank_credited_amount - unallocated_bank_amount,
                unmatched_count=latest_run.unmatched_bank_txs_count if latest_run else (total_bank_credits_count if unallocated_bank_amount > 0 else 0),
                unmatched_amount=unallocated_bank_amount,
            ),
        )

        # 5. Leakage Categorization & Severity
        leakage_findings_count = 0
        cat_summaries = {
            "MISSING_SETTLEMENT": {"name": "Missing Gateway Settlements", "count": 0, "amount": Decimal("0.0000")},
            "UNCREDITED_SETTLEMENT": {"name": "Settlements Uncredited to Bank", "count": 0, "amount": Decimal("0.0000")},
            "FEE_OVERCHARGE": {"name": "Contractual Fee Overcharges", "count": 0, "amount": Decimal("0.0000")},
            "DUPLICATE_REFUND": {"name": "Duplicate or Excess Refunds", "count": 0, "amount": Decimal("0.0000")},
        }

        # Check fee overcharges from matches
        fee_matches = db.execute(
            select(ReconciliationMatch).where(
                and_(
                    ReconciliationMatch.tenant_id == tenant_id,
                    ReconciliationMatch.fee_discrepancy > Decimal("0.0000")
                )
            )
        ).scalars().all()
        for fm in fee_matches:
            cat_summaries["FEE_OVERCHARGE"]["count"] += 1
            cat_summaries["FEE_OVERCHARGE"]["amount"] += fm.fee_discrepancy
            leakage_findings_count += 1

        # Check unallocated settlements
        unalloc_setls = db.execute(
            select(CanonicalSettlement).where(
                and_(
                    CanonicalSettlement.tenant_id == tenant_id,
                    CanonicalSettlement.unallocated_balance > Decimal("0.0000")
                )
            )
        ).scalars().all()
        for us in unalloc_setls:
            cat_summaries["UNCREDITED_SETTLEMENT"]["count"] += 1
            cat_summaries["UNCREDITED_SETTLEMENT"]["amount"] += us.unallocated_balance
            leakage_findings_count += 1

        # Check unallocated payments
        unalloc_pays = db.execute(
            select(CanonicalPayment).where(
                and_(
                    CanonicalPayment.tenant_id == tenant_id,
                    CanonicalPayment.unallocated_balance > Decimal("0.0000")
                )
            )
        ).scalars().all()
        for up in unalloc_pays:
            cat_summaries["MISSING_SETTLEMENT"]["count"] += 1
            cat_summaries["MISSING_SETTLEMENT"]["amount"] += up.unallocated_balance
            leakage_findings_count += 1

        # Check refund anomalies
        refunds = db.execute(
            select(CanonicalRefund).where(
                and_(
                    CanonicalRefund.tenant_id == tenant_id,
                    CanonicalRefund.refund_amount > Decimal("0.0000")
                )
            )
        ).scalars().all()
        for rf in refunds:
            cat_summaries["DUPLICATE_REFUND"]["count"] += 1
            cat_summaries["DUPLICATE_REFUND"]["amount"] += rf.refund_amount
            leakage_findings_count += 1

        leakage_by_category = [
            CategoryLeakageSummary(
                category=k,
                display_name=v["name"],
                count=v["count"],
                total_amount=v["amount"]
            )
            for k, v in cat_summaries.items()
        ]

        # Severity breakdown
        high_amt = Decimal("0.0000")
        high_cnt = 0
        med_amt = Decimal("0.0000")
        med_cnt = 0
        low_amt = Decimal("0.0000")
        low_cnt = 0

        for cat in leakage_by_category:
            if cat.category in ("MISSING_SETTLEMENT", "UNCREDITED_SETTLEMENT"):
                high_amt += cat.total_amount
                high_cnt += cat.count
            elif cat.category == "FEE_OVERCHARGE":
                med_amt += cat.total_amount
                med_cnt += cat.count
            else:
                low_amt += cat.total_amount
                low_cnt += cat.count

        leakage_by_severity = [
            SeverityLeakageSummary(severity="HIGH", count=high_cnt, total_amount=high_amt),
            SeverityLeakageSummary(severity="MEDIUM", count=med_cnt, total_amount=med_amt),
            SeverityLeakageSummary(severity="LOW", count=low_cnt, total_amount=low_amt),
        ]

        # 6. Trend data (from historical runs or past 7 days)
        runs_history = db.execute(
            select(ReconciliationRun).where(
                ReconciliationRun.tenant_id == tenant_id
            ).order_by(ReconciliationRun.run_number.asc()).limit(7)
        ).scalars().all()

        trends = []
        for r in runs_history:
            trends.append(
                LeakageTrendItem(
                    date=r.created_at.strftime("%Y-%m-%d"),
                    reconciled_amount=r.total_matched_bank_amount,
                    unmatched_amount=r.total_discrepancy_amount
                )
            )
        if not trends:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            trends.append(
                LeakageTrendItem(
                    date=today_str,
                    reconciled_amount=reconciled_amount,
                    unmatched_amount=unmatched_amount
                )
            )

        return DashboardOverviewResponse(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            currency="INR",
            total_orders_count=total_orders_count,
            total_orders_amount=total_orders_amount,
            total_captured_count=total_captured_count,
            total_captured_amount=total_captured_amount,
            total_settlements_count=total_settlements_count,
            total_settled_amount=total_settled_amount,
            total_bank_credits_count=total_bank_credits_count,
            total_bank_credited_amount=total_bank_credited_amount,
            reconciled_amount=reconciled_amount,
            unmatched_amount=unmatched_amount,
            reconciliation_accuracy_percentage=accuracy_rate,
            total_detected_leakage=total_detected_leakage,
            leakage_findings_count=leakage_findings_count,
            pending_review_count=pending_review_count,
            latest_run_id=latest_run_id,
            latest_run_number=latest_run_number,
            latest_run_status=latest_run_status,
            latest_run_timestamp=latest_run_timestamp,
            flow=flow,
            trends=trends,
            leakage_by_category=leakage_by_category,
            leakage_by_severity=leakage_by_severity,
        )

    @staticmethod
    def get_leakage_findings(db: Session, tenant_id: uuid.UUID) -> LeakageFindingsResponse:
        findings: List[LeakageFindingItem] = []
        high_count = 0
        med_count = 0
        low_count = 0
        total_leakage = Decimal("0.0000")

        # 1. Missing Gateway Settlements
        unalloc_payments = db.execute(
            select(CanonicalPayment).where(
                and_(
                    CanonicalPayment.tenant_id == tenant_id,
                    CanonicalPayment.unallocated_balance > Decimal("0.0000")
                )
            ).order_by(desc(CanonicalPayment.captured_at))
        ).scalars().all()

        for idx, p in enumerate(unalloc_payments, 1):
            finding_id = f"LKG-SETL-{str(idx).zfill(3)}"
            diff = p.unallocated_balance
            total_leakage += diff
            high_count += 1
            findings.append(
                LeakageFindingItem(
                    id=str(p.id),
                    finding_id=finding_id,
                    category="MISSING_SETTLEMENT",
                    title=f"Unsettled Gateway Capture {p.gateway_payment_id}",
                    expected_amount=p.captured_amount,
                    actual_amount=p.captured_amount - diff,
                    difference=diff,
                    severity="HIGH",
                    detection_date=p.captured_at,
                    evidence_references={
                        "payment_id": p.gateway_payment_id,
                        "order_reference": p.order_reference,
                        "payment_method": p.payment_method,
                        "reported_fee": str(p.reported_fee),
                        "reported_tax": str(p.reported_tax),
                    },
                    review_status="PENDING",
                    entity_type="canonical_payments",
                    entity_id=p.id
                )
            )

        # 2. Settlements Not Credited to Bank
        unalloc_settlements = db.execute(
            select(CanonicalSettlement).where(
                and_(
                    CanonicalSettlement.tenant_id == tenant_id,
                    CanonicalSettlement.unallocated_balance > Decimal("0.0000")
                )
            ).order_by(desc(CanonicalSettlement.settled_at))
        ).scalars().all()

        for idx, s in enumerate(unalloc_settlements, 1):
            finding_id = f"LKG-BANK-{str(idx).zfill(3)}"
            diff = s.unallocated_balance
            total_leakage += diff
            high_count += 1
            findings.append(
                LeakageFindingItem(
                    id=str(s.id),
                    finding_id=finding_id,
                    category="UNCREDITED_SETTLEMENT",
                    title=f"Uncredited Settlement Batch {s.settlement_reference}",
                    expected_amount=s.net_settlement_amount,
                    actual_amount=s.net_settlement_amount - diff,
                    difference=diff,
                    severity="HIGH",
                    detection_date=s.settled_at,
                    evidence_references={
                        "settlement_reference": s.settlement_reference,
                        "utr_number": s.utr_number,
                        "gross_amount": str(s.gross_amount),
                        "deductions": str(s.fee_deductions + s.tax_deductions),
                    },
                    review_status="PENDING",
                    entity_type="canonical_settlements",
                    entity_id=s.id
                )
            )

        # 3. Contractual Fee Overcharges from Matches
        fee_matches = db.execute(
            select(ReconciliationMatch).where(
                and_(
                    ReconciliationMatch.tenant_id == tenant_id,
                    ReconciliationMatch.fee_discrepancy > Decimal("0.0000")
                )
            ).order_by(desc(ReconciliationMatch.created_at))
        ).scalars().all()

        for idx, m in enumerate(fee_matches, 1):
            finding_id = f"LKG-FEE-{str(idx).zfill(3)}"
            diff = m.fee_discrepancy
            total_leakage += diff
            med_count += 1
            findings.append(
                LeakageFindingItem(
                    id=str(m.id),
                    finding_id=finding_id,
                    category="FEE_OVERCHARGE",
                    title=f"MDR Tariff Overcharge in Pass {m.pass_number}",
                    expected_amount=m.expected_fee + m.expected_tax,
                    actual_amount=m.expected_fee + m.expected_tax + diff,
                    difference=diff,
                    severity="MEDIUM",
                    detection_date=m.created_at,
                    evidence_references={
                        "match_id": str(m.id),
                        "run_id": str(m.run_id),
                        "explanation": m.explanation,
                        "metadata": m.evidence_metadata or {},
                    },
                    review_status=m.review_status,
                    match_id=m.id,
                    entity_type="reconciliation_matches",
                    entity_id=m.id
                )
            )

        # 4. Duplicate or Excess Refunds
        refunds = db.execute(
            select(CanonicalRefund).where(
                CanonicalRefund.tenant_id == tenant_id
            ).order_by(desc(CanonicalRefund.processed_at))
        ).scalars().all()

        for idx, rf in enumerate(refunds, 1):
            finding_id = f"LKG-REF-{str(idx).zfill(3)}"
            diff = rf.refund_amount
            total_leakage += diff
            low_count += 1
            findings.append(
                LeakageFindingItem(
                    id=str(rf.id),
                    finding_id=finding_id,
                    category="DUPLICATE_OR_EXCESS_REFUND",
                    title=f"Unmatched Gateway Refund {rf.gateway_refund_id}",
                    expected_amount=Decimal("0.0000"),
                    actual_amount=rf.refund_amount,
                    difference=diff,
                    severity="LOW",
                    detection_date=rf.processed_at or rf.created_at,
                    evidence_references={
                        "gateway_refund_id": rf.gateway_refund_id,
                        "payment_id": rf.gateway_payment_id,
                        "order_reference": rf.order_reference,
                    },
                    review_status="PENDING",
                    entity_type="canonical_refunds",
                    entity_id=rf.id
                )
            )

        return LeakageFindingsResponse(
            total_findings=len(findings),
            total_leakage_amount=total_leakage,
            high_severity_count=high_count,
            medium_severity_count=med_count,
            low_severity_count=low_count,
            findings=findings
        )

    @staticmethod
    def get_review_queue(
        db: Session,
        tenant_id: uuid.UUID,
        status_filter: Optional[str] = None
    ) -> ReviewQueueResponse:
        query = select(ReconciliationMatch).where(
            ReconciliationMatch.tenant_id == tenant_id
        )

        if status_filter:
            query = query.where(ReconciliationMatch.review_status == status_filter.upper())
        else:
            query = query.where(
                or_(
                    ReconciliationMatch.review_status == ReviewStatus.PENDING_REVIEW.value,
                    ReconciliationMatch.classification.in_([
                        MatchClassification.AMBIGUOUS_MATCH.value,
                        MatchClassification.UNRESOLVED_SUBSET_BOUND_EXCEEDED.value,
                        MatchClassification.AMBIGUOUS_AGGREGATION_COLLISION.value,
                    ]),
                    ReconciliationMatch.fee_discrepancy > Decimal("0.0000")
                )
            )

        matches = db.execute(query.order_by(desc(ReconciliationMatch.created_at))).scalars().all()

        items: List[ReviewQueueItem] = []
        for m in matches:
            candidates: List[ReviewQueueCandidate] = []
            if m.evidence_metadata and "candidate_scores" in m.evidence_metadata:
                for c in m.evidence_metadata["candidate_scores"]:
                    cand_id = c.get("id") or str(uuid.uuid4())
                    score = Decimal(str(c.get("score", "0.0000")))
                    candidates.append(
                        ReviewQueueCandidate(
                            id=cand_id,
                            reference=c.get("reference", f"Cand-{cand_id[:8]}"),
                            amount=Decimal(str(c.get("amount", "0.0000"))),
                            date=c.get("date"),
                            score=score
                        )
                    )

            run = db.get(ReconciliationRun, m.run_id)
            run_number = run.run_number if run else 1

            items.append(
                ReviewQueueItem(
                    match_id=m.id,
                    run_id=m.run_id,
                    run_number=run_number,
                    match_type=m.match_type,
                    classification=m.classification,
                    pass_number=m.pass_number,
                    confidence_score=m.confidence_score,
                    source_amount=m.source_amount,
                    target_amount=m.target_amount,
                    allocated_amount=m.allocated_amount,
                    discrepancy_amount=m.discrepancy_amount,
                    fee_discrepancy=m.fee_discrepancy,
                    explanation=m.explanation,
                    evidence_metadata=m.evidence_metadata,
                    review_status=m.review_status,
                    reviewed_by_user_id=m.reviewed_by_user_id,
                    reviewed_at=m.reviewed_at,
                    review_action=m.review_action,
                    review_notes=m.review_notes,
                    created_at=m.created_at,
                    candidates=candidates
                )
            )

        return ReviewQueueResponse(
            total_pending=len(items),
            items=items
        )

    @staticmethod
    def get_fee_analytics(db: Session, tenant_id: uuid.UUID) -> FeeAnalyticsResponse:
        contract = db.execute(
            select(FeeContract).where(
                and_(
                    FeeContract.tenant_id == tenant_id,
                    FeeContract.is_active == True
                )
            ).order_by(desc(FeeContract.version))
        ).scalars().first()

        contract_resp = FeeContractResponse.model_validate(contract) if contract else None
        version = contract.version if contract else 1
        gst = contract.gst_rate if contract else Decimal("0.180000")

        # Query payments grouped by instrument or aggregated
        payments = db.execute(
            select(CanonicalPayment).where(
                CanonicalPayment.tenant_id == tenant_id
            )
        ).scalars().all()

        total_gross = Decimal("0.0000")
        total_reported = Decimal("0.0000")
        total_contractual = Decimal("0.0000")
        total_overcharge = Decimal("0.0000")

        instrument_buckets: Dict[str, Dict[str, Any]] = {
            "UPI": {"txs": 0, "gross": Decimal("0.0000"), "reported": Decimal("0.0000"), "expected": Decimal("0.0000")},
            "DEBIT": {"txs": 0, "gross": Decimal("0.0000"), "reported": Decimal("0.0000"), "expected": Decimal("0.0000")},
            "CREDIT_STANDARD": {"txs": 0, "gross": Decimal("0.0000"), "reported": Decimal("0.0000"), "expected": Decimal("0.0000")},
            "CREDIT_CORPORATE": {"txs": 0, "gross": Decimal("0.0000"), "reported": Decimal("0.0000"), "expected": Decimal("0.0000")},
            "NETBANKING": {"txs": 0, "gross": Decimal("0.0000"), "reported": Decimal("0.0000"), "expected": Decimal("0.0000")},
        }

        # Match tiers to rates
        rate_map: Dict[str, Decimal] = {
            "UPI": Decimal("0.000000"),
            "DEBIT": Decimal("0.009000"),
            "CREDIT_STANDARD": Decimal("0.018500"),
            "CREDIT_CORPORATE": Decimal("0.021500"),
            "NETBANKING": Decimal("0.015000"),
        }
        if contract and contract.tiers:
            for t in contract.tiers:
                rate_map[t.instrument_type] = t.percentage_rate

        for p in payments:
            method = p.payment_method.upper() if p.payment_method else "UPI"
            matched_key = "UPI"
            if "DEBIT" in method:
                matched_key = "DEBIT"
            elif "CORP" in method:
                matched_key = "CREDIT_CORPORATE"
            elif "CREDIT" in method or "CARD" in method:
                matched_key = "CREDIT_STANDARD"
            elif "NET" in method or "NB" in method:
                matched_key = "NETBANKING"

            rate = rate_map.get(matched_key, Decimal("0.018500"))
            mdr = (p.captured_amount * rate).quantize(Decimal("0.0001"))
            expected_tax = (mdr * gst).quantize(Decimal("0.0001"))
            exp_total = mdr + expected_tax
            rep_total = p.reported_fee + p.reported_tax

            instrument_buckets[matched_key]["txs"] += 1
            instrument_buckets[matched_key]["gross"] += p.captured_amount
            instrument_buckets[matched_key]["reported"] += rep_total
            instrument_buckets[matched_key]["expected"] += exp_total

            total_gross += p.captured_amount
            total_reported += rep_total
            total_contractual += exp_total
            if rep_total > exp_total + Decimal("0.05"):
                total_overcharge += (rep_total - exp_total)

        tier_analytics: List[FeeInstrumentTierAnalytics] = []
        for k, v in instrument_buckets.items():
            rate = rate_map.get(k, Decimal("0.018500"))
            var = v["reported"] - v["expected"]
            tier_analytics.append(
                FeeInstrumentTierAnalytics(
                    instrument_type=k,
                    percentage_rate=rate,
                    fixed_fee_per_txn=Decimal("0.0000"),
                    transactions_evaluated=v["txs"],
                    gross_volume=v["gross"],
                    actual_gateway_fees=v["reported"],
                    contractual_expected_fees=v["expected"],
                    variance=var
                )
            )

        return FeeAnalyticsResponse(
            active_contract=contract_resp,
            contract_version=version,
            gst_rate=gst,
            total_gross_volume=total_gross,
            total_reported_fees=total_reported,
            total_contractual_fees=total_contractual,
            total_fee_drift=total_reported - total_contractual,
            total_fee_overcharges=total_overcharge,
            tiers=tier_analytics
        )

    @staticmethod
    def get_ai_investigation_status(db: Session, tenant_id: uuid.UUID) -> AIInvestigationStatusResponse:
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        is_configured = bool(gemini_api_key and len(gemini_api_key.strip()) > 5)

        return AIInvestigationStatusResponse(
            provider="GOOGLE_GEMINI",
            status="ACTIVE" if is_configured else "PENDING_CONFIGURATION",
            is_configured=is_configured,
            model_version="gemini-2.0-flash",
            investigations_count=0,
            message=(
                "Gemini 2.0 AI Forensic Engine is active." if is_configured else
                "Google Gemini API integration is currently pending API key provisioning. "
                "AI-assisted forensic dossiers and grounded dispute recovery narratives will activate "
                "automatically once the GEMINI_API_KEY environment variable is configured."
            ),
            recent_investigations=[]
        )

    @staticmethod
    def get_audit_logs(
        db: Session,
        tenant_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0
    ) -> AuditLogsResponse:
        total = db.execute(
            select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant_id)
        ).scalar() or 0

        logs = db.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant_id
            ).order_by(desc(AuditLog.performed_at)).limit(limit).offset(offset)
        ).scalars().all()

        items = []
        for l in logs:
            user_email = None
            if l.user_id:
                u = db.get(User, l.user_id)
                user_email = u.email if u else None

            items.append(
                AuditLogItem(
                    id=l.id,
                    action=l.action,
                    target_entity_type=l.target_entity_type,
                    target_entity_id=l.target_entity_id,
                    user_email=user_email,
                    user_rationale=l.user_rationale,
                    ip_address=l.ip_address,
                    performed_at=l.performed_at
                )
            )

        return AuditLogsResponse(total_logs=total, logs=items)
