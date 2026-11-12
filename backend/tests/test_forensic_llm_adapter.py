import pytest
from app.services.forensics.llm_adapter import (
    BaseLLMAdapter,
    GeminiLLMAdapter,
    MockLLMAdapter,
    get_llm_adapter,
)
from app.services.forensics.exceptions import LLMProviderError


@pytest.mark.asyncio
async def test_mock_llm_adapter_valid_response():
    adapter = MockLLMAdapter()
    res = await adapter.generate_investigation(
        system_prompt="Test system",
        user_prompt='Investigate {"detector_type": "FEE_OVERCHARGE", "evidence_items": [{"evidence_id": "ev-123"}]}'
    )
    assert "summary" in res
    assert "hypotheses" in res
    assert len(res["hypotheses"]) >= 1
    assert adapter.provider_name == "mock"


@pytest.mark.asyncio
async def test_mock_llm_adapter_simulated_timeout():
    adapter = MockLLMAdapter(simulate_timeout=True)
    with pytest.raises(LLMProviderError, match="timed out"):
        await adapter.generate_investigation(system_prompt="sys", user_prompt="usr")


@pytest.mark.asyncio
async def test_mock_llm_adapter_simulated_invalid_json():
    adapter = MockLLMAdapter(simulate_invalid_json=True)
    with pytest.raises(LLMProviderError, match="malformed JSON"):
        await adapter.generate_investigation(system_prompt="sys", user_prompt="usr")


@pytest.mark.asyncio
async def test_mock_llm_adapter_simulated_error():
    adapter = MockLLMAdapter(simulate_error="API Rate Limit Exceeded")
    with pytest.raises(LLMProviderError, match="API Rate Limit Exceeded"):
        await adapter.generate_investigation(system_prompt="sys", user_prompt="usr")


@pytest.mark.asyncio
async def test_gemini_llm_adapter_missing_api_key():
    adapter = GeminiLLMAdapter(api_key=None)
    with pytest.raises(LLMProviderError, match="PENDING_CONFIGURATION|UNVERIFIED"):
        await adapter.generate_investigation(system_prompt="sys", user_prompt="usr")


def test_get_llm_adapter_factory():
    adapter = get_llm_adapter(provider="mock")
    assert isinstance(adapter, MockLLMAdapter)
    assert adapter.provider_name == "mock"
