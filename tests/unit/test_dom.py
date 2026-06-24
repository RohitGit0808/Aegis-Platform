"""Unit tests for :mod:`aegis.healing.dom`.

Selector parsing and DOM flattening are pure (BeautifulSoup + regex), so we can
feed small inline HTML/selector snippets and assert structure directly.
"""

from __future__ import annotations

import pytest

from aegis.healing.dom import (
    DomElement,
    parse_dom,
    parse_selector,
    snapshot_hash,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# parse_selector
# --------------------------------------------------------------------------- #
def test_parse_selector_extracts_id_classes_and_tag() -> None:
    hints = parse_selector("button#submit-btn.primary.large")
    assert hints.tag == "button"
    assert hints.element_id == "submit-btn"
    assert hints.classes == {"primary", "large"}


def test_parse_selector_extracts_testid_attribute() -> None:
    hints = parse_selector('[data-testid="checkout-button"]')
    assert hints.attributes["data-testid"] == "checkout-button"
    assert hints.test_id == "checkout-button"


def test_parse_selector_extracts_playwright_text() -> None:
    # Unquoted Playwright `text=` engine syntax.
    hints = parse_selector("text=Add to cart")
    assert hints.text == "Add to cart"

    # Quoted `has-text(...)` pseudo, combined with a tag.
    has_text = parse_selector('button:has-text("Sign in")')
    assert has_text.text == "Sign in"
    assert has_text.tag == "button"


def test_parse_selector_uses_last_segment_for_tag() -> None:
    # Descendant combinator: the rightmost simple selector wins for the tag.
    hints = parse_selector("div.container > a.link")
    assert hints.tag == "a"
    assert "link" in hints.classes


def test_parse_selector_test_id_alias_priority() -> None:
    # data-testid is preferred, but aliases are recognised too.
    hints = parse_selector('[data-qa="login"]')
    assert hints.test_id == "login"


# --------------------------------------------------------------------------- #
# parse_dom
# --------------------------------------------------------------------------- #
def test_parse_dom_flattens_interactable_elements() -> None:
    html = """
    <html><body>
      <div class="layout">
        <button data-testid="buy">Buy now</button>
        <a href="/help">Help</a>
        <input name="email" placeholder="Email"/>
      </div>
      <span>just text</span>
    </body></html>
    """
    elements = parse_dom(html)
    tags = [e.tag for e in elements]

    assert "button" in tags
    assert "a" in tags
    assert "input" in tags
    # A bare layout <span> carries no identifying signal and is dropped.
    assert "span" not in tags


def test_parse_dom_keeps_non_interactable_with_identifying_attr() -> None:
    # A <div> is not interactable, but a data-testid makes it a candidate.
    html = '<div data-testid="banner">Welcome</div><div class="plain">x</div>'
    elements = parse_dom(html)
    testids = [e.test_id for e in elements]
    assert "banner" in testids


def test_parse_dom_empty_html_returns_empty_list() -> None:
    assert parse_dom("") == []


def test_parse_dom_captures_attrs_and_text() -> None:
    html = '<button data-testid="go" class="btn primary">Go &amp; Save</button>'
    [element] = parse_dom(html)
    assert element.tag == "button"
    assert element.attributes["data-testid"] == "go"
    assert element.classes == ["btn", "primary"]
    assert element.text == "Go & Save"


# --------------------------------------------------------------------------- #
# DomElement.to_selector
# --------------------------------------------------------------------------- #
def test_to_selector_prefers_test_id() -> None:
    element = DomElement(
        tag="button",
        element_id="submit",
        classes=["primary"],
        attributes={"data-testid": "checkout", "id": "submit"},
        text="Checkout",
    )
    assert element.to_selector() == '[data-testid="checkout"]'


def test_to_selector_falls_back_to_id_then_classes() -> None:
    by_id = DomElement(
        tag="div", element_id="hero", classes=["a"], attributes={"id": "hero"}, text=""
    )
    assert by_id.to_selector() == "#hero"

    by_class = DomElement(
        tag="span",
        element_id=None,
        classes=["a", "b", "c", "d"],
        attributes={},
        text="",
    )
    # Caps at the first three classes for stability.
    assert by_class.to_selector() == "span.a.b.c"


def test_to_selector_falls_back_to_stable_attribute() -> None:
    element = DomElement(
        tag="input",
        element_id=None,
        classes=[],
        attributes={"name": "email"},
        text="",
    )
    assert element.to_selector() == 'input[name="email"]'


def test_to_selector_bare_tag_when_no_signal() -> None:
    element = DomElement(tag="button", element_id=None, classes=[], attributes={}, text="")
    assert element.to_selector() == "button"


# --------------------------------------------------------------------------- #
# snapshot_hash
# --------------------------------------------------------------------------- #
def test_snapshot_hash_is_deterministic() -> None:
    html = "<div data-testid='x'>hi</div>"
    assert snapshot_hash(html) == snapshot_hash(html)


def test_snapshot_hash_differs_for_different_content() -> None:
    assert snapshot_hash("<a>one</a>") != snapshot_hash("<a>two</a>")


def test_snapshot_hash_is_sha256_hex() -> None:
    digest = snapshot_hash("anything")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
