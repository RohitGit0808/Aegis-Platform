"""Deterministic, heuristic locator healing.

Given the selector that failed and the DOM snapshot, we score every candidate
element by how strongly its identifying signals (test-id, id, visible text,
classes, tag, attributes) match the broken selector's intent, then synthesise
the most robust selector for the winner. This requires no network and is the
engine's fast, free first line of defence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from aegis.domain.enums import HealingStrategy
from aegis.domain.schemas import HealingProposal
from aegis.healing.dom import DomElement, SelectorHints, parse_dom, parse_selector

# Weights sum to 1.0; the most stable signal (test-id) is enough on its own to
# clear a typical confidence threshold, matching real-world locator practice.
_W_TESTID = 0.60
_W_ID = 0.18
_W_TEXT = 0.10
_W_CLASS = 0.07
_W_TAG = 0.03
_W_ATTR = 0.02
_OTHER_ATTRS = ("name", "aria-label", "placeholder", "role", "type")


@dataclass(slots=True)
class ScoredCandidate:
    element: DomElement
    score: float
    reasons: list[str] = field(default_factory=list)


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


class HeuristicHealer:
    """Score-based candidate selection over a DOM snapshot."""

    def score(self, hints: SelectorHints, element: DomElement) -> ScoredCandidate:
        score = 0.0
        reasons: list[str] = []

        if hints.test_id and element.test_id:
            if hints.test_id == element.test_id:
                score += _W_TESTID
                reasons.append(f"test-id exact ({element.test_id})")
            elif hints.test_id in element.test_id or element.test_id in hints.test_id:
                score += _W_TESTID * 0.5
                reasons.append("test-id partial")

        if hints.element_id and element.element_id:
            if hints.element_id == element.element_id:
                score += _W_ID
                reasons.append(f"id exact ({element.element_id})")
            elif _ratio(hints.element_id, element.element_id) > 0.6:
                score += _W_ID * 0.5
                reasons.append("id similar")

        if hints.text and element.text:
            text_ratio = _ratio(hints.text, element.text)
            if text_ratio > 0.5:
                score += _W_TEXT * text_ratio
                reasons.append(f"text ~{text_ratio:.0%}")

        class_sim = _jaccard(hints.classes, set(element.classes))
        if class_sim > 0:
            score += _W_CLASS * class_sim
            reasons.append(f"class overlap {class_sim:.0%}")

        if hints.tag and hints.tag == element.tag:
            score += _W_TAG
            reasons.append(f"tag <{element.tag}>")

        shared = [
            attr
            for attr in _OTHER_ATTRS
            if hints.attributes.get(attr)
            and hints.attributes.get(attr) == element.attributes.get(attr)
        ]
        if shared:
            score += _W_ATTR * (len(shared) / len(_OTHER_ATTRS))
            reasons.append(f"attrs {','.join(shared)}")

        return ScoredCandidate(element=element, score=min(score, 1.0), reasons=reasons)

    def propose(
        self, original_selector: str, html: str, *, target_text: str | None = None
    ) -> HealingProposal:
        hints = parse_selector(original_selector)
        if target_text and not hints.text:
            hints.text = target_text

        elements = parse_dom(html)
        if not elements:
            return HealingProposal(
                healed_selector=None,
                strategy=HealingStrategy.HEURISTIC,
                confidence=0.0,
                rationale="No interactable elements in the DOM snapshot.",
            )

        best = max((self.score(hints, e) for e in elements), key=lambda c: c.score)
        if best.score <= 0.0:
            return HealingProposal(
                healed_selector=None,
                strategy=HealingStrategy.HEURISTIC,
                confidence=0.0,
                rationale="No candidate shared any signal with the broken selector.",
            )

        return HealingProposal(
            healed_selector=best.element.to_selector(),
            strategy=HealingStrategy.HEURISTIC,
            confidence=round(best.score, 3),
            rationale="Matched on " + "; ".join(best.reasons) + ".",
        )
