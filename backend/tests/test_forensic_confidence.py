import pytest
from app.services.forensics.confidence_evaluator import ConfidenceEvaluator
from app.models.forensic import InvestigationConclusion, InvestigationConfidence


def test_confidence_evaluator_high_confidence_supported():
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-1", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-2", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-3", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Full corroboration found across payment, settlement, and bank records.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Uncredited Settlement",
                "explanation": "Settlement occurred but bank failed to post credit.",
                "supporting_evidence_ids": ["ev-1", "ev-2", "ev-3"],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
                "confidence": "HIGH"
            }
        ],
        "verified_facts": ["Payment settled", "UTR reference present in gateway batch"],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    assert conclusion == InvestigationConclusion.SUPPORTED
    assert confidence == InvestigationConfidence.HIGH
    assert len(contract.hypotheses[0].supporting_evidence_ids) == 3


def test_confidence_evaluator_partially_supported():
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-1", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-2", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Partial evidence available.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Missing Settlement",
                "explanation": "Payment captured, no settlement batch found.",
                "supporting_evidence_ids": ["ev-1", "ev-2"],
                "contradicting_evidence_ids": [],
                "missing_evidence": ["Missing next-day gateway statement"],
                "confidence": "HIGH"  # LLM overconfidently claims HIGH
            }
        ],
        "verified_facts": ["Payment captured on 2026-11-01"],
        "contradictions": [],
        "missing_information": ["Need next-day settlement statement"],
        "recommended_human_checks": ["Check gateway portal"]
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    # Backend overrides LLM's self-assigned HIGH confidence down to MEDIUM because of missing evidence
    assert conclusion == InvestigationConclusion.PARTIALLY_SUPPORTED
    assert confidence == InvestigationConfidence.MEDIUM


def test_confidence_evaluator_contradicted_evidence():
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-1", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-2", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Evidence contains direct contradiction.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Refund Anomaly",
                "explanation": "Refund record conflicts with settlement reversal.",
                "supporting_evidence_ids": ["ev-1"],
                "contradicting_evidence_ids": ["ev-2"],
                "missing_evidence": [],
                "confidence": "LOW"
            }
        ],
        "verified_facts": [],
        "contradictions": ["Settlement report indicates refund was already reversed in batch B-12"],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    assert conclusion == InvestigationConclusion.CONTRADICTED
    assert confidence == InvestigationConfidence.LOW


def test_confidence_evaluator_discards_hallucinated_evidence_ids():
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "real-ev-1", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Analysis citing made-up evidence IDs.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Fee Overcharge",
                "explanation": "Fee exceeds contracted tier.",
                "supporting_evidence_ids": ["real-ev-1", "fake-ev-999", "invented-ev-888"],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
                "confidence": "HIGH"
            }
        ],
        "verified_facts": [],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    # Hallucinated IDs are discarded
    assert contract.hypotheses[0].supporting_evidence_ids == ["real-ev-1"]
    # Warning placed in missing evidence
    assert any("Discarded" in m for m in contract.hypotheses[0].missing_evidence)
    # With only 1 real verified evidence item, confidence must be LOW
    assert confidence == InvestigationConfidence.LOW


def test_confidence_evaluator_blocks_on_tampered_evidence():
    evidence_bundle = {
        "all_evidence_verified": False,  # Tampered evidence!
        "evidence_items": [
            {"evidence_id": "ev-1", "verification_status": "TAMPERED"},
        ]
    }
    raw_llm_result = {
        "summary": "Analysis.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Title",
                "explanation": "Exp",
                "supporting_evidence_ids": ["ev-1"],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
                "confidence": "HIGH"
            }
        ],
        "verified_facts": [],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    assert conclusion == InvestigationConclusion.INCONCLUSIVE
    assert confidence == InvestigationConfidence.LOW


