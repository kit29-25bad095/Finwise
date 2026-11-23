import os
import json
import uuid
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from app.core.config import settings
from app.services.forensics.llm_adapter import (
    GeminiLLMAdapter,
    MockLLMAdapter,
    get_llm_adapter,
)
from app.services.forensics.exceptions import LLMProviderError
from app.services.forensics.confidence_evaluator import ConfidenceEvaluator
from app.services.forensics.prompt_builder import ForensicPromptBuilder
from app.services.dashboard_service import DashboardService
from app.models.forensic import InvestigationConclusion, InvestigationConfidence
from google.genai.errors import APIError, ClientError


# ==============================================================================
# Unit & Contract Tests: Google Gemini LLM Adapter
# ==============================================================================

@pytest.mark.asyncio
async def test_gemini_missing_api_key_raises_pending_configuration():
    """
    When GEMINI_API_KEY is not configured, the adapter must raise an explicit
    LLMProviderError indicating PENDING_CONFIGURATION status.
    """
    adapter = GeminiLLMAdapter(api_key=None)
    assert not adapter.is_configured
    assert adapter.provider_name == "gemini"

    with pytest.raises(LLMProviderError) as exc_info:
        await adapter.generate_investigation(
            system_prompt="Test system instructions",
            user_prompt="Test user evidence bundle",
        )
    assert "PENDING_CONFIGURATION" in str(exc_info.value)
    assert "Set GEMINI_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_invalid_api_key_fails_fast_without_retries():
    """
    When the Gemini API returns a 400/401/403 ClientError (e.g. invalid API key),
    the adapter must fail immediately without wasting time on exponential backoff retries.
    """
    adapter = GeminiLLMAdapter(api_key="AIzaSyFakeInvalidKeyForTestingOnly12345678", max_retries=3)

    mock_client = MagicMock()
    mock_client_error = ClientError(
        code=400,
        response_json={"error": {"message": "API_KEY_INVALID", "status": "INVALID_ARGUMENT"}}
    )
    mock_client.aio.models.generate_content = AsyncMock(side_effect=mock_client_error)

    with patch("google.genai.Client", return_value=mock_client):
        with pytest.raises(LLMProviderError) as exc_info:
            await adapter.generate_investigation(
                system_prompt="Test system",
                user_prompt="Test user prompt",
            )

        # Must fail on the first attempt without exhausting 3 retries
        assert mock_client.aio.models.generate_content.call_count == 1
        assert "Invalid or expired API key" in str(exc_info.value) or "Gemini API client error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_rate_limit_retry_and_recovery():
    """
    When Gemini API responds with HTTP 429 / RESOURCE_EXHAUSTED, the adapter
    must catch the rate limit, perform exponential backoff, and succeed if subsequent attempt passes.
    """
    adapter = GeminiLLMAdapter(
        api_key="AIzaSyValidFormatKeyForTestingMockOnly12345",
        max_retries=3,
        timeout_seconds=5.0
    )

    mock_client = MagicMock()
    mock_rate_limit_error = APIError(
        code=429,
        response_json={"error": {"message": "Resource has been exhausted (quota exceeded)", "status": "RESOURCE_EXHAUSTED"}}
    )

    success_payload = {
        "summary": "Forensic analysis of fee drift.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "MDR Fee Surcharge",
                "explanation": "Calculated rate drifted from schedule.",
                "supporting_evidence_ids": ["ev-001"],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
                "confidence": "HIGH"
            }
        ],
        "verified_facts": ["MDR drift observed"],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": ["Check gateway tariff table"]
    }
    mock_success_response = MagicMock()
    mock_success_response.text = f"```json\n{json.dumps(success_payload)}\n```"

    # Attempt 1 fails with 429, Attempt 2 succeeds
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[mock_rate_limit_error, mock_success_response]
    )

    with patch("google.genai.Client", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await adapter.generate_investigation(
            system_prompt="Test system",
            user_prompt="Test user prompt",
        )

        assert mock_client.aio.models.generate_content.call_count == 2
        assert mock_sleep.call_count == 1
        assert res["summary"] == "Forensic analysis of fee drift."
        assert len(res["hypotheses"]) == 1


@pytest.mark.asyncio
async def test_gemini_timeout_handling_and_exhaustion():
    """
    When API calls exceed the timeout threshold across all retry attempts,
    the adapter must raise LLMProviderError citing timeout exhaustion.
    """
    adapter = GeminiLLMAdapter(
        api_key="AIzaSyValidFormatKeyForTestingMockOnly12345",
        max_retries=2,
        timeout_seconds=0.01  # Extremely short timeout to force timeout
    )

    mock_client = MagicMock()
    # Simulate a slow network call that hangs
    async def slow_call(*args, **kwargs):
        await asyncio.sleep(1.0)
        return MagicMock(text="{}")

    mock_client.aio.models.generate_content = AsyncMock(side_effect=slow_call)

    with patch("google.genai.Client", return_value=mock_client):
        with pytest.raises(LLMProviderError) as exc_info:
            await adapter.generate_investigation(
                system_prompt="Test system",
                user_prompt="Test user prompt",
            )

        assert "timed out after" in str(exc_info.value) or "failed after 2 attempts" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_successful_response_parsing():
    """
    Verifies that markdown-wrapped JSON or text-wrapped JSON from Gemini 2.0
    is cleanly parsed into a Python dictionary.
    """
    adapter = GeminiLLMAdapter(
        api_key="AIzaSyValidFormatKeyForTestingMockOnly12345",
        model_name="gemini-2.0-flash"
    )

    raw_json = {
        "summary": "Discrepancy caused by delayed T+2 settlement.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Settlement Delay",
                "explanation": "Settlement was delayed over public holiday weekend.",
                "supporting_evidence_ids": ["ev-101", "ev-102"],
                "contradicting_evidence_ids": [],
                "missing_evidence": [],
                "confidence": "HIGH"
            }
        ],
        "verified_facts": ["Bank closed on Sunday."],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": ["Verify bank settlement schedule"]
    }

    mock_client = MagicMock()
    mock_resp = MagicMock()
    # Emulate real Gemini markdown block with preamble
    mock_resp.text = f"Here is the investigation:\n```json\n{json.dumps(raw_json)}\n```\nHope this helps!"
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        result = await adapter.generate_investigation("sys", "usr")
        assert result["summary"] == "Discrepancy caused by delayed T+2 settlement."
        assert len(result["hypotheses"]) == 1
        assert result["hypotheses"][0]["supporting_evidence_ids"] == ["ev-101", "ev-102"]


