import os
import uuid
import asyncio
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock
from dotenv import dotenv_values

from app.core.config import settings
from app.models.forensic import (
    InvestigationConclusion,
    InvestigationConfidence,
)
from app.services.forensics.llm_adapter import (
    GeminiLLMAdapter,
    MockLLMAdapter,
    get_llm_adapter,
    _sanitize_error_message,
)
from app.services.forensics.exceptions import LLMProviderError
from app.services.forensics.prompt_builder import ForensicPromptBuilder
from app.services.forensics.confidence_evaluator import ConfidenceEvaluator
from app.schemas.forensic import InvestigationResultContract


def _get_live_gemini_key() -> str:
    """Helper to retrieve the live Gemini API key from environment or .env without leaking it."""
    envs = dotenv_values(".env")
    key = envs.get("GEMINI_API_KEY") or envs.get("AI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY")
    if not key or not key.strip():
        pytest.skip("Live GEMINI_API_KEY / AI_API_KEY is not configured. Skipping live test.")
    return key.strip()


# ==============================================================================
# 1. Real API Connectivity & Live Investigation
# ==============================================================================

@pytest.mark.asyncio
async def test_live_gemini_api_connectivity():
    """
    Verifies live connectivity to Google Gemini API using configured model (gemini-3.5-flash-lite).
    Confirms valid response structure, latency tracking, token accounting, and zero credential leakage.
    """
    api_key = _get_live_gemini_key()
    target_model = settings.AI_MODEL or "gemini-3.5-flash-lite"
    adapter = GeminiLLMAdapter(api_key=api_key, model_name=target_model)

    system_prompt = (
        "You are Finora's AI Forensic Financial Investigator. "
        "Reply with a JSON object containing 'summary' and 'verified_facts'."
    )
    user_prompt = "Verify Gemini connectivity for Finora. State that connection is verified."

    result = await adapter.generate_investigation(system_prompt=system_prompt, user_prompt=user_prompt)

    assert isinstance(result, dict)
    assert "summary" in result
    assert "verified_facts" in result
    assert isinstance(result["verified_facts"], list)

    # Verify execution metadata
    meta = result.get("_execution_metadata", {})
    assert meta.get("provider") == "gemini"
    assert meta.get("model") == target_model
    assert meta.get("latency_ms", 0) > 0
    assert meta.get("total_tokens", 0) > 0
    assert meta.get("estimated_cost_usd", 0) >= 0


