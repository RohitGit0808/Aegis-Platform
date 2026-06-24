"""The self-healing engine — orchestrates heuristic and LLM strategies.

Strategy: try the fast, free, deterministic heuristic first. If it is confident
enough, use it. Otherwise consult the LLM (when available) and combine: when both
strategies independently agree on the same locator, confidence is boosted and the
result is tagged ``HYBRID``; otherwise the higher-confidence proposal wins. Every
attempt is recorded to Prometheus for observability.
"""

from __future__ import annotations

from aegis.core.config import settings
from aegis.core.logging import get_logger
from aegis.core.metrics import HEALING_ATTEMPTS, HEALING_CONFIDENCE
from aegis.domain.enums import HealingStrategy
from aegis.domain.schemas import HealingProposal
from aegis.healing.llm import HealingLLM, build_llm
from aegis.healing.strategies import HeuristicHealer

log = get_logger(__name__)


class SelfHealingEngine:
    def __init__(
        self, *, heuristic: HeuristicHealer | None = None, llm: HealingLLM | None = None
    ) -> None:
        self._heuristic = heuristic or HeuristicHealer()
        self._llm = llm if llm is not None else build_llm()
        self._min_confidence = settings.healing_min_confidence

    async def heal(
        self, original_selector: str, html: str, *, context: str | None = None
    ) -> HealingProposal:
        heuristic = self._heuristic.propose(original_selector, html, target_text=context)

        if heuristic.confidence >= self._min_confidence:
            best = heuristic
        else:
            llm_proposal = await self._llm.propose(original_selector, html, context=context)
            best = self._combine(heuristic, llm_proposal)

        self._record(best)
        log.info(
            "healing.result",
            original=original_selector,
            healed=best.healed_selector,
            strategy=best.strategy.value,
            confidence=best.confidence,
        )
        return best

    def _combine(self, heuristic: HealingProposal, llm: HealingProposal | None) -> HealingProposal:
        if llm is None or llm.healed_selector is None:
            return heuristic
        if heuristic.healed_selector is None:
            return llm
        if heuristic.healed_selector == llm.healed_selector:
            return HealingProposal(
                healed_selector=llm.healed_selector,
                strategy=HealingStrategy.HYBRID,
                confidence=min(1.0, max(heuristic.confidence, llm.confidence) + 0.1),
                rationale=f"Heuristic and LLM agreed on the locator. {llm.rationale}",
            )
        return llm if llm.confidence >= heuristic.confidence else heuristic

    def _record(self, proposal: HealingProposal) -> None:
        healed = proposal.healed_selector is not None
        confident = healed and proposal.confidence >= self._min_confidence
        outcome = "success" if confident else ("low_confidence" if healed else "no_match")
        HEALING_ATTEMPTS.labels(strategy=proposal.strategy.value, outcome=outcome).inc()
        if healed:
            HEALING_CONFIDENCE.observe(proposal.confidence)
