import os
import json
import re
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from app.core.config import settings
from app.services.forensics.exceptions import LLMProviderError

logger = logging.getLogger(__name__)


class BaseLLMAdapter(ABC):
    """
    Provider-independent interface for LLM-based forensic investigations.
    """

    def __init__(self, model_name: str, temperature: float = 0.1, max_tokens: int = 2048):
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    async def generate_investigation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """
        Executes prompt against LLM and returns structured JSON dictionary.
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass


class GeminiLLMAdapter(BaseLLMAdapter):
    """
    Official Google GenAI (Gemini) LLM Adapter using the google-genai SDK.
    Supports asynchronous execution, timeout handling, retries, and strict JSON output parsing.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ):
        model = model_name or settings.AI_MODEL or "gemini-2.0-flash"
        super().__init__(model_name=model, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key or settings.AI_API_KEY or os.environ.get("GEMINI_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def generate_investigation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise LLMProviderError(
                "Gemini API key is not configured. Set AI_API_KEY or GEMINI_API_KEY environment variable. "
                "Live provider status: UNVERIFIED."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise LLMProviderError(f"google-genai package not installed: {str(e)}")

        client = genai.Client(api_key=self.api_key)

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # Wrap with timeout
                async with asyncio.timeout(self.timeout_seconds):
                    config = types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=self.temperature,
                        max_output_tokens=self.max_tokens,
                        response_mime_type="application/json",
                    )
                    response = await client.aio.models.generate_content(
                        model=self.model_name,
                        contents=user_prompt,
                        config=config,
                    )

                text = response.text or ""
                return self._parse_json_response(text)

            except asyncio.TimeoutError:
                last_error = f"Gemini request timed out after {self.timeout_seconds}s (attempt {attempt}/{self.max_retries})"
                logger.warning(last_error)
            except Exception as e:
                err_str = str(e)
                last_error = f"Gemini API error (attempt {attempt}/{self.max_retries}): {err_str}"
                logger.warning(last_error)
                # Rate limit or quota error check
                if "429" in err_str or "quota" in err_str.lower() or "resource_exhausted" in err_str.lower():
                    await asyncio.sleep(2 ** attempt)
                    continue
                # If non-retryable client error, raise immediately
                if "400" in err_str or "invalid" in err_str.lower():
                    raise LLMProviderError(f"Invalid request to Gemini: {err_str}")

            if attempt < self.max_retries:
                await asyncio.sleep(1.0 * attempt)

        raise LLMProviderError(f"Gemini investigation generation failed after {self.max_retries} attempts. Last error: {last_error}")

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        # Strip code markdown block if present
        clean_text = text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        try:
            return json.loads(clean_text)
        except json.JSONDecodeError as e:
            raise LLMProviderError(f"LLM returned malformed JSON: {str(e)}. Raw text: {text[:200]}")


class MockLLMAdapter(BaseLLMAdapter):
    """
    Deterministic Mock LLM Adapter for unit, integration, and security testing.
    Provides controllable responses, simulated failures, and synthetic forensic reasoning.
    """

    def __init__(
        self,
        model_name: str = "mock-forensic-v1",
        predefined_response: Optional[Dict[str, Any]] = None,
        simulate_error: Optional[str] = None,
        simulate_timeout: bool = False,
        simulate_invalid_json: bool = False,
    ):
        super().__init__(model_name=model_name)
        self.predefined_response = predefined_response
        self.simulate_error = simulate_error
        self.simulate_timeout = simulate_timeout
        self.simulate_invalid_json = simulate_invalid_json

    @property
    def provider_name(self) -> str:
        return "mock"

    async def generate_investigation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        if self.simulate_timeout:
            raise LLMProviderError("Mock request timed out after 30s")

        if self.simulate_error:
            raise LLMProviderError(f"Simulated LLM error: {self.simulate_error}")

        if self.simulate_invalid_json:
            raise LLMProviderError("LLM returned malformed JSON: Expecting property name enclosed in double quotes")

        if self.predefined_response:
            return self.predefined_response

        # Automatically construct a sensible, deterministic response from the prompt
        return self._generate_default_deterministic_response(user_prompt)

    def _generate_default_deterministic_response(self, user_prompt: str) -> Dict[str, Any]:
        # Extract evidence IDs from user prompt if present
        evidence_ids = re.findall(r'"evidence_id":\s*"([a-f0-9\-]+)"', user_prompt)
        detector_types = re.findall(r'"detector_type":\s*"([A-Z_]+)"', user_prompt)
        detector_type = detector_types[0] if detector_types else "REVENUE_LEAKAGE"

        supporting = evidence_ids[:2] if evidence_ids else []
        missing = ["Missing counterparty bank transmission log"] if not evidence_ids else []

        return {
            "summary": f"Forensic analysis of {detector_type} exception substantiated by {len(supporting)} verified evidence records.",
            "hypotheses": [
                {
                    "hypothesis_id": "H1",
                    "title": f"Root Cause: {detector_type.replace('_', ' ').title()}",
                    "explanation": f"Evaluation of primary source records indicates an unresolved discrepancy in {detector_type}.",
                    "supporting_evidence_ids": supporting,
                    "contradicting_evidence_ids": [],
                    "missing_evidence": missing,
                    "confidence": "MEDIUM" if len(supporting) >= 2 else "LOW",
                }
            ],
            "verified_facts": [
                f"Exception classification confirmed as {detector_type}.",
                f"Evaluated {len(evidence_ids)} total evidence items in execution bundle.",
            ],
            "contradictions": [],
            "missing_information": missing,
            "recommended_human_checks": [
                "Inspect counterparty gateway settlement statement for corresponding payout ID.",
                "Verify bank statement feed for matching credit entry.",
            ],
        }


def get_llm_adapter(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None
) -> BaseLLMAdapter:
    """
    Factory function returning the configured LLM adapter.
    """
    active_provider = (provider or settings.AI_PROVIDER or "gemini").lower()

    if active_provider == "gemini":
        key = api_key or settings.AI_API_KEY
        if key:
            return GeminiLLMAdapter(api_key=key, model_name=model_name)
        elif settings.ENVIRONMENT in ("test", "development"):
            logger.info("Gemini API key not configured; falling back to MockLLMAdapter for testing.")
            return MockLLMAdapter()
        else:
            return GeminiLLMAdapter(api_key=None, model_name=model_name)

    return MockLLMAdapter(model_name=model_name or "mock-forensic-v1")
