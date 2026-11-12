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
