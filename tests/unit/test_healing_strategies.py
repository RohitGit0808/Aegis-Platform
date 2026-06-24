"""Unit tests for :mod:`aegis.healing.strategies`.

The :class:`HeuristicHealer` scores DOM candidates against a broken selector's
extracted hints. The data-testid weight (0.60) dominates, so an exact test-id
match alone clears the platform's 0.6 confidence threshold.
"""

from __future__ import annotations

import pytest

from aegis.domain.enums import HealingStrategy
from aegis.healing.strategies import HeuristicHealer

pytestmark = pytest.mark.unit


@pytest.fixture
def healer() -> HeuristicHealer:
    return HeuristicHealer()


def test_testid_match_yields_high_confidence(healer: HeuristicHealer) -> None:
    html = """
    <div class="cart">
      <button data-testid="checkout" class="btn">Checkout</button>
      <a href="/home">Home</a>
    </div>
    """
    # The broken selector referenced a now-stale id, but the test-id survives.
    proposal = healer.propose('button#old-checkout-id[data-testid="checkout"]', html)

    assert proposal.strategy is HealingStrategy.HEURISTIC
    assert proposal.confidence >= 0.6
    assert proposal.healed_selector == '[data-testid="checkout"]'


def test_no_signal_selector_yields_zero_confidence(healer: HeuristicHealer) -> None:
    # A purely structural selector shares nothing with the DOM's candidates.
    html = '<button data-testid="unrelated">Unrelated</button>'
    proposal = healer.propose("div > div:nth-child(2) > span", html)

    assert proposal.confidence == 0.0
    assert proposal.healed_selector is None
    assert proposal.strategy is HealingStrategy.HEURISTIC


def test_empty_dom_yields_zero_confidence(healer: HeuristicHealer) -> None:
    proposal = healer.propose('[data-testid="anything"]', "")
    assert proposal.confidence == 0.0
    assert proposal.healed_selector is None


def test_class_overlap_contributes_to_score(healer: HeuristicHealer) -> None:
    # No test-id/id anywhere — only shared classes provide a (small) signal.
    html = '<button class="primary cta large">Go</button>'
    proposal = healer.propose("button.primary.cta.large", html)

    assert proposal.confidence > 0.0
    # Below the 0.6 threshold (class weight is only 0.07) but still a match.
    assert proposal.confidence < 0.6
    assert proposal.healed_selector is not None
    assert "class overlap" in proposal.rationale


def test_partial_testid_scores_lower_than_exact(healer: HeuristicHealer) -> None:
    exact_html = '<button data-testid="submit-form">Go</button>'
    partial_html = '<button data-testid="submit-form-and-more">Go</button>'

    exact = healer.propose('[data-testid="submit-form"]', exact_html)
    partial = healer.propose('[data-testid="submit-form"]', partial_html)

    assert exact.confidence > partial.confidence


def test_target_text_used_when_selector_lacks_text(healer: HeuristicHealer) -> None:
    html = '<button data-testid="x">Save changes</button>'
    # The broken selector has no text hint; target_text supplies the intent.
    proposal = healer.propose('[data-testid="x"]', html, target_text="Save changes")
    assert proposal.healed_selector == '[data-testid="x"]'
    assert proposal.confidence >= 0.6
