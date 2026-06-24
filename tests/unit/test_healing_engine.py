"""Unit tests for :mod:`aegis.healing.engine`.

The :class:`SelfHealingEngine` orchestrates the heuristic and LLM strategies:
prefer the fast heuristic when confident; otherwise consult the LLM and combine
(agreement -> HYBRID with a confidence boost; disagreement -> the more confident
proposal wins). We drive it with a real :class:`HeuristicHealer` plus a small
in-process stub LLM so the test stays pure (no network, no Anthropic SDK).
"""

from __future__ import annotations

import pytest

from aegis.domain.enums import HealingStrategy
from aegis.domain.schemas import HealingProposal
from aegis.healing.engine import SelfHealingEngine
from aegis.healing.strategies import HeuristicHealer

pytestmark = pytest.mark.unit


class StubLLM:
    """In-process ``HealingLLM`` that records calls and returns a canned proposal."""

    def __init__(self, proposal: HealingProposal | None) -> None:
        self._proposal = proposal
        self.calls = 0

    async def propose(
        self, original_selector: str, html: str, *, context: str | None = None
    ) -> HealingProposal | None:
        self.calls += 1
        return self._proposal


async def test_high_confidence_heuristic_skips_llm() -> None:
    # An exact test-id match clears the 0.6 threshold, so the LLM is never called.
    stub = StubLLM(
        HealingProposal(
            healed_selector="#should-not-be-used",
            strategy=HealingStrategy.LLM,
            confidence=0.99,
            rationale="should not be consulted",
        )
    )
    engine = SelfHealingEngine(heuristic=HeuristicHealer(), llm=stub)

    html = '<button data-testid="checkout">Checkout</button>'
    result = await engine.heal('[data-testid="checkout"]', html)

    assert stub.calls == 0
    assert result.strategy is HealingStrategy.HEURISTIC
    assert result.healed_selector == '[data-testid="checkout"]'
    assert result.confidence >= 0.6


async def test_low_heuristic_defers_to_higher_confidence_llm() -> None:
    # Heuristic finds only a weak (class-only) signal; the LLM proposes a
    # different, more confident locator, so the LLM proposal wins.
    stub = StubLLM(
        HealingProposal(
            healed_selector='[data-testid="from-llm"]',
            strategy=HealingStrategy.LLM,
            confidence=0.9,
            rationale="LLM identified the intended element",
        )
    )
    engine = SelfHealingEngine(heuristic=HeuristicHealer(), llm=stub)

    html = '<button class="cta">Click</button>'
    result = await engine.heal("button.cta", html)

    assert stub.calls == 1
    assert result.strategy is HealingStrategy.LLM
    assert result.healed_selector == '[data-testid="from-llm"]'
    assert result.confidence == 0.9


async def test_agreement_produces_hybrid_with_boost() -> None:
    # Heuristic is below threshold but the LLM agrees on the SAME locator ->
    # strategy becomes HYBRID and confidence is boosted above either input.
    html = '<button class="cta">Click</button>'
    heuristic_only = HeuristicHealer().propose("button.cta", html)
    assert heuristic_only.healed_selector is not None
    assert heuristic_only.confidence < 0.6  # ensure the LLM branch is taken

    stub = StubLLM(
        HealingProposal(
            healed_selector=heuristic_only.healed_selector,
            strategy=HealingStrategy.LLM,
            confidence=0.55,
            rationale="LLM concurs.",
        )
    )
    engine = SelfHealingEngine(heuristic=HeuristicHealer(), llm=stub)

    result = await engine.heal("button.cta", html)

    assert stub.calls == 1
    assert result.strategy is HealingStrategy.HYBRID
    assert result.healed_selector == heuristic_only.healed_selector
    expected = min(1.0, max(heuristic_only.confidence, 0.55) + 0.1)
    assert result.confidence == pytest.approx(expected)
    assert result.confidence > heuristic_only.confidence
    assert result.confidence > 0.55


async def test_low_heuristic_and_null_llm_returns_heuristic() -> None:
    # When the LLM returns None (e.g. NullHealingLLM), the heuristic stands.
    stub = StubLLM(None)
    engine = SelfHealingEngine(heuristic=HeuristicHealer(), llm=stub)

    html = '<button class="cta">Click</button>'
    result = await engine.heal("button.cta", html)

    assert stub.calls == 1
    assert result.strategy is HealingStrategy.HEURISTIC


async def test_no_match_anywhere_returns_no_selector() -> None:
    # Heuristic finds nothing and the LLM also declines -> no healed selector.
    stub = StubLLM(None)
    engine = SelfHealingEngine(heuristic=HeuristicHealer(), llm=stub)

    html = "<div>nothing useful here</div>"
    result = await engine.heal("span > span:nth-child(3)", html)

    assert result.healed_selector is None
    assert result.confidence == 0.0
