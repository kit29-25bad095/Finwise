import os
import json
import re
import time
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from app.core.config import settings
from app.services.forensics.exceptions import LLMProviderError
from app.core.monitoring.metrics import metrics_collector

logger = logging.getLogger(__name__)


def _sanitize_error_message(err_str: str, api_key: Optional[str] = None) -> str:
    """
    Strips raw API keys or key-like tokens from error messages to prevent credential leakage.
    """
    if not err_str:
        return ""
    sanitized = err_str
    if api_key and len(api_key) > 5:
        sanitized = sanitized.replace(api_key, "[REDACTED_API_KEY]")
    # Also strip standard Google AIza API key format
    sanitized = re.sub(r'AIzaSy[A-Za-z0-9_-]{33}', '[REDACTED_API_KEY]', sanitized)
    return sanitized


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
    Supports asynchronous execution, timeout handling, retries, rate-limit backoff,
    and strict JSON output parsing.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        fallback_adapter: Optional[BaseLLMAdapter] = None,
    ):
        model = model_name or settings.AI_MODEL or "gemini-3.1-flash-lite"
        # Map deprecated models to supported modern models
        if model in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"):
            logger.info("Mapping deprecated model %s to gemini-3.1-flash-lite", model)
            model = "gemini-3.1-flash-lite"
        super().__init__(model_name=model, temperature=temperature, max_tokens=max_tokens)
        resolved_key = (
            api_key
            or settings.resolved_ai_api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("AI_API_KEY")
        )
        self.api_key = resolved_key.strip() if resolved_key and resolved_key.strip() else None
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.fallback_adapter = fallback_adapter

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    async def generate_investigation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        if not self.is_configured:
            if self.fallback_adapter:
                logger.warning("Gemini API key is not configured; invoking fallback adapter %s", self.fallback_adapter.provider_name)
                return await self.fallback_adapter.generate_investigation(system_prompt, user_prompt)
            raise LLMProviderError(
                "Gemini API key is not configured. Set GEMINI_API_KEY or AI_API_KEY environment variable. "
                "Provider status: PENDING_CONFIGURATION (UNVERIFIED)."
            )

        try:
            from google import genai
            from google.genai import types
            from google.genai.errors import APIError, ClientError
        except ImportError as e:
            if self.fallback_adapter:
                logger.warning("google-genai package not installed; invoking fallback adapter %s", self.fallback_adapter.provider_name)
                return await self.fallback_adapter.generate_investigation(system_prompt, user_prompt)
            raise LLMProviderError(f"google-genai package not installed: {str(e)}")

        client = genai.Client(api_key=self.api_key)

        start_time = time.perf_counter()
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # Wrap with explicit asyncio timeout
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

                duration_sec = time.perf_counter() - start_time
                latency_ms = duration_sec * 1000.0
                metrics_collector.record_gemini_call(duration_sec=duration_sec, success=True)
                text = getattr(response, "text", "") or ""
                parsed = self._parse_json_response(text)

                # Extract token usage and compute estimated cost
                usage = getattr(response, "usage_metadata", None)
                prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
                candidates_tokens = getattr(usage, "candidates_token_count", None) if usage else None
                total_tokens = getattr(usage, "total_token_count", None) if usage else None

                p_tok = prompt_tokens or 0
                c_tok = candidates_tokens or 0
                tot_tok = total_tokens or (p_tok + c_tok)

                # Gemini Flash-Lite pricing estimate (~$0.075/1M prompt, $0.30/1M completion)
                est_cost = (p_tok * 0.000000075) + (c_tok * 0.00000030)

                parsed["_token_usage"] = {
                    "prompt_tokens": prompt_tokens,
                    "candidate_tokens": candidates_tokens,
                    "total_tokens": total_tokens,
                    "model": self.model_name
                }
                parsed["_execution_metadata"] = {
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "latency_ms": round(latency_ms, 2),
                    "prompt_tokens": p_tok,
                    "candidates_tokens": c_tok,
                    "total_tokens": tot_tok,
                    "estimated_cost_usd": round(est_cost, 6),
                }
                logger.info(
                    f"Gemini investigation completed. Model: {self.model_name}, "
                    f"Prompt tokens: {prompt_tokens}, Candidate tokens: {candidates_tokens}, Total tokens: {total_tokens}"
                )
                return parsed

            except asyncio.TimeoutError:
                metrics_collector.record_gemini_call(
                    duration_sec=(time.perf_counter() - start_time),
                    success=False,
                    error_type="timeout",
                )
                last_error = f"Gemini request timed out after {self.timeout_seconds}s (attempt {attempt}/{self.max_retries})"
                logger.warning(last_error)
            except ClientError as e:
                # 400, 401, 403 are non-retryable client errors (invalid key, model not found, etc.)
                err_msg = str(e)
                code = getattr(e, "code", None)
                if code in (401, 403) or any(term in err_msg.lower() for term in ("api_key_invalid", "invalid api key", "unauthenticated", "permission_denied")):
                    raise LLMProviderError(f"Gemini API authentication failed: Invalid or expired API key. Details: {err_msg}")
                raise LLMProviderError(f"Gemini API client error (HTTP {code}): {err_msg}")
            except APIError as e:
                err_str = str(e)
                code = getattr(e, "code", None)
                # Rate limit (429) or quota exhaustion
                if code == 429 or "429" in err_str or any(term in err_str.lower() for term in ("quota", "resource_exhausted", "rate limit")):
                    last_error = f"Gemini API rate limit exceeded (HTTP 429 / RESOURCE_EXHAUSTED): {err_str}"
                    logger.warning(f"{last_error}. Backing off attempt {attempt}/{self.max_retries}...")
                    if attempt < self.max_retries:
                        await asyncio.sleep(2 ** attempt)
                        continue
                last_error = f"Gemini API server error (HTTP {code}): {err_str}"
                logger.warning(last_error)
            except Exception as e:
                raw_err = str(e)
                err_lower = raw_err.lower()
                error_type = "rate_limit" if ("429" in raw_err or "quota" in err_lower or "resource_exhausted" in err_lower) else "api_error"
                metrics_collector.record_gemini_call(
                    duration_sec=(time.perf_counter() - start_time),
                    success=False,
                    error_type=error_type,
                )
                err_str = _sanitize_error_message(raw_err, self.api_key)
                last_error = f"Gemini API error (attempt {attempt}/{self.max_retries}): {err_str}"
                logger.warning(last_error)
                # Rate limit or quota error check -> exponential backoff
                if "429" in raw_err or "quota" in err_lower or "resource_exhausted" in err_lower:
                    if attempt < self.max_retries:
                        backoff = 2 ** attempt
                        logger.info("Rate limit hit on Gemini API; sleeping for %ss before retry", backoff)
                        await asyncio.sleep(backoff)
                        continue

                # Authentication / Permission / Invalid API key check -> FAIL-FAST immediately without retrying
                if (
                    "api_key_invalid" in err_lower
                    or "invalid api key" in err_lower
                    or "permission_denied" in err_lower
                    or "401" in raw_err
                    or "403" in raw_err
                    or "unauthenticated" in err_lower
                ):
                    clean_msg = f"Gemini authentication/permission error: {err_str}"
                    if self.fallback_adapter:
                        logger.warning("%s; invoking fallback adapter %s", clean_msg, self.fallback_adapter.provider_name)
                        return await self.fallback_adapter.generate_investigation(system_prompt, user_prompt)
                    raise LLMProviderError(clean_msg)

                # Non-retryable 400 Bad Request / Invalid request
                if any(code in raw_err for code in ("400", "401", "403")) or "invalid" in err_lower:
                    clean_msg = f"Invalid request to Gemini: {err_str}"
                    if self.fallback_adapter:
                        logger.warning("%s; invoking fallback adapter %s", clean_msg, self.fallback_adapter.provider_name)
                        return await self.fallback_adapter.generate_investigation(system_prompt, user_prompt)
                    raise LLMProviderError(clean_msg)

            if attempt < self.max_retries:
                backoff = 1.0 * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

        clean_final_error = _sanitize_error_message(last_error or "Unknown failure", self.api_key)
        if self.fallback_adapter:
            logger.warning(
                "Gemini failed after %d attempts (%s); invoking fallback adapter %s",
                self.max_retries,
                clean_final_error,
                self.fallback_adapter.provider_name,
            )
            return await self.fallback_adapter.generate_investigation(system_prompt, user_prompt)

        raise LLMProviderError(f"Gemini investigation generation failed after {self.max_retries} attempts. Last error: {clean_final_error}")

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        clean_text = text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        # Isolate outermost JSON object if wrapped in explanatory text
        if "{" in clean_text and "}" in clean_text:
            first_brace = clean_text.find("{")
            last_brace = clean_text.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                clean_text = clean_text[first_brace:last_brace + 1]

        try:
            parsed = json.loads(clean_text)
            if isinstance(parsed, dict):
                return parsed
            raise LLMProviderError(f"LLM returned valid JSON but not an object dictionary: {type(parsed).__name__}")
        except (json.JSONDecodeError, ValueError) as e:
            match = re.search(r"(\{.*\})", clean_text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            snippet = text[:200].replace("\n", " ")
            raise LLMProviderError(f"LLM returned malformed JSON: {str(e)}. Raw text: {snippet}")


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
            metrics_collector.record_gemini_call(0.1, False, "timeout")
            raise LLMProviderError("Mock request timed out after 30s")

        if self.simulate_error:
            err_type = "rate_limit" if "429" in self.simulate_error else "api_error"
            metrics_collector.record_gemini_call(0.1, False, err_type)
            raise LLMProviderError(f"Simulated LLM error: {self.simulate_error}")

        if self.simulate_invalid_json:
            metrics_collector.record_gemini_call(0.1, False, "json_parse_error")
            raise LLMProviderError("LLM returned malformed JSON: Expecting property name enclosed in double quotes")

        metrics_collector.record_gemini_call(0.01, True)

        if self.predefined_response:
            resp = dict(self.predefined_response)
            if "_execution_metadata" not in resp:
                resp["_execution_metadata"] = {
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "latency_ms": 10.0,
                    "prompt_tokens": 300,
                    "candidates_tokens": 100,
                    "total_tokens": 400,
                    "estimated_cost_usd": 0.000070,
                }
            return resp

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
            "_execution_metadata": {
                "provider": self.provider_name,
                "model": self.model_name,
                "latency_ms": 15.0,
                "prompt_tokens": 350,
                "candidates_tokens": 120,
                "total_tokens": 470,
                "estimated_cost_usd": 0.000083,
            },
        }


def get_llm_adapter(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    fallback_adapter: Optional[BaseLLMAdapter] = None,
) -> BaseLLMAdapter:
    """
    Factory function returning the configured LLM adapter.
    """
    active_provider = (provider or settings.AI_PROVIDER or "gemini").lower()

    if active_provider == "gemini":
        key = (
            api_key
            or settings.resolved_ai_api_key
            or getattr(settings, "GEMINI_API_KEY", None)
            or getattr(settings, "AI_API_KEY", None)
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("AI_API_KEY")
        )
        if key and key.strip():
            return GeminiLLMAdapter(api_key=key.strip(), model_name=model_name, fallback_adapter=fallback_adapter)
        elif settings.ENVIRONMENT in ("test", "development"):
            logger.info("Gemini API key not configured; falling back to MockLLMAdapter for local test/dev.")
            return MockLLMAdapter()
        else:
            return GeminiLLMAdapter(api_key=None, model_name=model_name, fallback_adapter=fallback_adapter)

    return MockLLMAdapter(model_name=model_name or "mock-forensic-v1")
