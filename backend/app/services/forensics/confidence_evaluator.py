import uuid
from typing import Dict, Any, List, Set, Tuple
from app.models.forensic import InvestigationConclusion, InvestigationConfidence
from app.schemas.forensic import InvestigationResultContract, Hypothesis


class ConfidenceEvaluator:
    """
    Deterministic backend evaluator for forensic investigation confidence and conclusions.
    Enforces strict mathematical and logical boundaries preventing LLM overconfidence or evidence fabrication.
    """

    @classmethod
    def _sanitize_evidence_ids(cls, raw_collection: Any) -> Tuple[List[str], int]:
        """
        Validates incoming evidence-ID collections:
        - Accepts sequences (lists or tuples), preserving first-seen insertion order.
        - Accepts sets or frozensets, normalizing them deterministically via sorted order.
        - Handles None, wrong types, non-string entries, or empty strings gracefully.
        - Deduplicates valid IDs.
        Returns:
            (unique_clean_ids, malformed_or_dropped_count)
        """
        if not isinstance(raw_collection, (list, tuple, set, frozenset)):
            return [], 0

        # Deterministically normalize unordered collections (set / frozenset)
        if isinstance(raw_collection, (set, frozenset)):
            iterable = sorted(
                (item for item in raw_collection if isinstance(item, str)),
                key=str
            ) + [item for item in raw_collection if not isinstance(item, str)]
        else:
            iterable = raw_collection

        unique_ids: List[str] = []
        seen: Set[str] = set()
        malformed_count = 0

        for item in iterable:
            if isinstance(item, str) and item.strip():
                clean_id = item.strip()
                if clean_id not in seen:
                    seen.add(clean_id)
                    unique_ids.append(clean_id)
            else:
                malformed_count += 1

        return unique_ids, malformed_count

    @classmethod
    def evaluate(
        cls,
        raw_result: Dict[str, Any],
        evidence_bundle: Dict[str, Any],
    ) -> Tuple[InvestigationResultContract, InvestigationConclusion, InvestigationConfidence]:
        """
        Validates the LLM output against the verified evidence bundle, removes any fabricated
        evidence IDs, applies deterministic confidence bounding, and computes the final conclusion.
        """
        # 1. Collect valid evidence IDs and their verification status safely
        evidence_items = (
            evidence_bundle.get("evidence_items", [])
            if isinstance(evidence_bundle, dict)
            else []
        )
        if not isinstance(evidence_items, list):
            evidence_items = []

        valid_evidence_ids: Set[str] = set()
        verified_evidence_ids: Set[str] = set()

        for item in evidence_items:
            if isinstance(item, dict) and "evidence_id" in item:
                eid_str = str(item["evidence_id"]).strip()
                if eid_str:
                    valid_evidence_ids.add(eid_str)
                    if item.get("verification_status") == "VERIFIED":
                        verified_evidence_ids.add(eid_str)

        all_evidence_verified = (
            evidence_bundle.get("all_evidence_verified", False)
            if isinstance(evidence_bundle, dict)
            else False
        )

        # 2. Extract and validate hypotheses safely
        raw_hypotheses = raw_result.get("hypotheses") if isinstance(raw_result, dict) else []
        if not isinstance(raw_hypotheses, list):
            raw_hypotheses = []

        validated_hypotheses: List[Hypothesis] = []
        total_supported_evidence_ids: Set[str] = set()
        total_contradicting_evidence_ids: Set[str] = set()

        for idx, h in enumerate(raw_hypotheses):
            if not isinstance(h, dict):
                continue

            h_id = str(h.get("hypothesis_id") or f"H{idx + 1}").strip()
            title = str(h.get("title") or "Root cause hypothesis").strip()
            explanation = str(h.get("explanation") or "").strip()

            # Sanitize and deduplicate supporting evidence IDs
            unique_supporting, dropped_supp_malformed = cls._sanitize_evidence_ids(
                h.get("supporting_evidence_ids")
            )
            valid_supporting = [eid for eid in unique_supporting if eid in verified_evidence_ids]
            discarded_supporting_count = len(unique_supporting) - len(valid_supporting)

            # Sanitize and deduplicate contradicting evidence IDs
            unique_contradicting, dropped_contra_malformed = cls._sanitize_evidence_ids(
                h.get("contradicting_evidence_ids")
            )
            valid_contradicting = [eid for eid in unique_contradicting if eid in verified_evidence_ids]
            discarded_contradicting_count = len(unique_contradicting) - len(valid_contradicting)

            # Extract missing evidence safely
            raw_missing = h.get("missing_evidence")
            missing_ev: List[str] = []
            if isinstance(raw_missing, list):
                for m in raw_missing:
                    if isinstance(m, str) and m.strip():
                        missing_ev.append(m.strip())

            # Audit record for discarded unverified/fabricated supporting evidence IDs
            if discarded_supporting_count > 0:
                missing_ev.append(
                    f"Warning: Discarded {discarded_supporting_count} unverified or fabricated supporting evidence ID(s)."
                )

            # Audit record for discarded unverified/fabricated contradicting evidence IDs
            if discarded_contradicting_count > 0:
                missing_ev.append(
                    f"Warning: Discarded {discarded_contradicting_count} unverified or fabricated contradicting evidence ID(s)."
                )

            # Audit record for malformed non-string citations
            total_malformed = dropped_supp_malformed + dropped_contra_malformed
            if total_malformed > 0:
                missing_ev.append(
                    f"Warning: Discarded {total_malformed} malformed non-string evidence citation(s)."
                )

            total_supported_evidence_ids.update(valid_supporting)
            total_contradicting_evidence_ids.update(valid_contradicting)

            # Deterministic Confidence Assessment per hypothesis (strictly using unique validated IDs)
            h_conf = cls._compute_hypothesis_confidence(
                supporting_count=len(valid_supporting),
                contradicting_count=len(valid_contradicting),
                missing_count=len(missing_ev),
                all_verified=all_evidence_verified
            )

            validated_hypotheses.append(
                Hypothesis(
                    hypothesis_id=h_id,
                    title=title,
                    explanation=explanation,
                    supporting_evidence_ids=valid_supporting,
                    contradicting_evidence_ids=valid_contradicting,
                    missing_evidence=missing_ev,
                    confidence=h_conf,
                )
            )

        # 3. Extract facts, contradictions, and missing info safely
        raw_facts = raw_result.get("verified_facts") if isinstance(raw_result, dict) else []
        verified_facts: List[str] = []
        if isinstance(raw_facts, list):
            for f in raw_facts:
                if isinstance(f, str) and f.strip():
                    verified_facts.append(f.strip())

        raw_contradictions = raw_result.get("contradictions") if isinstance(raw_result, dict) else []
        contradictions: List[str] = []
        if isinstance(raw_contradictions, list):
            for c in raw_contradictions:
                if isinstance(c, str) and c.strip():
                    contradictions.append(c.strip())

        raw_missing_info = raw_result.get("missing_information") if isinstance(raw_result, dict) else []
        missing_info: List[str] = []
        if isinstance(raw_missing_info, list):
            for m in raw_missing_info:
                if isinstance(m, str) and m.strip():
                    missing_info.append(m.strip())

        raw_checks = raw_result.get("recommended_human_checks") if isinstance(raw_result, dict) else []
        recommended_checks: List[str] = []
        if isinstance(raw_checks, list):
            for chk in raw_checks:
                if isinstance(chk, str) and chk.strip():
                    recommended_checks.append(chk.strip())

        # If any verified contradicting evidence was cited in hypotheses, ensure it is recorded in contradictions
        if total_contradicting_evidence_ids and not contradictions:
            contradictions.append(
                f"Contradictory evidence identified in items: {', '.join(sorted(total_contradicting_evidence_ids))}"
            )

        total_verified_supporting_count = len(total_supported_evidence_ids)
        total_verified_contradicting_count = len(total_contradicting_evidence_ids)
        text_contradictions_count = len(contradictions)
        missing_info_count = len(missing_info)

        # 4. Global Deterministic Confidence Evaluation
        overall_confidence = cls._compute_global_confidence(
            total_verified_supporting=total_verified_supporting_count,
            total_verified_contradicting=total_verified_contradicting_count,
            text_contradictions_count=text_contradictions_count,
            missing_info_count=missing_info_count,
            all_evidence_verified=all_evidence_verified,
            total_evidence_items=len(evidence_items)
        )

        # 5. Global Conclusion Determination
        overall_conclusion = cls._compute_global_conclusion(
            total_verified_supporting=total_verified_supporting_count,
            total_verified_contradicting=total_verified_contradicting_count,
            text_contradictions_count=text_contradictions_count,
            missing_info_count=missing_info_count,
            all_evidence_verified=all_evidence_verified,
            total_evidence_items=len(evidence_items),
            overall_confidence=overall_confidence
        )

        raw_summary = raw_result.get("summary") if isinstance(raw_result, dict) else None
        summary = (
            raw_summary.strip()
            if isinstance(raw_summary, str) and raw_summary.strip()
            else "Forensic analysis completed."
        )

        execution_meta = (
            (raw_result.get("_execution_metadata") or raw_result.get("execution_metadata"))
            if isinstance(raw_result, dict)
            else None
        )

        result_contract = InvestigationResultContract(
            summary=summary,
            hypotheses=validated_hypotheses,
            verified_facts=verified_facts,
            contradictions=contradictions,
            missing_information=missing_info,
            recommended_human_checks=recommended_checks,
            execution_metadata=execution_meta if isinstance(execution_meta, dict) else None,
        )

        return result_contract, overall_conclusion, overall_confidence

    @classmethod
    def _compute_hypothesis_confidence(
        cls,
        supporting_count: int,
        contradicting_count: int,
        missing_count: int,
        all_verified: bool
    ) -> InvestigationConfidence:
        if not all_verified or supporting_count == 0 or contradicting_count > 0:
            return InvestigationConfidence.LOW
        if supporting_count >= 3 and missing_count == 0:
            return InvestigationConfidence.HIGH
        if supporting_count >= 2:
            return InvestigationConfidence.MEDIUM
        return InvestigationConfidence.LOW

    @classmethod
    def _compute_global_confidence(
        cls,
        total_verified_supporting: int,
        total_verified_contradicting: int,
        text_contradictions_count: int,
        missing_info_count: int,
        all_evidence_verified: bool,
        total_evidence_items: int
    ) -> InvestigationConfidence:
        # LOW Rule: Unverified evidence, no verified supporting evidence, or contradictions
        if not all_evidence_verified or total_evidence_items == 0 or total_verified_supporting == 0:
            return InvestigationConfidence.LOW
        if total_verified_contradicting > 0 or text_contradictions_count > 0:
            return InvestigationConfidence.LOW
        if total_verified_supporting < 2:
            return InvestigationConfidence.LOW

        # HIGH Rule: >= 3 independent verified sources, zero contradictions, and zero major missing info
        if total_verified_supporting >= 3 and missing_info_count == 0:
            return InvestigationConfidence.HIGH

        # MEDIUM Rule: >= 2 verified sources, no contradictions
        if total_verified_supporting >= 2:
            return InvestigationConfidence.MEDIUM

        return InvestigationConfidence.LOW

    @classmethod
    def _compute_global_conclusion(
        cls,
        total_verified_supporting: int,
        total_verified_contradicting: int,
        text_contradictions_count: int,
        missing_info_count: int,
        all_evidence_verified: bool,
        total_evidence_items: int,
        overall_confidence: InvestigationConfidence
    ) -> InvestigationConclusion:
        # Integrity failure or empty evidence -> INCONCLUSIVE
        if not all_evidence_verified or total_evidence_items == 0 or total_verified_supporting == 0:
            return InvestigationConclusion.INCONCLUSIVE

        # Material contradiction dominates ONLY when backed by verified contradictory evidence IDs
        # Free-form contradiction text alone cannot force CONTRADICTED.
        if total_verified_contradicting > 0 and total_verified_contradicting >= total_verified_supporting:
            return InvestigationConclusion.CONTRADICTED

        # Strong support with HIGH confidence
        if overall_confidence == InvestigationConfidence.HIGH:
            return InvestigationConclusion.SUPPORTED

        # Solid support with MEDIUM confidence
        if overall_confidence == InvestigationConfidence.MEDIUM:
            if missing_info_count > 0 or total_verified_contradicting > 0 or text_contradictions_count > 0:
                return InvestigationConclusion.PARTIALLY_SUPPORTED
            return InvestigationConclusion.SUPPORTED

        # Weak, incomplete, or partially contested evidence
        if total_verified_supporting > 0 and (missing_info_count > 0 or text_contradictions_count > 0 or total_verified_contradicting > 0):
            return InvestigationConclusion.PARTIALLY_SUPPORTED

        return InvestigationConclusion.INCONCLUSIVE