# ==============================================================================
# Security & Forensic Integrity Guardrail Tests
# ==============================================================================

def test_gemini_prompt_guardrails_enforce_read_only_and_zero_calculation():
    """
    Ensures that ForensicPromptBuilder strictly contains non-negotiable security guardrails:
    1. Read-only passive external data (no command execution)
    2. Zero calculation / recalculation rule
    3. Zero fabrication rule
    4. Advisory only (no auto-approval / no reconciliation action)
    """
    sys_prompt = ForensicPromptBuilder.get_system_prompt()
    assert "READ-ONLY PASSIVE DATA RULE" in sys_prompt
    assert "ZERO CALCULATION RULE" in sys_prompt
    assert "ZERO FABRICATION RULE" in sys_prompt
    assert "ADVISORY ONLY" in sys_prompt
    assert "You have NO authority to resolve exceptions" in sys_prompt


def test_gemini_ungrounded_output_evidence_filtering():
    """
    Tests anti-hallucination defense:
    If Gemini hallucinates evidence IDs not present in the verified bundle,
    ConfidenceEvaluator strips the hallucinated IDs, flags a warning,
    and down-weights confidence to prevent false positive disputes.
    """
    evidence_bundle = {
        "all_evidence_verified": True,
        "evidence_items": [
            {"evidence_id": "ev-real-001", "verification_status": "VERIFIED"},
            {"evidence_id": "ev-real-002", "verification_status": "VERIFIED"}
        ]
    }

    raw_gemini_output = {
        "summary": "Forensic test summary.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "title": "Suspected Overcharge",
                "explanation": "Calculated discrepancy against tariff.",
                # Mix of 1 real evidence ID and 2 fabricated IDs
                "supporting_evidence_ids": ["ev-real-001", "ev-hallucinated-999", "ev-fake-888"],
                "contradicting_evidence_ids": ["ev-ghost-000"],
                "missing_evidence": []
            }
        ],
        "verified_facts": ["Empirical test fact"],
        "contradictions": [],
        "missing_information": [],
        "recommended_human_checks": ["Review tariff schedule"]
    }

    result, conclusion, confidence = ConfidenceEvaluator.evaluate(
        raw_result=raw_gemini_output,
        evidence_bundle=evidence_bundle
    )

    hypo = result.hypotheses[0]
    # Fabricated IDs MUST be stripped
    assert "ev-hallucinated-999" not in hypo.supporting_evidence_ids
    assert "ev-fake-888" not in hypo.supporting_evidence_ids
    assert "ev-ghost-000" not in hypo.contradicting_evidence_ids
    assert hypo.supporting_evidence_ids == ["ev-real-001"]

    # Warning must be added to missing_evidence
    warning_found = any("Discarded 2 unverified or fabricated" in item for item in hypo.missing_evidence)
    assert warning_found


