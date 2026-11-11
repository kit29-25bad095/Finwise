import re
from decimal import Decimal
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from app.models.canonical import CanonicalSettlement, CanonicalBankTransaction


class CandidateMatchScore:
    def __init__(
        self,
        bank_tx: CanonicalBankTransaction,
        total_score: Decimal,
        utr_score: Decimal,
        amount_score: Decimal,
        date_score: Decimal,
        narration_score: Decimal,
        explanation: str
    ):
        self.bank_tx = bank_tx
        self.total_score = total_score
        self.utr_score = utr_score
        self.amount_score = amount_score
        self.date_score = date_score
        self.narration_score = narration_score
        self.explanation = explanation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bank_tx_id": str(self.bank_tx.id),
            "bank_reference": self.bank_tx.bank_reference,
            "extracted_utr": self.bank_tx.extracted_utr,
            "credit_amount": str(self.bank_tx.credit_amount),
            "total_score": str(self.total_score),
            "utr_score": str(self.utr_score),
            "amount_score": str(self.amount_score),
            "date_score": str(self.date_score),
            "narration_score": str(self.narration_score),
            "explanation": self.explanation,
        }


class ScoringEngine:
    """
    Multi-Factor Candidate Scoring Engine (Pass 4) with Anti-Collision Guard.
    """
    DEFAULT_W_UTR = Decimal("0.40")
    DEFAULT_W_AMT = Decimal("0.35")
    DEFAULT_W_DATE = Decimal("0.15")
    DEFAULT_W_NARR = Decimal("0.10")

    DEFAULT_MIN_AUTO_MATCH_SCORE = Decimal("0.9000")
    DEFAULT_MIN_COLLISION_DELTA = Decimal("0.1500")

    @classmethod
    def score_candidate(
        cls,
        settlement: CanonicalSettlement,
        bank_tx: CanonicalBankTransaction,
        w_utr: Decimal = DEFAULT_W_UTR,
        w_amt: Decimal = DEFAULT_W_AMT,
        w_date: Decimal = DEFAULT_W_DATE,
        w_narr: Decimal = DEFAULT_W_NARR
    ) -> CandidateMatchScore:
        """
        Calculates normalized multi-factor candidate score between a settlement batch and bank transaction.
        """
        # 1. UTR Score (0.0 to 1.0)
        utr_score = Decimal("0.0")
        s_utr = (settlement.utr_number or "").strip().upper()
        b_utr = (bank_tx.extracted_utr or "").strip().upper()
        b_ref = (bank_tx.bank_reference or "").strip().upper()
        b_narr = (bank_tx.raw_narration or "").strip().upper()

        if s_utr:
            if b_utr and s_utr == b_utr:
                utr_score = Decimal("1.0")
            elif b_ref and s_utr == b_ref:
                utr_score = Decimal("1.0")
            elif s_utr in b_narr:
                utr_score = Decimal("0.95")
            elif len(s_utr) >= 8 and s_utr[-8:] in b_narr:
                # Suffix UTR match (for truncated references)
                utr_score = Decimal("0.80")

        # 2. Amount Score (0.0 to 1.0)
        s_amt = settlement.unallocated_balance
        b_amt = bank_tx.unallocated_balance
        amount_score = Decimal("0.0")
        if s_amt > 0 and b_amt > 0:
            if s_amt == b_amt:
                amount_score = Decimal("1.0")
            else:
                amt_diff = abs(s_amt - b_amt)
                if amt_diff <= Decimal("0.05"):
                    amount_score = Decimal("0.98")
                elif amt_diff <= Decimal("1.00"):
                    amount_score = Decimal("0.85")
                elif amt_diff <= Decimal("10.00"):
                    amount_score = Decimal("0.50")

        # 3. Date Proximity Score (0.0 to 1.0)
        s_date = settlement.settled_at.date() if hasattr(settlement.settled_at, "date") else settlement.settled_at
        b_date = bank_tx.value_date or bank_tx.transaction_date
        date_score = Decimal("0.0")

        days_diff = (b_date - s_date).days
        # Indian settlement clearing normally happens within [0, +3] business days
        if days_diff == 0:
            date_score = Decimal("1.0")
        elif days_diff == 1:
            date_score = Decimal("0.95")
        elif days_diff == 2:
            date_score = Decimal("0.85")
        elif days_diff == 3:
            date_score = Decimal("0.70")
        elif days_diff == 4:
            date_score = Decimal("0.50")
        elif -1 <= days_diff < 0:
            # Banking timestamp slightly precedes gateway batch finalize
            date_score = Decimal("0.80")
        else:
            date_score = Decimal("0.20") if abs(days_diff) <= 7 else Decimal("0.0")

        # 4. Narration Token Overlap Score (0.0 to 1.0)
        narration_score = Decimal("0.0")
        keywords = ["RAZORPAY", "NODAL", "CMS", "SETTLEMENT", "SETL", "RZP"]
        matched_keywords = sum(1 for kw in keywords if kw in b_narr)
        if matched_keywords >= 2:
            narration_score = Decimal("1.0")
        elif matched_keywords == 1:
            narration_score = Decimal("0.70")

        # Check if settlement reference appears in narration
        s_ref = (settlement.settlement_reference or "").strip().upper()
        if s_ref and s_ref in b_narr:
            narration_score = Decimal("1.0")

        total_score = (
            (w_utr * utr_score) +
            (w_amt * amount_score) +
            (w_date * date_score) +
            (w_narr * narration_score)
        ).quantize(Decimal("0.0001"))

        explanation = (
            f"Multi-factor score: {total_score} "
            f"(UTR={utr_score}, Amount={amount_score}, Date={date_score}, Narration={narration_score})"
        )

        return CandidateMatchScore(
            bank_tx=bank_tx,
            total_score=total_score,
            utr_score=utr_score,
            amount_score=amount_score,
            date_score=date_score,
            narration_score=narration_score,
            explanation=explanation
        )

    @classmethod
    def evaluate_candidates(
        cls,
        settlement: CanonicalSettlement,
        candidates: List[CanonicalBankTransaction],
        min_auto_match_score: Decimal = DEFAULT_MIN_AUTO_MATCH_SCORE,
        min_collision_delta: Decimal = DEFAULT_MIN_COLLISION_DELTA
    ) -> Tuple[Optional[CandidateMatchScore], List[CandidateMatchScore], bool]:
        """
        Ranks candidates and applies the Anti-Collision Thresholding Rule:
        AutoMatch(S_j, C_1) <==> Score(S_j, C_1) >= min_auto_match_score AND
                                 (Score(S_j, C_1) - Score(S_j, C_2) >= min_collision_delta)

        Returns: (top_match, all_candidate_scores, is_ambiguous_collision)
        """
        if not candidates:
            return (None, [], False)

        scores: List[CandidateMatchScore] = []
        for b_tx in candidates:
            cand_score = cls.score_candidate(settlement, b_tx)
            scores.append(cand_score)

        # Sort descending by total score
        scores.sort(key=lambda s: s.total_score, reverse=True)

        top = scores[0]
        if len(scores) == 1:
            if top.total_score >= min_auto_match_score:
                return (top, scores, False)
            else:
                return (top if top.total_score >= Decimal("0.60") else None, scores, True)

        second = scores[1]
        score_delta = top.total_score - second.total_score

        # Check anti-collision condition
        if top.total_score >= min_auto_match_score and score_delta >= min_collision_delta:
            return (top, scores, False)

        # Ambiguous collision detected
        return (top, scores, True)
