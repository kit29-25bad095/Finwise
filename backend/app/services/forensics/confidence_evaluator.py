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
    def evaluate(
        cls,
        raw_result: Dict[str, Any],
        evidence_bundle: Dict[str, Any],
    ) -> Tuple[InvestigationResultContract, InvestigationConclusion, InvestigationConfidence]:
        """
        Validates the LLM output against the verified evidence bundle, removes any fabricated
        evidence IDs, applies deterministic confidence bounding, and computes the final conclusion.
        """
        # 1. Collect valid evidence IDs and their verification status
        evidence_items = evidence_bundle.get("evidence_items", [])
        valid_evidence_ids: Set[str] = {item["evidence_id"] for item in evidence_items}
        verified_evidence_ids: Set[str] = {
            item["evidence_id"] for item in evidence_items if item.get("verification_status") == "VERIFIED"
        }
        all_evidence_verified = evidence_bundle.get("all_evidence_verified", False)

        # 2. Extract and validate hypotheses
        raw_hypotheses = raw_result.get("hypotheses", [])
        validated_hypotheses: List[Hypothesis] = []
        total_supported_evidence_ids: Set[str] = set()
        total_contradicting_evidence_ids: Set[str] = set()

        for idx, h in enumerate(raw_hypotheses):
            h_id = h.get("hypothesis_id", f"H{idx + 1}")
            title = h.get("title", "Root cause hypothesis")
            explanation = h.get("explanation", "")

            # Filter cited supporting evidence IDs strictly against known evidence IDs
            raw_supporting = h.get("supporting_evidence_ids", [])
            valid_supporting = [eid for eid in raw_supporting if eid in verified_evidence_ids]
            hallucinated_supporting = [eid for eid in raw_supporting if eid not in valid_evidence_ids]

            # Filter cited contradicting evidence IDs
            raw_contradicting = h.get("contradicting_evidence_ids", [])
            valid_contradicting = [eid for eid in raw_contradicting if eid in verified_evidence_ids]

            missing_ev = list(h.get("missing_evidence", []))
            if hallucinated_supporting:
                missing_ev.append(
                    f"Warning: Discarded {len(hallucinated_supporting)} unverified or fabricated evidence ID(s): "
                    f"{', '.join(hallucinated_supporting[:3])}"
                )

            total_supported_evidence_ids.update(valid_supporting)
            total_contradicting_evidence_ids.update(valid_contradicting)

            # Deterministic Confidence Assessment per hypothesis
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

        # 3. Extract facts, contradictions, and missing info
        verified_facts = list(raw_result.get("verified_facts", []))
        contradictions = list(raw_result.get("contradictions", []))
        missing_info = list(raw_result.get("missing_information", []))
        recommended_checks = list(raw_result.get("recommended_human_checks", []))

        # If any contradicting evidence was cited in hypotheses, ensure it is recorded in contradictions
        if total_contradicting_evidence_ids and not contradictions:
            contradictions.append(
                f"Contradictory evidence identified in items: {', '.join(sorted(total_contradicting_evidence_ids))}"
            )

        # 4. Global Deterministic Confidence Evaluation
        overall_confidence = cls._compute_global_confidence(
            total_verified_supporting=len(total_supported_evidence_ids),
            total_contradictions=len(contradictions) + len(total_contradicting_evidence_ids),
            missing_info_count=len(missing_info),
            all_evidence_verified=all_evidence_verified,
            total_evidence_items=len(evidence_items)
        )

        # 5. Global Conclusion Determination
        overall_conclusion = cls._compute_global_conclusion(
            total_verified_supporting=len(total_supported_evidence_ids),
            total_contradictions=len(contradictions) + len(total_contradicting_evidence_ids),
            missing_info_count=len(missing_info),
            all_evidence_verified=all_evidence_verified,
            total_evidence_items=len(evidence_items),
            overall_confidence=overall_confidence
        )

        result_contract = InvestigationResultContract(
            summary=raw_result.get("summary", "Forensic analysis completed."),
            hypotheses=validated_hypotheses,
            verified_facts=verified_facts,
            contradictions=contradictions,
            missing_information=missing_info,
            recommended_human_checks=recommended_checks,
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
        total_contradictions: int,
        missing_info_count: int,
        all_evidence_verified: bool,
        total_evidence_items: int
    ) -> InvestigationConfidence:
        # LOW Rule: Unverified evidence, no verified supporting evidence, or material contradictions
        if not all_evidence_verified or total_evidence_items == 0 or total_verified_supporting == 0:
            return InvestigationConfidence.LOW
        if total_contradictions > 0:
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
        total_contradictions: int,
        missing_info_count: int,
        all_evidence_verified: bool,
        total_evidence_items: int,
        overall_confidence: InvestigationConfidence
    ) -> InvestigationConclusion:
        # Integrity failure or empty evidence -> INCONCLUSIVE
        if not all_evidence_verified or total_evidence_items == 0 or total_verified_supporting == 0:
            return InvestigationConclusion.INCONCLUSIVE

        # Material contradiction dominates
        if total_contradictions > 0 and total_contradictions >= total_verified_supporting:
            return InvestigationConclusion.CONTRADICTED

        # Strong support with HIGH confidence
        if overall_confidence == InvestigationConfidence.HIGH:
            return InvestigationConclusion.SUPPORTED

        # Solid support with MEDIUM confidence
        if overall_confidence == InvestigationConfidence.MEDIUM:
            if missing_info_count > 0 or total_contradictions > 0:
                return InvestigationConclusion.PARTIALLY_SUPPORTED
            return InvestigationConclusion.SUPPORTED

        # Weak or incomplete evidence
        if total_verified_supporting > 0 and missing_info_count > 0:
            return InvestigationConclusion.PARTIALLY_SUPPORTED

        return InvestigationConclusion.INCONCLUSIVE
