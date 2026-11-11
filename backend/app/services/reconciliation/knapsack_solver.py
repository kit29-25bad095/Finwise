import itertools
from decimal import Decimal
from typing import List, Optional, Tuple, Dict, Any

from app.models.canonical import CanonicalSettlement, CanonicalBankTransaction


class KnapsackResult:
    def __init__(
        self,
        status: str,  # EXACT_SUBSET_FOUND, UNRESOLVED_SUBSET_BOUND_EXCEEDED, AMBIGUOUS_AGGREGATION_COLLISION
        matching_subsets: List[List[CanonicalSettlement]],
        target_amount: Decimal,
        candidate_count: int,
        bound_used: int,
        explanation: str
    ):
        self.status = status
        self.matching_subsets = matching_subsets
        self.target_amount = target_amount
        self.candidate_count = candidate_count
        self.bound_used = bound_used
        self.explanation = explanation


class BoundedKnapsackSolver:
    """
    Pass 5: Controlled Multi-Record Aggregated Allocation (Bounded Subset Sum).
    Guarantees that no match is ever guessed or forced when bounds are exceeded.
    """

    @classmethod
    def find_matching_subsets(
        cls,
        bank_tx: CanonicalBankTransaction,
        candidate_settlements: List[CanonicalSettlement],
        max_bound_n: int = 5,
        fee_tolerance: Decimal = Decimal("0.05")
    ) -> KnapsackResult:
        target_amount = bank_tx.unallocated_balance
        if target_amount <= Decimal("0.0000"):
            return KnapsackResult(
                status="NO_BALANCE_TO_ALLOCATE",
                matching_subsets=[],
                target_amount=target_amount,
                candidate_count=len(candidate_settlements),
                bound_used=max_bound_n,
                explanation="Bank transaction has no remaining unallocated credit balance."
            )

        # Filter candidate settlements with unallocated balance > 0 and <= target_amount + tolerance
        valid_candidates = [
            s for s in candidate_settlements
            if Decimal("0.0000") < s.unallocated_balance <= (target_amount + fee_tolerance)
        ]

        if not valid_candidates:
            return KnapsackResult(
                status="UNRESOLVED_SUBSET_BOUND_EXCEEDED",
                matching_subsets=[],
                target_amount=target_amount,
                candidate_count=0,
                bound_used=max_bound_n,
                explanation=f"No unallocated settlement batches available with amounts <= target ₹{target_amount}."
            )

        matching_subsets: List[List[CanonicalSettlement]] = []
        bound_limit = min(max_bound_n, len(valid_candidates))

        # Search combinations of sizes 2 through bound_limit
        for k in range(2, bound_limit + 1):
            for subset in itertools.combinations(valid_candidates, k):
                subset_sum = sum(s.unallocated_balance for s in subset)
                diff = abs(subset_sum - target_amount)
                if diff <= fee_tolerance:
                    matching_subsets.append(list(subset))

        if len(matching_subsets) == 1:
            matched = matching_subsets[0]
            matched_sum = sum(s.unallocated_balance for s in matched)
            refs = [s.settlement_reference for s in matched]
            return KnapsackResult(
                status="EXACT_SUBSET_FOUND",
                matching_subsets=matching_subsets,
                target_amount=target_amount,
                candidate_count=len(valid_candidates),
                bound_used=bound_limit,
                explanation=(
                    f"Identified unique aggregated subset of {len(matched)} settlement batches "
                    f"({', '.join(refs)}) summing to ₹{matched_sum} matching bank credit ₹{target_amount}."
                )
            )

        elif len(matching_subsets) > 1:
            # Combinatorial Collision: multiple valid subsets sum to target
            return KnapsackResult(
                status="AMBIGUOUS_AGGREGATION_COLLISION",
                matching_subsets=matching_subsets,
                target_amount=target_amount,
                candidate_count=len(valid_candidates),
                bound_used=bound_limit,
                explanation=(
                    f"Combinatorial collision detected: {len(matching_subsets)} distinct settlement subsets "
                    f"sum to target credit ₹{target_amount}. Auto-allocation strictly halted."
                )
            )

        else:
            # No subset found within configured maximum bound N
            return KnapsackResult(
                status="UNRESOLVED_SUBSET_BOUND_EXCEEDED",
                matching_subsets=[],
                target_amount=target_amount,
                candidate_count=len(valid_candidates),
                bound_used=bound_limit,
                explanation=(
                    f"No exact subset combination of settlement batches found within max bound N={bound_limit} "
                    f"for bank credit ₹{target_amount}. Zero speculative allocations created."
                )
            )