def test_repeated_evidence_id_cannot_inflate_confidence():
    """
    1. Three repetitions of one valid evidence ID cannot produce HIGH confidence.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-single", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Adversarial/hallucinated repetition of single evidence item.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Inflated Confidence Attempt",
                "explanation": "Citing ev-single three times to mimic 3 independent corroborating records.",
                "supporting_evidence_ids": ["ev-single", "ev-single", "ev-single"],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
                "confidence": "HIGH"
            }
        ],
        "verified_facts": [],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    # Must be deduplicated to exactly 1 ID
    assert contract.hypotheses[0].supporting_evidence_ids == ["ev-single"]
    # Hypothesis confidence cannot be HIGH with only 1 unique evidence item
    assert contract.hypotheses[0].confidence == InvestigationConfidence.LOW
    assert confidence == InvestigationConfidence.LOW


def test_null_evidence_id_lists_do_not_crash_evaluation():
    """
    2. Null supporting and contradicting ID lists do not crash evaluation.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-1", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Result with explicit null collections.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Null collection test",
                "explanation": "Model returned null for lists.",
                "supporting_evidence_ids": None,
                "contradicting_evidence_ids": None,
                "missing_evidence": None,
            }
        ],
        "verified_facts": None,
        "contradictions": None,
        "missing_information": None,
        "recommended_human_checks": None,
        "execution_metadata": None,
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    assert contract.hypotheses[0].supporting_evidence_ids == []
    assert contract.hypotheses[0].contradicting_evidence_ids == []
    assert contract.hypotheses[0].missing_evidence == []
    assert contract.verified_facts == []
    assert contract.contradictions == []
    assert conclusion == InvestigationConclusion.INCONCLUSIVE
    assert confidence == InvestigationConfidence.LOW


def test_malformed_evidence_id_entries_handled_safely():
    """
    3. Malformed list entries and non-list values are handled safely.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-valid", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Result with malformed types.",
        "hypotheses": [
            "malformed_hypothesis_entry_is_string",
            {
                "hypothesis_id": "H1",
                "title": "Malformed entries test",
                "explanation": "Mixed valid and invalid types in arrays.",
                "supporting_evidence_ids": [12345, None, {}, "", "   ", "ev-valid", True],
                "contradicting_evidence_ids": "not-a-list-string",
                "missing_evidence": [None, 999, "Valid missing record note"],
            }
        ],
        "verified_facts": [None, 123, "Legitimate fact string"],
        "contradictions": "unexpected-string-not-list",
        "missing_information": 42,
        "recommended_human_checks": [None, "Check settlement log"],
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    # Valid string was extracted, all malformed non-strings dropped
    assert contract.hypotheses[0].supporting_evidence_ids == ["ev-valid"]
    assert contract.hypotheses[0].contradicting_evidence_ids == []
    # Audit trail indicates dropped malformed entries
    assert any("malformed" in m for m in contract.hypotheses[0].missing_evidence)
    assert contract.verified_facts == ["Legitimate fact string"]
    assert contract.contradictions == []
    assert contract.missing_information == []
    assert contract.recommended_human_checks == ["Check settlement log"]


def test_fabricated_supporting_ids_discarded_and_audited():
    """
    4. Fabricated supporting IDs are discarded and recorded.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-real", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Hypothesis citing fake supporting IDs.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Fabrication test",
                "explanation": "Citing fake-1 and fake-2.",
                "supporting_evidence_ids": ["ev-real", "fake-supporting-1", "fake-supporting-2"],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
            }
        ],
        "verified_facts": [],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    assert contract.hypotheses[0].supporting_evidence_ids == ["ev-real"]
    assert any("Discarded 2 unverified or fabricated supporting" in m for m in contract.hypotheses[0].missing_evidence)
    # Untrusted strings are NOT echoed in the audit message
    assert "fake-supporting-1" not in str(contract.hypotheses[0].missing_evidence)


def test_fabricated_contradicting_ids_discarded_and_audited():
    """
    5. Fabricated contradicting IDs are discarded and recorded.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-real", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Hypothesis citing fake contradicting IDs.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Fabricated Contradiction Test",
                "explanation": "Citing fake-contra-999.",
                "supporting_evidence_ids": ["ev-real"],
                "contradicting_evidence_ids": ["fake-contra-999"],
                "missing_evidence": [],
            }
        ],
        "verified_facts": [],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    assert contract.hypotheses[0].contradicting_evidence_ids == []
    assert any("Discarded 1 unverified or fabricated contradicting" in m for m in contract.hypotheses[0].missing_evidence)
    # Untrusted strings are NOT echoed in the audit message
    assert "fake-contra-999" not in str(contract.hypotheses[0].missing_evidence)


def test_fabricated_contradictions_cannot_change_conclusion():
    """
    6. Fabricated contradictions cannot change the conclusion.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-1", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-2", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-3", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Attempt to force CONTRADICTED conclusion via fabricated contradicting IDs.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Attempted Contradiction Override",
                "explanation": "Fabricating contradictory evidence IDs.",
                "supporting_evidence_ids": ["ev-1", "ev-2", "ev-3"],
                "contradicting_evidence_ids": ["fabricated-c1", "fabricated-c2", "fabricated-c3"],
                "missing_evidence": [],
            }
        ],
        "verified_facts": [],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    # All fabricated contradicting IDs discarded
    assert contract.hypotheses[0].contradicting_evidence_ids == []
    assert contract.contradictions == []
    # Conclusion cannot be forced to CONTRADICTED by fake contradiction IDs
    assert conclusion != InvestigationConclusion.CONTRADICTED
    assert conclusion in (InvestigationConclusion.SUPPORTED, InvestigationConclusion.PARTIALLY_SUPPORTED)