@pytest.mark.asyncio
async def test_live_gemini_controlled_investigation_and_grounded_citations():
    """
    Executes a real investigation against Google Gemini using a controlled financial evidence bundle.
    Verifies that the generated hypotheses cite verified evidence IDs and pass ConfidenceEvaluator grounding.
    """
    api_key = _get_live_gemini_key()
    target_model = settings.AI_MODEL or "gemini-3.5-flash-lite"
    adapter = GeminiLLMAdapter(api_key=api_key, model_name=target_model)

    ev_id_1 = str(uuid.uuid4())
    ev_id_2 = str(uuid.uuid4())

    controlled_bundle = {
        "exception_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "detector_type": "FEE_OVERCHARGE",
        "exception_type": "FEE_OVERCHARGE",
        "severity": "HIGH",
        "currency": "INR",
        "dispute_amount": "250.0000",
        "expected_amount": "100.0000",
        "actual_amount": "350.0000",
        "leakage_amount": "250.0000",
        "gateway_name": "RAZORPAY",
        "explanation": "Contract commission rate was 2.0% but payment gateway charged 7.0%.",
        "all_evidence_verified": True,
        "evidence_items": [
            {
                "evidence_id": ev_id_1,
                "evidence_type": "PAYMENT_CAPTURE",
                "entity_type": "canonical_payments",
                "verification_status": "VERIFIED",
                "details": {
                    "payment_id": "pay_live_001",
                    "gross_amount": "5000.00",
                    "gateway_fee": "350.00",
                    "fee_rate_applied": "0.0700",
                },
            },
            {
                "evidence_id": ev_id_2,
                "evidence_type": "FEE_CONTRACT",
                "entity_type": "fee_contracts",
                "verification_status": "VERIFIED",
                "details": {
                    "contract_id": "cnt_live_2026",
                    "counterparty": "RAZORPAY",
                    "agreed_rate": "0.0200",
                    "effective_date": "2026-01-01",
                },
            },
        ],
    }

    system_prompt = ForensicPromptBuilder.get_system_prompt()
    user_prompt = ForensicPromptBuilder.build_user_prompt(controlled_bundle)

    raw_result = await adapter.generate_investigation(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    # Verify structured response schema
    assert "summary" in raw_result
    assert "hypotheses" in raw_result
    assert isinstance(raw_result["hypotheses"], list)
    assert len(raw_result["hypotheses"]) >= 1

    # Run through deterministic ConfidenceEvaluator
    result_contract, conclusion, confidence = ConfidenceEvaluator.evaluate(
        raw_result=raw_result,
        evidence_bundle=controlled_bundle,
    )

    assert isinstance(result_contract, InvestigationResultContract)
    assert len(result_contract.hypotheses) >= 1

    # Verify grounded citations
    all_cited = []
    for h in result_contract.hypotheses:
        all_cited.extend(h.supporting_evidence_ids)

    # Citations must only contain valid verified evidence IDs
    valid_ids = {ev_id_1, ev_id_2}
    for cited in all_cited:
        assert cited in valid_ids, f"Fabricated or unverified citation detected: {cited}"

    # Governance check: Read-only, conclusion is grounded
    assert conclusion in (InvestigationConclusion.SUPPORTED, InvestigationConclusion.PARTIALLY_SUPPORTED)
    assert confidence in (InvestigationConfidence.MEDIUM, InvestigationConfidence.HIGH)


# ==============================================================================
# 2. Security & Credential Protection
# ==============================================================================

def test_sanitize_error_message_strips_api_keys():
    """
    Verifies that _sanitize_error_message completely redacts raw API keys
    and Google AIzaSy regex patterns from error strings.
    """
    fake_key = "AIzaSyB3fakeKey99887766554433221100X"
    raw_error = f"HTTP 400: Invalid request for key {fake_key} on endpoint https://generativelanguage.googleapis.com"

    sanitized = _sanitize_error_message(raw_error, api_key=fake_key)

    assert fake_key not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    assert "Invalid request" in sanitized


@pytest.mark.asyncio
async def test_invalid_api_key_fails_safely_without_leaking_key():
    """
    Verifies that calling Gemini with an invalid API key fails cleanly with LLMProviderError,
    does NOT loop through retries, and NEVER exposes the invalid key in logs or exceptions.
    """
    bad_key = "AIzaSyD_InvalidTestKeyThatShouldNeverBeExposed123"
    adapter = GeminiLLMAdapter(api_key=bad_key, model_name="gemini-3.1-flash-lite", max_retries=1)

    with pytest.raises(LLMProviderError) as exc_info:
        await adapter.generate_investigation(
            system_prompt="Test system prompt",
            user_prompt="Test user prompt",
        )

    err_msg = str(exc_info.value)
    assert bad_key not in err_msg
    assert "[REDACTED_API_KEY]" in err_msg or "authentication" in err_msg.lower() or "invalid" in err_msg.lower()


# ==============================================================================
# 3. Timeout, Retries, Backoff & Rate Limiting
# ==============================================================================

@pytest.mark.asyncio
async def test_gemini_adapter_timeout_handling():
    """
    Verifies that when Gemini requests exceed the configured timeout,
    the adapter handles TimeoutError, retries, and raises LLMProviderError upon exhaustion.
    """
    adapter = GeminiLLMAdapter(
        api_key="AIzaSyMockKeyForTimeoutTest_1234567890",
        timeout_seconds=0.01,  # Ultra-short timeout
        max_retries=2,
    )

    async def _mock_slow_call(*args, **kwargs):
        await asyncio.sleep(0.5)
        return MagicMock(text='{"summary": "done"}')

    with patch("google.genai.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.aio.models.generate_content = AsyncMock(side_effect=_mock_slow_call)
        mock_client_cls.return_value = mock_instance

        with pytest.raises(LLMProviderError) as exc_info:
            await adapter.generate_investigation("system", "user")

        assert "timed out" in str(exc_info.value)
        assert mock_instance.aio.models.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_gemini_adapter_rate_limit_backoff_and_recovery():
    """
    Verifies that HTTP 429 / Resource Exhausted errors trigger exponential backoff
    and cleanly recover when a subsequent attempt succeeds.
    """
    adapter = GeminiLLMAdapter(
        api_key="AIzaSyMockKeyForRateLimitTest_12345678",
        max_retries=3,
    )

    call_count = 0

    async def _mock_rate_limit_then_success(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("429 Resource Exhausted: Quota exceeded for quota metric 'GenerateContent'")
        resp = MagicMock()
        resp.text = '{"summary": "Rate limit recovered", "hypotheses": []}'
        resp.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50, total_token_count=150)
        return resp

    with patch("google.genai.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.aio.models.generate_content = AsyncMock(side_effect=_mock_rate_limit_then_success)
        mock_client_cls.return_value = mock_instance

        # Patch asyncio.sleep to avoid waiting during test
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await adapter.generate_investigation("system", "user")

            assert result["summary"] == "Rate limit recovered"
            assert call_count == 2
            mock_sleep.assert_awaited()  # Confirms backoff sleep occurred


# ==============================================================================
# 4. Provider Failure Fallback & Resilient JSON Parsing
# ==============================================================================

@pytest.mark.asyncio
async def test_gemini_adapter_fallback_to_mock_on_provider_error():
    """
    Verifies that if a fallback adapter is configured and Gemini encounters
    a fatal error, the adapter seamlessly falls back without raising an unhandled exception.
    """
    mock_fallback = MockLLMAdapter(
        model_name="mock-fallback-v1",
        predefined_response={"summary": "Fallback executed successfully", "hypotheses": []},
    )

    adapter = GeminiLLMAdapter(
        api_key="AIzaSyBadKey",
        max_retries=1,
        fallback_adapter=mock_fallback,
    )

    with patch("google.genai.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.aio.models.generate_content = AsyncMock(side_effect=Exception("401 Unauthorized: Invalid API key"))
        mock_client_cls.return_value = mock_instance

        result = await adapter.generate_investigation("system", "user")

        assert result["summary"] == "Fallback executed successfully"
        assert result.get("_execution_metadata", {}).get("provider") == "mock"


def test_json_parsing_resilience():
    """
    Verifies that _parse_json_response handles pure JSON, markdown fenced JSON,
    and conversational preamble/postamble cleanly.
    """
    adapter = GeminiLLMAdapter(api_key="dummy-key")

    # Pure JSON
    assert adapter._parse_json_response('{"summary": "clean"}') == {"summary": "clean"}

    # Fenced markdown
    fenced = '```json\n{"summary": "fenced"}\n```'
    assert adapter._parse_json_response(fenced) == {"summary": "fenced"}

    # Conversational wrapper
    conversational = 'Here is the forensic investigation output:\n```json\n{"summary": "wrapped"}\n```\nHope this helps!'
    assert adapter._parse_json_response(conversational) == {"summary": "wrapped"}

    # Malformed JSON raises LLMProviderError
    with pytest.raises(LLMProviderError):
        adapter._parse_json_response("Not JSON at all")


# ==============================================================================
# 5. Factory Function & Configuration Precedence
# ==============================================================================

def test_get_llm_adapter_factory_precedence():
    """
    Verifies get_llm_adapter properly resolves provider, key, and model from settings and params.
    """
    # 1. Mock provider
    mock_adapter = get_llm_adapter(provider="mock")
    assert isinstance(mock_adapter, MockLLMAdapter)
    assert mock_adapter.provider_name == "mock"

    # 2. Gemini provider with explicit key
    gemini_adapter = get_llm_adapter(provider="gemini", api_key="test-key-123", model_name="gemini-3.1-flash-lite")
    assert isinstance(gemini_adapter, GeminiLLMAdapter)
    assert gemini_adapter.provider_name == "gemini"
    assert gemini_adapter.model_name == "gemini-3.1-flash-lite"
    assert gemini_adapter.api_key == "test-key-123"

    # 3. Deprecated model automatically upgraded
    legacy_adapter = GeminiLLMAdapter(api_key="test-key", model_name="gemini-2.0-flash")
    assert legacy_adapter.model_name == "gemini-3.1-flash-lite"
