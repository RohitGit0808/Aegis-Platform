"""LLM-backed locator healing via Claude (Anthropic SDK).

The engine treats the LLM as a pluggable strategy behind the :class:`HealingLLM`
protocol. When no API key is configured we use :class:`NullHealingLLM`, so the
platform degrades gracefully to heuristic-only healing with zero code changes.
The Claude call is constrained to a strict JSON schema (structured outputs) so
the response is always machine-parseable, and is fronted by a timeout + circuit
breaker so a slow provider can never stall the worker pool.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from aegis.core.config import settings
from aegis.core.logging import get_logger
from aegis.core.resilience import CircuitBreaker, with_timeout
from aegis.domain.enums import HealingStrategy
from aegis.domain.schemas import HealingProposal

log = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a test-automation locator-repair assistant. A CSS/XPath selector that "
    "previously matched an element no longer matches because the DOM changed. Given the "
    "broken selector, an optional human-readable description of the element's purpose, and "
    "the current DOM snapshot, identify the single element the test intended to target and "
    "return the most robust, stable CSS selector for it (prefer data-test ids, then id, then "
    "stable attributes; avoid brittle :nth-child chains). If no element plausibly matches, "
    "return an empty string for `selector` and a confidence of 0."
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "selector": {
            "type": "string",
            "description": "Healed CSS selector, or empty string if none found.",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence between 0 and 1.",
        },
        "rationale": {
            "type": "string",
            "description": "Brief justification for the chosen selector.",
        },
    },
    "required": ["selector", "confidence", "rationale"],
    "additionalProperties": False,
}

_MAX_DOM_CHARS = 6000


@runtime_checkable
class HealingLLM(Protocol):
    async def propose(
        self, original_selector: str, html: str, *, context: str | None = None
    ) -> HealingProposal | None: ...


class NullHealingLLM:
    """No-op provider used when no API key is configured."""

    async def propose(
        self, original_selector: str, html: str, *, context: str | None = None
    ) -> HealingProposal | None:
        return None


class ClaudeHealingLLM:
    """Healing strategy backed by Claude via the Anthropic async SDK."""

    def __init__(self) -> None:
        # Imported lazily so the package imports without the SDK when LLM is unused.
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.healing_model
        self._breaker = CircuitBreaker(name="claude-healing", failure_threshold=4)

    async def propose(
        self, original_selector: str, html: str, *, context: str | None = None
    ) -> HealingProposal | None:
        prompt = (
            f"Broken selector:\n{original_selector}\n\n"
            f"Element description: {context or '(none provided)'}\n\n"
            f"Current DOM snapshot (truncated):\n{html[:_MAX_DOM_CHARS]}"
        )
        try:
            return await self._breaker.call(lambda: self._invoke(prompt))
        except Exception as exc:  # degrade to heuristic-only on any failure
            log.warning("healing.llm.failed", error=str(exc))
            return None

    async def _invoke(self, prompt: str) -> HealingProposal | None:
        message = await with_timeout(
            self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA},
                },
                messages=[{"role": "user", "content": prompt}],
            ),
            seconds=settings.healing_llm_timeout_seconds,
        )

        if message.stop_reason == "refusal":  # safety classifier declined
            return None

        text = next((b.text for b in message.content if b.type == "text"), None)
        if not text:
            return None

        data = json.loads(text)
        selector = (data.get("selector") or "").strip()
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        return HealingProposal(
            healed_selector=selector or None,
            strategy=HealingStrategy.LLM,
            confidence=confidence,
            rationale=str(data.get("rationale", "")).strip() or "LLM proposal.",
        )


def build_llm() -> HealingLLM:
    """Return the configured healing LLM (Claude if a key is set, else null)."""
    if settings.healing_llm_available:
        return ClaudeHealingLLM()
    return NullHealingLLM()