def test_free_form_contradiction_without_verified_id_cannot_cause_contradicted():
    """
    One verified supporting evidence ID plus a free-form contradiction statement,
    with no verified contradictory ID, must NOT produce CONTRADICTED.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-single-supporting", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "LLM claims contradiction in text but cites no verified contradictory evidence ID.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Unsubstantiated Contradiction",
                "explanation": "Stating that payment was reversed on bank portal.",
                "supporting_evidence_ids": ["ev-single-supporting"],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
            }
        ],
        "verified_facts": [],
        "contradictions": ["Free-form text: Bank portal indicates settlement reversed"],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    # Conclusion must NOT be CONTRADICTED because there are zero verified contradictory evidence IDs
    assert conclusion != InvestigationConclusion.CONTRADICTED
    assert conclusion == InvestigationConclusion.PARTIALLY_SUPPORTED
    # Free-form contradiction string remains available in contract as an advisory note
    assert contract.contradictions == ["Free-form text: Bank portal indicates settlement reversed"]


def test_verified_contradictory_evidence_id_produces_contradicted():
    """
    A valid verified contradictory evidence ID must still influence the conclusion
    according to existing policy.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-supp-1", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-contra-1", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Real verified contradictory record exists.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Substantiated Contradiction",
                "explanation": "Contradictory settlement reversal record confirmed.",
                "supporting_evidence_ids": ["ev-supp-1"],
                "contradicting_evidence_ids": ["ev-contra-1"],
                "missing_evidence": [],
            }
        ],
        "verified_facts": [],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    # Verified contradictory evidence ID produces CONTRADICTED
    assert conclusion == InvestigationConclusion.CONTRADICTED
    assert confidence == InvestigationConfidence.LOW
    assert contract.hypotheses[0].contradicting_evidence_ids == ["ev-contra-1"]


def test_duplicate_and_fabricated_contradictions_cannot_change_conclusion():
    """
    Fabricated and duplicate contradictory IDs cannot change the conclusion.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-1", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-2", "verification_status": "VERIFIED"},
        ]
    }
    raw_llm_result = {
        "summary": "Adversarial duplicate and fabricated contradictory IDs.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Adversarial Contradiction Attempt",
                "explanation": "Repeating fabricated IDs.",
                "supporting_evidence_ids": ["ev-1", "ev-2"],
                "contradicting_evidence_ids": [
                    "fake-c1", "fake-c1", "fake-c1",  # Duplicates of fabricated ID
                    "non-existent-c2"
                ],
                "missing_evidence": [],
            }
        ],
        "verified_facts": [],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": []
    }

    contract, conclusion, confidence = ConfidenceEvaluator.evaluate(raw_llm_result, evidence_bundle)

    assert contract.hypotheses[0].contradicting_evidence_ids == []
    assert conclusion != InvestigationConclusion.CONTRADICTED
    assert conclusion in (InvestigationConclusion.SUPPORTED, InvestigationConclusion.PARTIALLY_SUPPORTED)


def test_set_input_handled_deterministically():
    """
    Unordered set input is normalized deterministically via alphanumeric sort.
    """
    raw_set = {"ev-zebra", "ev-apple", "ev-mango"}
    unique_ids, malformed = ConfidenceEvaluator._sanitize_evidence_ids(raw_set)

    # Must be deterministically sorted
    assert unique_ids == ["ev-apple", "ev-mango", "ev-zebra"]
    assert malformed == 0
