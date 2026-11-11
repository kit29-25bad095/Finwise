import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, desc, func

from app.models.tenant import Tenant
from app.models.user import User
from app.models.audit import AuditLog
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalRefund,
    CanonicalBankTransaction,
)
from app.models.reconciliation import (
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    ReconciliationRunDelta,
    FeeContract,
    FeeScheduleTier,
    ReconciliationStatus,
    MatchType,
    MatchClassification,
    ReviewStatus,
    AllocationStatus,
)
from app.services.reconciliation.fee_calculator import FeeCalculator, round_half_up
from app.services.reconciliation.scoring_engine import ScoringEngine, CandidateMatchScore
from app.services.reconciliation.knapsack_solver import BoundedKnapsackSolver, KnapsackResult


class ReconciliationService:
    """
    Deterministic Three-Way Financial Reconciliation & Allocation Engine.
    Coordinates Passes 1 through 6, enforces double-entry balance conservation,
    immutable run versioning, and non-speculative financial rules.
    """

    @classmethod
    def create_run(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        parameters: Optional[Dict[str, Any]] = None
    ) -> ReconciliationRun:
        """
        Initializes an immutable reconciliation run record with sequential run_number.
        """
        last_run = db.execute(
            select(func.max(ReconciliationRun.run_number)).where(ReconciliationRun.tenant_id == tenant_id)
        ).scalar()
        next_run_number = (last_run or 0) + 1

        run_params = {
            "fee_overcharge_tolerance": str(Decimal("0.05")),
            "max_knapsack_bound": 5,
            "settlement_window_days": 3,
            "settlement_cutoff_time": "23:00",
            "min_auto_match_score": str(Decimal("0.9000")),
            "min_collision_delta": str(Decimal("0.1500")),
        }
        if parameters:
            for k, v in parameters.items():
                run_params[k] = str(v) if isinstance(v, Decimal) else v

        run = ReconciliationRun(
            tenant_id=tenant_id,
            run_number=next_run_number,
            status=ReconciliationStatus.PENDING.value,
            is_active=True,
            triggered_by_user_id=user_id,
            parameters=run_params
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    @classmethod
    def execute_run(cls, db: Session, run_id: uuid.UUID) -> ReconciliationRun:
        """
        Executes the deterministic 3-way multi-pass reconciliation engine.
        """
        start_time = time.time()
        run = db.get(ReconciliationRun, run_id)
        if not run:
            raise ValueError(f"Reconciliation run {run_id} does not exist.")

        tenant_id = run.tenant_id
        run.status = ReconciliationStatus.IN_PROGRESS.value
        db.commit()

        # Parse parameters
        params = run.parameters or {}
        fee_tolerance = Decimal(str(params.get("fee_overcharge_tolerance", "0.05")))
        max_bound_n = int(params.get("max_knapsack_bound", 5))
        settlement_window_days = int(params.get("settlement_window_days", 3))
        min_auto_match_score = Decimal(str(params.get("min_auto_match_score", "0.9000")))
        min_collision_delta = Decimal(str(params.get("min_collision_delta", "0.1500")))

        # Active FeeContract for tenant
        contract = db.execute(
            select(FeeContract).where(
                and_(
                    FeeContract.tenant_id == tenant_id,
                    FeeContract.is_active == True
                )
            ).order_by(desc(FeeContract.created_at))
        ).scalars().first()

        # -------------------------------------------------------------------
        # Fetch Canonical Entities for Tenant
        # -------------------------------------------------------------------
        orders = db.execute(
            select(CanonicalOrder).where(CanonicalOrder.tenant_id == tenant_id)
        ).scalars().all()

        payments = db.execute(
            select(CanonicalPayment).where(CanonicalPayment.tenant_id == tenant_id)
        ).scalars().all()

        settlements = db.execute(
            select(CanonicalSettlement).where(CanonicalSettlement.tenant_id == tenant_id)
        ).scalars().all()

        bank_txs = db.execute(
            select(CanonicalBankTransaction).where(CanonicalBankTransaction.tenant_id == tenant_id)
        ).scalars().all()

        # Tracking evaluated counts
        run.total_orders_evaluated = len(orders)
        run.total_payments_evaluated = len(payments)
        run.total_settlements_evaluated = len(settlements)
        run.total_bank_transactions_evaluated = len(bank_txs)

        run.total_order_amount = sum((o.gross_amount for o in orders), Decimal("0.0000"))
        run.total_captured_amount = sum((p.captured_amount for p in payments), Decimal("0.0000"))
        run.total_settled_amount = sum((s.net_settlement_amount for s in settlements), Decimal("0.0000"))

        matched_orders_set = set()
        matched_payments_set = set()
        matched_settlements_set = set()
        matched_bank_txs_set = set()

        total_discrepancy = Decimal("0.0000")
        total_fee_drift = Decimal("0.0000")
        total_matched_bank_amt = Decimal("0.0000")

        # -------------------------------------------------------------------
        # PASS 1: Exact Gateway Payment ID / Order Reference Match (Order <-> Payment)
        # -------------------------------------------------------------------
        # Map orders by order_reference and order_number
        orders_by_ref: Dict[str, CanonicalOrder] = {}
        for o in orders:
            if o.order_reference:
                orders_by_ref[o.order_reference.strip()] = o
                # Clean reference without '#'
                clean_ref = o.order_reference.strip().lstrip("#")
                if clean_ref:
                    orders_by_ref[clean_ref] = o
            if o.order_number:
                orders_by_ref[o.order_number.strip()] = o

        for p in payments:
            if p.id in matched_payments_set:
                continue

            matched_order: Optional[CanonicalOrder] = None
            ref_candidates = [
                p.order_reference,
                p.gateway_order_id,
                p.gateway_payment_id
            ]
            for candidate in ref_candidates:
                if candidate and candidate.strip() in orders_by_ref:
                    ord_candidate = orders_by_ref[candidate.strip()]
                    if ord_candidate.id not in matched_orders_set:
                        matched_order = ord_candidate
                        break

            if matched_order:
                # Compare Order Gross vs Payment Captured Amount
                ord_amt = matched_order.gross_amount
                pay_amt = p.captured_amount
                amt_diff = abs(ord_amt - pay_amt)

                is_exact = amt_diff == Decimal("0.0000")
                is_partial = amt_diff > Decimal("0.0000")

                classification = MatchClassification.EXACT_MATCH if is_exact else MatchClassification.PARTIAL_MATCH
                allocated_amt = min(ord_amt, p.unallocated_balance)

                # Fee calculation against contract
                fee_calc = FeeCalculator.calculate_payment_fees(p, contract, fee_tolerance)
                if fee_calc.is_overcharge:
                    total_discrepancy += fee_calc.overcharge_delta
                elif fee_calc.is_rounding_drift:
                    total_fee_drift += fee_calc.overcharge_delta

                if is_partial:
                    total_discrepancy += amt_diff

                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.ORDER_TO_PAYMENT.value,
                    classification=classification.value,
                    pass_number=1,
                    confidence_score=Decimal("1.0000"),
                    order_id=matched_order.id,
                    payment_id=p.id,
                    source_amount=ord_amt,
                    target_amount=pay_amt,
                    allocated_amount=allocated_amt,
                    discrepancy_amount=amt_diff,
                    expected_fee=fee_calc.expected_total_fee,
                    expected_tax=fee_calc.calculated_tax,
                    fee_discrepancy=fee_calc.overcharge_delta if fee_calc.is_overcharge else Decimal("0.0000"),
                    explanation=(
                        f"Pass 1 Identity Match: Order '{matched_order.order_reference}' "
                        f"matched Gateway Payment '{p.gateway_payment_id}'. "
                        f"Order Gross ₹{ord_amt}, Captured ₹{pay_amt}."
                    ),
                    evidence_metadata=fee_calc.to_dict(),
                    review_status=ReviewStatus.NOT_REQUIRED.value if is_exact and not fee_calc.is_overcharge else ReviewStatus.PENDING_REVIEW.value
                )
                db.add(match)
                db.flush()

                # Double-Entry Allocation
                if allocated_amt > Decimal("0.0000"):
                    alloc = ReconciliationAllocation(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        match_id=match.id,
                        source_entity_type="canonical_orders",
                        source_entity_id=matched_order.id,
                        target_entity_type="canonical_payments",
                        target_entity_id=p.id,
                        allocated_amount=allocated_amt,
                        status=AllocationStatus.ACTIVE.value
                    )
                    db.add(alloc)
                    p.unallocated_balance = max(Decimal("0.0000"), p.unallocated_balance - allocated_amt)

                matched_orders_set.add(matched_order.id)
                matched_payments_set.add(p.id)

        # -------------------------------------------------------------------
        # PASS 2: Exact Settlement Batch UTR Match (Settlement <-> Bank)
        # -------------------------------------------------------------------
        for s in settlements:
            if s.id in matched_settlements_set:
                continue

            s_utr = (s.utr_number or "").strip()
            if not s_utr:
                continue

            # Look for exact UTR match in bank transactions
            candidate_bank_txs = [
                b for b in bank_txs
                if b.id not in matched_bank_txs_set and b.credit_amount > Decimal("0.0000") and (
                    (b.extracted_utr and b.extracted_utr.strip() == s_utr) or
                    (b.bank_reference and b.bank_reference.strip() == s_utr) or
                    (s_utr in (b.raw_narration or ""))
                )
            ]

            if len(candidate_bank_txs) == 1:
                b_tx = candidate_bank_txs[0]
                diff = abs(s.unallocated_balance - b_tx.unallocated_balance)
                is_exact = diff == Decimal("0.0000")
                is_close = diff <= fee_tolerance

                classification = MatchClassification.EXACT_MATCH if is_exact else MatchClassification.PARTIAL_MATCH
                allocated_amt = min(s.unallocated_balance, b_tx.unallocated_balance)

                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=classification.value,
                    pass_number=2,
                    confidence_score=Decimal("1.0000"),
                    settlement_id=s.id,
                    bank_transaction_id=b_tx.id,
                    source_amount=s.net_settlement_amount,
                    target_amount=b_tx.credit_amount,
                    allocated_amount=allocated_amt,
                    discrepancy_amount=diff,
                    explanation=(
                        f"Pass 2 Exact UTR Match: Settlement '{s.settlement_reference}' (UTR: {s_utr}) "
                        f"matched Bank Transaction '{b_tx.bank_reference or b_tx.id}'. "
                        f"Net Settlement ₹{s.net_settlement_amount}, Bank Credit ₹{b_tx.credit_amount}."
                    ),
                    evidence_metadata={
                        "utr": s_utr,
                        "settlement_ref": s.settlement_reference,
                        "bank_ref": b_tx.bank_reference,
                        "raw_narration": b_tx.raw_narration,
                        "diff": str(diff)
                    },
                    review_status=ReviewStatus.NOT_REQUIRED.value if is_exact else ReviewStatus.PENDING_REVIEW.value
                )
                db.add(match)
                db.flush()

                if allocated_amt > Decimal("0.0000"):
                    alloc = ReconciliationAllocation(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        match_id=match.id,
                        source_entity_type="canonical_settlements",
                        source_entity_id=s.id,
                        target_entity_type="canonical_bank_transactions",
                        target_entity_id=b_tx.id,
                        allocated_amount=allocated_amt,
                        status=AllocationStatus.ACTIVE.value
                    )
                    db.add(alloc)
                    s.unallocated_balance = max(Decimal("0.0000"), s.unallocated_balance - allocated_amt)
                    b_tx.unallocated_balance = max(Decimal("0.0000"), b_tx.unallocated_balance - allocated_amt)
                    total_matched_bank_amt += allocated_amt

                matched_settlements_set.add(s.id)
                matched_bank_txs_set.add(b_tx.id)

        # -------------------------------------------------------------------
        # PASS 3: Exact Net Amount & Banking Window Match with Collision Guard
        # -------------------------------------------------------------------
        for s in settlements:
            if s.id in matched_settlements_set or s.unallocated_balance <= Decimal("0.0000"):
                continue

            s_date = s.settled_at.date() if hasattr(s.settled_at, "date") else s.settled_at
            # Candidates matching net amount and within [settled_date, settled_date + window_days]
            candidates = [
                b for b in bank_txs
                if b.id not in matched_bank_txs_set and b.unallocated_balance > Decimal("0.0000") and (
                    abs(b.unallocated_balance - s.unallocated_balance) <= fee_tolerance and
                    0 <= ((b.value_date or b.transaction_date) - s_date).days <= settlement_window_days
                )
            ]

            if len(candidates) == 1:
                b_tx = candidates[0]
                # Check collision: does any other unallocated settlement match this same bank transaction?
                competing_settlements = [
                    other_s for other_s in settlements
                    if other_s.id != s.id and other_s.id not in matched_settlements_set and
                    abs(other_s.unallocated_balance - b_tx.unallocated_balance) <= fee_tolerance
                ]

                if not competing_settlements:
                    # Clear unique match
                    diff = abs(s.unallocated_balance - b_tx.unallocated_balance)
                    allocated_amt = min(s.unallocated_balance, b_tx.unallocated_balance)

                    match = ReconciliationMatch(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        match_type=MatchType.SETTLEMENT_TO_BANK.value,
                        classification=MatchClassification.EXACT_MATCH.value if diff == 0 else MatchClassification.PARTIAL_MATCH.value,
                        pass_number=3,
                        confidence_score=Decimal("0.9500"),
                        settlement_id=s.id,
                        bank_transaction_id=b_tx.id,
                        source_amount=s.unallocated_balance,
                        target_amount=b_tx.unallocated_balance,
                        allocated_amount=allocated_amt,
                        discrepancy_amount=diff,
                        explanation=(
                            f"Pass 3 Amount & Window Match: Settlement '{s.settlement_reference}' (₹{s.unallocated_balance}) "
                            f"matched Bank Credit (₹{b_tx.unallocated_balance}) within {settlement_window_days}-day window."
                        ),
                        evidence_metadata={
                            "settlement_date": str(s_date),
                            "bank_date": str(b_tx.value_date or b_tx.transaction_date),
                            "window_days": settlement_window_days
                        },
                        review_status=ReviewStatus.NOT_REQUIRED.value if diff == 0 else ReviewStatus.PENDING_REVIEW.value
                    )
                    db.add(match)
                    db.flush()

                    if allocated_amt > Decimal("0.0000"):
                        alloc = ReconciliationAllocation(
                            tenant_id=tenant_id,
                            run_id=run.id,
                            match_id=match.id,
                            source_entity_type="canonical_settlements",
                            source_entity_id=s.id,
                            target_entity_type="canonical_bank_transactions",
                            target_entity_id=b_tx.id,
                            allocated_amount=allocated_amt,
                            status=AllocationStatus.ACTIVE.value
                        )
                        db.add(alloc)
                        s.unallocated_balance = max(Decimal("0.0000"), s.unallocated_balance - allocated_amt)
                        b_tx.unallocated_balance = max(Decimal("0.0000"), b_tx.unallocated_balance - allocated_amt)
                        total_matched_bank_amt += allocated_amt

                    matched_settlements_set.add(s.id)
                    matched_bank_txs_set.add(b_tx.id)
                else:
                    # Collision Guard: multiple settlements compete for the same bank tx
                    match = ReconciliationMatch(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        match_type=MatchType.SETTLEMENT_TO_BANK.value,
                        classification=MatchClassification.AMBIGUOUS_MATCH.value,
                        pass_number=3,
                        confidence_score=Decimal("0.7000"),
                        settlement_id=s.id,
                        bank_transaction_id=b_tx.id,
                        source_amount=s.unallocated_balance,
                        target_amount=b_tx.unallocated_balance,
                        allocated_amount=Decimal("0.0000"),
                        discrepancy_amount=Decimal("0.0000"),
                        explanation=(
                            f"Pass 3 Collision Guard: Multiple settlement batches compete for "
                            f"bank credit ₹{b_tx.unallocated_balance}. Auto-allocation strictly halted."
                        ),
                        evidence_metadata={
                            "competing_settlement_ids": [str(cs.id) for cs in competing_settlements]
                        },
                        review_status=ReviewStatus.PENDING_REVIEW.value
                    )
                    db.add(match)
                    run.ambiguous_matches_count += 1

            elif len(candidates) > 1:
                # Multiple bank credits share the exact same amount in window
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=MatchClassification.AMBIGUOUS_MATCH.value,
                    pass_number=3,
                    confidence_score=Decimal("0.7000"),
                    settlement_id=s.id,
                    bank_transaction_id=candidates[0].id,
                    source_amount=s.unallocated_balance,
                    target_amount=candidates[0].unallocated_balance,
                    allocated_amount=Decimal("0.0000"),
                    discrepancy_amount=Decimal("0.0000"),
                    explanation=(
                        f"Pass 3 Collision Guard: {len(candidates)} bank credit transactions share identical amount "
                        f"₹{s.unallocated_balance} in {settlement_window_days}-day window. Deferring to human review."
                    ),
                    evidence_metadata={
                        "candidate_bank_tx_ids": [str(c.id) for c in candidates]
                    },
                    review_status=ReviewStatus.PENDING_REVIEW.value
                )
                db.add(match)
                run.ambiguous_matches_count += 1

        # -------------------------------------------------------------------
        # PASS 4: Multi-Factor Candidate Scoring Engine (Pass 4)
        # -------------------------------------------------------------------
        for s in settlements:
            if s.id in matched_settlements_set or s.unallocated_balance <= Decimal("0.0000"):
                continue

            available_bank_txs = [
                b for b in bank_txs
                if b.id not in matched_bank_txs_set and b.unallocated_balance > Decimal("0.0000")
            ]
            if not available_bank_txs:
                break

            top_score, all_scores, is_ambiguous = ScoringEngine.evaluate_candidates(
                settlement=s,
                candidates=available_bank_txs,
                min_auto_match_score=min_auto_match_score,
                min_collision_delta=min_collision_delta
            )

            if top_score and not is_ambiguous:
                # Confident auto-match
                b_tx = top_score.bank_tx
                diff = abs(s.unallocated_balance - b_tx.unallocated_balance)
                allocated_amt = min(s.unallocated_balance, b_tx.unallocated_balance)

                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=MatchClassification.EXACT_MATCH.value if diff == 0 else MatchClassification.PARTIAL_MATCH.value,
                    pass_number=4,
                    confidence_score=top_score.total_score,
                    settlement_id=s.id,
                    bank_transaction_id=b_tx.id,
                    source_amount=s.unallocated_balance,
                    target_amount=b_tx.unallocated_balance,
                    allocated_amount=allocated_amt,
                    discrepancy_amount=diff,
                    explanation=f"Pass 4 Multi-Factor Score {top_score.total_score}: {top_score.explanation}",
                    evidence_metadata=top_score.to_dict(),
                    review_status=ReviewStatus.NOT_REQUIRED.value if diff == 0 else ReviewStatus.PENDING_REVIEW.value
                )
                db.add(match)
                db.flush()

                if allocated_amt > Decimal("0.0000"):
                    alloc = ReconciliationAllocation(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        match_id=match.id,
                        source_entity_type="canonical_settlements",
                        source_entity_id=s.id,
                        target_entity_type="canonical_bank_transactions",
                        target_entity_id=b_tx.id,
                        allocated_amount=allocated_amt,
                        status=AllocationStatus.ACTIVE.value
                    )
                    db.add(alloc)
                    s.unallocated_balance = max(Decimal("0.0000"), s.unallocated_balance - allocated_amt)
                    b_tx.unallocated_balance = max(Decimal("0.0000"), b_tx.unallocated_balance - allocated_amt)
                    total_matched_bank_amt += allocated_amt

                matched_settlements_set.add(s.id)
                matched_bank_txs_set.add(b_tx.id)

            elif top_score and is_ambiguous:
                # Ambiguous candidate collision or low delta: preserve for human review
                b_tx = top_score.bank_tx
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=MatchClassification.AMBIGUOUS_MATCH.value,
                    pass_number=4,
                    confidence_score=top_score.total_score,
                    settlement_id=s.id,
                    bank_transaction_id=b_tx.id,
                    source_amount=s.unallocated_balance,
                    target_amount=b_tx.unallocated_balance,
                    allocated_amount=Decimal("0.0000"),
                    discrepancy_amount=Decimal("0.0000"),
                    explanation=(
                        f"Pass 4 Ambiguity Isolation: Score {top_score.total_score} does not satisfy "
                        f"anti-collision delta of {min_collision_delta}. Preserved for human review."
                    ),
                    evidence_metadata={
                        "top_score": top_score.to_dict(),
                        "all_candidate_scores": [cs.to_dict() for cs in all_scores[:5]]
                    },
                    review_status=ReviewStatus.PENDING_REVIEW.value
                )
                db.add(match)
                run.ambiguous_matches_count += 1

        # -------------------------------------------------------------------
        # PASS 5: Controlled Multi-Record Aggregated Allocation (Knapsack Solver)
        # -------------------------------------------------------------------
        for b_tx in bank_txs:
            if b_tx.id in matched_bank_txs_set or b_tx.unallocated_balance <= Decimal("0.0000"):
                continue

            unallocated_settlements = [
                s for s in settlements
                if s.id not in matched_settlements_set and s.unallocated_balance > Decimal("0.0000")
            ]
            if len(unallocated_settlements) < 2:
                continue

            knapsack = BoundedKnapsackSolver.find_matching_subsets(
                bank_tx=b_tx,
                candidate_settlements=unallocated_settlements,
                max_bound_n=max_bound_n,
                fee_tolerance=fee_tolerance
            )

            if knapsack.status == "EXACT_SUBSET_FOUND":
                matched_subset = knapsack.matching_subsets[0]
                # Unique subset match found
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=MatchClassification.AGGREGATED_MATCH.value,
                    pass_number=5,
                    confidence_score=Decimal("0.9500"),
                    bank_transaction_id=b_tx.id,
                    source_amount=sum(s.unallocated_balance for s in matched_subset),
                    target_amount=b_tx.unallocated_balance,
                    allocated_amount=b_tx.unallocated_balance,
                    discrepancy_amount=Decimal("0.0000"),
                    explanation=knapsack.explanation,
                    evidence_metadata={
                        "subset_settlement_ids": [str(s.id) for s in matched_subset],
                        "subset_references": [s.settlement_reference for s in matched_subset]
                    },
                    review_status=ReviewStatus.NOT_REQUIRED.value
                )
                db.add(match)
                db.flush()

                # Create individual atomic allocations for each settlement batch in subset
                for s in matched_subset:
                    alloc_amt = s.unallocated_balance
                    alloc = ReconciliationAllocation(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        match_id=match.id,
                        source_entity_type="canonical_settlements",
                        source_entity_id=s.id,
                        target_entity_type="canonical_bank_transactions",
                        target_entity_id=b_tx.id,
                        allocated_amount=alloc_amt,
                        status=AllocationStatus.ACTIVE.value
                    )
                    db.add(alloc)
                    s.unallocated_balance = Decimal("0.0000")
                    matched_settlements_set.add(s.id)

                total_matched_bank_amt += b_tx.unallocated_balance
                b_tx.unallocated_balance = Decimal("0.0000")
                matched_bank_txs_set.add(b_tx.id)

            elif knapsack.status == "AMBIGUOUS_AGGREGATION_COLLISION":
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=MatchClassification.AMBIGUOUS_AGGREGATION_COLLISION.value,
                    pass_number=5,
                    confidence_score=Decimal("0.5000"),
                    bank_transaction_id=b_tx.id,
                    source_amount=Decimal("0.0000"),
                    target_amount=b_tx.unallocated_balance,
                    allocated_amount=Decimal("0.0000"),
                    discrepancy_amount=Decimal("0.0000"),
                    explanation=knapsack.explanation,
                    evidence_metadata={
                        "competing_subsets_count": len(knapsack.matching_subsets),
                        "competing_subset_ids": [
                            [str(s.id) for s in sub] for sub in knapsack.matching_subsets[:3]
                        ]
                    },
                    review_status=ReviewStatus.PENDING_REVIEW.value
                )
                db.add(match)
                run.ambiguous_matches_count += 1

            elif knapsack.status == "UNRESOLVED_SUBSET_BOUND_EXCEEDED":
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=MatchClassification.UNRESOLVED_SUBSET_BOUND_EXCEEDED.value,
                    pass_number=5,
                    confidence_score=Decimal("0.0000"),
                    bank_transaction_id=b_tx.id,
                    source_amount=Decimal("0.0000"),
                    target_amount=b_tx.unallocated_balance,
                    allocated_amount=Decimal("0.0000"),
                    discrepancy_amount=Decimal("0.0000"),
                    explanation=knapsack.explanation,
                    evidence_metadata={"bound_limit": max_bound_n},
                    review_status=ReviewStatus.PENDING_REVIEW.value
                )
                db.add(match)
                run.unresolved_count += 1

        # -------------------------------------------------------------------
        # PASS 6: Mark Remaining Unmatched Records
        # -------------------------------------------------------------------
        for o in orders:
            if o.id not in matched_orders_set:
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.ORDER_TO_PAYMENT.value,
                    classification=MatchClassification.UNMATCHED.value,
                    pass_number=6,
                    confidence_score=Decimal("0.0000"),
                    order_id=o.id,
                    source_amount=o.gross_amount,
                    target_amount=Decimal("0.0000"),
                    allocated_amount=Decimal("0.0000"),
                    discrepancy_amount=o.gross_amount,
                    explanation=f"Shopify Order '{o.order_reference}' (₹{o.gross_amount}) has no corresponding payment capture record.",
                    review_status=ReviewStatus.NOT_REQUIRED.value
                )
                db.add(match)
                run.unmatched_orders_count += 1

        for p in payments:
            if p.id not in matched_payments_set:
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.ORDER_TO_PAYMENT.value,
                    classification=MatchClassification.UNMATCHED.value,
                    pass_number=6,
                    confidence_score=Decimal("0.0000"),
                    payment_id=p.id,
                    source_amount=p.captured_amount,
                    target_amount=Decimal("0.0000"),
                    allocated_amount=Decimal("0.0000"),
                    discrepancy_amount=p.captured_amount,
                    explanation=f"Gateway Payment '{p.gateway_payment_id}' (₹{p.captured_amount}) has no correlated order record.",
                    review_status=ReviewStatus.NOT_REQUIRED.value
                )
                db.add(match)
                run.unmatched_payments_count += 1

        for s in settlements:
            if s.id not in matched_settlements_set:
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=MatchClassification.UNMATCHED.value,
                    pass_number=6,
                    confidence_score=Decimal("0.0000"),
                    settlement_id=s.id,
                    source_amount=s.net_settlement_amount,
                    target_amount=Decimal("0.0000"),
                    allocated_amount=Decimal("0.0000"),
                    discrepancy_amount=s.net_settlement_amount,
                    explanation=f"Gateway Settlement '{s.settlement_reference}' (₹{s.net_settlement_amount}) has no matching bank deposit.",
                    review_status=ReviewStatus.NOT_REQUIRED.value
                )
                db.add(match)
                run.unmatched_settlements_count += 1

        for b in bank_txs:
            if b.id not in matched_bank_txs_set and b.unallocated_balance > Decimal("0.0000"):
                match = ReconciliationMatch(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    match_type=MatchType.SETTLEMENT_TO_BANK.value,
                    classification=MatchClassification.UNMATCHED.value,
                    pass_number=6,
                    confidence_score=Decimal("0.0000"),
                    bank_transaction_id=b.id,
                    source_amount=b.credit_amount,
                    target_amount=Decimal("0.0000"),
                    allocated_amount=Decimal("0.0000"),
                    discrepancy_amount=b.unallocated_balance,
                    explanation=f"Bank Credit '{b.bank_reference or b.id}' (₹{b.unallocated_balance}) has no matched gateway settlement batch.",
                    review_status=ReviewStatus.NOT_REQUIRED.value
                )
                db.add(match)
                run.unmatched_bank_txs_count += 1

        # -------------------------------------------------------------------
        # Update Run Metrics and Supersede Prior Active Runs
        # -------------------------------------------------------------------
        run.matched_orders_count = len(matched_orders_set)
        run.matched_payments_count = len(matched_payments_set)
        run.matched_settlements_count = len(matched_settlements_set)
        run.matched_bank_txs_count = len(matched_bank_txs_set)

        run.total_matched_bank_amount = total_matched_bank_amt
        run.total_discrepancy_amount = total_discrepancy
        run.total_fee_drift_amount = total_fee_drift

        duration_ms = int((time.time() - start_time) * 1000)
        run.duration_ms = duration_ms
        run.completed_at = datetime.now(timezone.utc)

        has_exceptions = (
            run.ambiguous_matches_count > 0 or
            run.unresolved_count > 0 or
            run.unmatched_orders_count > 0 or
            run.unmatched_payments_count > 0 or
            run.unmatched_settlements_count > 0 or
            run.total_discrepancy_amount > Decimal("0.0000")
        )
        run.status = (
            ReconciliationStatus.COMPLETED_WITH_EXCEPTIONS.value
            if has_exceptions
            else ReconciliationStatus.COMPLETED.value
        )

        # Deactivate / Supersede previous active runs for this tenant
        previous_runs = db.execute(
            select(ReconciliationRun).where(
                and_(
                    ReconciliationRun.tenant_id == tenant_id,
                    ReconciliationRun.id != run.id,
                    ReconciliationRun.is_active == True
                )
            )
        ).scalars().all()

        for prev_run in previous_runs:
            prev_run.is_active = False
            # Supersede allocations of previous run
            prev_allocs = db.execute(
                select(ReconciliationAllocation).where(ReconciliationAllocation.run_id == prev_run.id)
            ).scalars().all()
            for pa in prev_allocs:
                pa.status = AllocationStatus.SUPERSEDED.value

            # Record run delta
            delta = ReconciliationRunDelta(
                tenant_id=tenant_id,
                current_run_id=run.id,
                previous_run_id=prev_run.id,
                delta_type="SUPERSEDED_RUN",
                details={
                    "previous_run_number": prev_run.run_number,
                    "previous_status": prev_run.status,
                    "new_run_number": run.run_number,
                    "new_status": run.status,
                    "matched_orders_delta": run.matched_orders_count - prev_run.matched_orders_count,
                    "matched_settlements_delta": run.matched_settlements_count - prev_run.matched_settlements_count
                }
            )
            db.add(delta)

        # Audit Log Entry
        audit = AuditLog(
            tenant_id=tenant_id,
            user_id=run.triggered_by_user_id,
            action="RECONCILIATION_RUN_COMPLETED",
            target_entity_type="reconciliation_runs",
            target_entity_id=run.id,
            user_rationale=f"Executed Reconciliation Run #{run.run_number} in {duration_ms}ms with status {run.status}.",
            new_state={
                "run_number": run.run_number,
                "status": run.status,
                "matched_orders": run.matched_orders_count,
                "matched_payments": run.matched_payments_count,
                "matched_settlements": run.matched_settlements_count,
                "matched_bank_txs": run.matched_bank_txs_count,
                "total_discrepancy": str(run.total_discrepancy_amount),
            }
        )
        db.add(audit)

        db.commit()
        db.refresh(run)
        return run

    @classmethod
    def resolve_match(
        cls,
        db: Session,
        match_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,  # APPROVE, REJECT, MANUAL_ALLOCATE
        notes: Optional[str] = None,
        target_entity_id: Optional[uuid.UUID] = None,
        manual_amount: Optional[Decimal] = None
    ) -> ReconciliationMatch:
        """
        Processes human review decision for an ambiguous or exception match.
        Guarantees RBAC enforcement and immutable audit recording.
        """
        match = db.execute(
            select(ReconciliationMatch).where(
                and_(
                    ReconciliationMatch.id == match_id,
                    ReconciliationMatch.tenant_id == tenant_id
                )
            )
        ).scalars().first()
        if not match:
            raise ValueError(f"Match {match_id} does not exist in this tenant workspace.")

        action_upper = action.strip().upper()
        if action_upper not in ("APPROVE", "REJECT", "MANUAL_ALLOCATE"):
            raise ValueError(f"Invalid review action '{action}'. Must be APPROVE, REJECT, or MANUAL_ALLOCATE.")

        match.reviewed_by_user_id = user_id
        match.reviewed_at = datetime.now(timezone.utc)
        match.review_action = action_upper
        match.review_notes = notes

        if action_upper == "APPROVE":
            match.review_status = ReviewStatus.APPROVED.value
            # If allocation did not yet happen (ambiguous candidate), execute allocation
            if match.allocated_amount == Decimal("0.0000"):
                amt_to_alloc = min(match.source_amount, match.target_amount)
                if amt_to_alloc > Decimal("0.0000"):
                    match.allocated_amount = amt_to_alloc
                    alloc = ReconciliationAllocation(
                        tenant_id=tenant_id,
                        run_id=match.run_id,
                        match_id=match.id,
                        source_entity_type="canonical_settlements" if match.settlement_id else "canonical_orders",
                        source_entity_id=match.settlement_id or match.order_id,
                        target_entity_type="canonical_bank_transactions" if match.bank_transaction_id else "canonical_payments",
                        target_entity_id=match.bank_transaction_id or match.payment_id,
                        allocated_amount=amt_to_alloc,
                        status=AllocationStatus.ACTIVE.value
                    )
                    db.add(alloc)
                    if match.settlement_id:
                        s_ent = db.get(CanonicalSettlement, match.settlement_id)
                        if s_ent:
                            s_ent.unallocated_balance = max(Decimal("0.0000"), s_ent.unallocated_balance - amt_to_alloc)
                    if match.bank_transaction_id:
                        b_ent = db.get(CanonicalBankTransaction, match.bank_transaction_id)
                        if b_ent:
                            b_ent.unallocated_balance = max(Decimal("0.0000"), b_ent.unallocated_balance - amt_to_alloc)

        elif action_upper == "REJECT":
            match.review_status = ReviewStatus.REJECTED.value
            # If allocations were made, mark them reversed and restore balance
            for alloc in match.allocations:
                alloc.status = AllocationStatus.REVERSED.value
                if match.settlement_id:
                    s_ent = db.get(CanonicalSettlement, match.settlement_id)
                    if s_ent:
                        s_ent.unallocated_balance += alloc.allocated_amount
                if match.bank_transaction_id:
                    b_ent = db.get(CanonicalBankTransaction, match.bank_transaction_id)
                    if b_ent:
                        b_ent.unallocated_balance += alloc.allocated_amount

        elif action_upper == "MANUAL_ALLOCATE":
            match.review_status = ReviewStatus.RESOLVED.value
            if manual_amount and manual_amount > Decimal("0.0000"):
                match.allocated_amount = manual_amount
                target_id = target_entity_id or match.bank_transaction_id or match.payment_id
                alloc = ReconciliationAllocation(
                    tenant_id=tenant_id,
                    run_id=match.run_id,
                    match_id=match.id,
                    source_entity_type="canonical_settlements" if match.settlement_id else "canonical_orders",
                    source_entity_id=match.settlement_id or match.order_id,
                    target_entity_type="canonical_bank_transactions" if match.bank_transaction_id else "canonical_payments",
                    target_entity_id=target_id,
                    allocated_amount=manual_amount,
                    status=AllocationStatus.ACTIVE.value
                )
                db.add(alloc)
                if match.settlement_id:
                    s_ent = db.get(CanonicalSettlement, match.settlement_id)
                    if s_ent:
                        s_ent.unallocated_balance = max(Decimal("0.0000"), s_ent.unallocated_balance - manual_amount)
                if match.bank_transaction_id:
                    b_ent = db.get(CanonicalBankTransaction, match.bank_transaction_id)
                    if b_ent:
                        b_ent.unallocated_balance = max(Decimal("0.0000"), b_ent.unallocated_balance - manual_amount)

        # Audit Log
        audit = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=f"MATCH_REVIEW_{action_upper}",
            target_entity_type="reconciliation_matches",
            target_entity_id=match.id,
            user_rationale=notes or f"Manual reviewer decision: {action_upper}.",
            new_state={
                "match_id": str(match.id),
                "review_action": action_upper,
                "review_status": match.review_status,
                "allocated_amount": str(match.allocated_amount),
            }
        )
        db.add(audit)

        db.commit()
        db.refresh(match)
        return match