def test_dashboard_ai_status_pending_configuration_when_no_key(db_session, monkeypatch):
    """
    Tests that the dashboard API service correctly returns PENDING_CONFIGURATION
    status when GEMINI_API_KEY is not configured.
    """
    tenant_id = uuid.uuid4()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "AI_API_KEY", None)

    status_res = DashboardService.get_ai_investigation_status(db_session, tenant_id)
    assert status_res.status == "PENDING_CONFIGURATION"
    assert not status_res.is_configured
    assert status_res.provider == "GOOGLE_GEMINI"
    assert "pending API key provisioning" in status_res.message


def test_dashboard_ai_status_active_when_key_configured(db_session, monkeypatch):
    """
    Tests that the dashboard API service correctly returns ACTIVE status
    when GEMINI_API_KEY is configured.
    """
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "AIzaSyValidFormatKey12345")
    status_res = DashboardService.get_ai_investigation_status(db_session, tenant_id)
    assert status_res.status == "ACTIVE"
    assert status_res.is_configured
    assert status_res.provider == "GOOGLE_GEMINI"


# ==============================================================================
# Live End-to-End Gemini Integration Test (Executed ONLY when key is present)
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY") and not os.getenv("AI_API_KEY"),
    reason="Live Google Gemini API test requires live GEMINI_API_KEY or AI_API_KEY in environment."
)
async def test_live_gemini_api_connectivity():
    """
    REAL LIVE INTEGRATION TEST:
    Executes a real call to Google Gemini 2.0 API using the official google-genai SDK.
    Runs only when GEMINI_API_KEY is actively provided in the environment.
    """
    live_key = os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY")
    adapter = GeminiLLMAdapter(api_key=live_key, model_name="gemini-2.0-flash")

    system_prompt = ForensicPromptBuilder.get_system_prompt()
    test_bundle = {
        "exception_id": "test-live-exc-001",
        "detector_type": "FEE_OVERCHARGE",
        "all_evidence_verified": True,
        "evidence_items": [
            {
                "evidence_id": "ev-test-live-01",
                "evidence_type": "SETTLEMENT_RECORD",
                "details": {
                    "reported_fee": "25.0000",
                    "expected_fee": "20.0000",
                    "difference": "5.0000"
                },
                "verification_status": "VERIFIED"
            }
        ]
    }
    user_prompt = ForensicPromptBuilder.build_user_prompt(test_bundle)

    res = await adapter.generate_investigation(
        system_prompt=system_prompt,
        user_prompt=user_prompt
    )

    assert "summary" in res
    assert "hypotheses" in res
    assert isinstance(res["hypotheses"], list)
    assert len(res["hypotheses"]) >= 1
    assert adapter.provider_name == "gemini"
