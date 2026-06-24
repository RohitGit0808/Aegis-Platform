"""DOM parsing and selector utilities used by the healing strategies.

We deliberately keep this dependency-light (BeautifulSoup + lxml) and pure: no
network, no browser. The healing strategies operate on a *DOM snapshot* — the
HTML captured at the moment a locator failed — which makes the whole engine
deterministic and unit-testable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

_ATTR_RE = re.compile(r"\[([\w:-]+)\s*(?:[*^$|~]?=\s*['\"]?([^'\"\]]*)['\"]?)?\]")
_ID_RE = re.compile(r"#([\w:-]+)")
_CLASS_RE = re.compile(r"\.([\w-]+)")
_TAG_RE = re.compile(r"^([a-zA-Z][\w-]*)")
_TEXT_RE = re.compile(r"(?:text=|has-text\(['\"]|text\(\)\s*=\s*['\"])([^'\")]+)")


@dataclass(slots=True)
class SelectorHints:
    """Structured signal extracted from a (possibly broken) selector string."""

    tag: str | None = None
    element_id: str | None = None
    classes: set[str] = field(default_factory=set)
    attributes: dict[str, str] = field(default_factory=dict)
    text: str | None = None

    @property
    def test_id(self) -> str | None:
        for key in ("data-testid", "data-test-id", "data-test", "data-qa"):
            if key in self.attributes:
                return self.attributes[key]
        return None


@dataclass(slots=True)
class DomElement:
    """A candidate element flattened from the DOM snapshot."""

    tag: str
    element_id: str | None
    classes: list[str]
    attributes: dict[str, str]
    text: str

    @property
    def test_id(self) -> str | None:
        for key in ("data-testid", "data-test-id", "data-test", "data-qa"):
            if key in self.attributes:
                return self.attributes[key]
        return None

    def to_selector(self) -> str:
        """Generate the most robust CSS selector this element supports."""
        if self.test_id is not None:
            key = next(
                k
                for k in ("data-testid", "data-test-id", "data-test", "data-qa")
                if k in self.attributes
            )
            return f'[{key}="{self.test_id}"]'
        if self.element_id:
            return f"#{self.element_id}"
        if self.classes:
            return self.tag + "".join(f".{c}" for c in self.classes[:3])
        for attr in ("name", "aria-label", "placeholder", "role", "type"):
            if attr in self.attributes:
                return f'{self.tag}[{attr}="{self.attributes[attr]}"]'
        return self.tag


def parse_selector(selector: str) -> SelectorHints:
    """Best-effort parse of CSS/XPath/Playwright-style selectors into hints."""
    hints = SelectorHints()

    if (text_match := _TEXT_RE.search(selector)) is not None:
        hints.text = text_match.group(1).strip()

    for attr_match in _ATTR_RE.finditer(selector):
        key, value = attr_match.group(1), attr_match.group(2)
        hints.attributes[key] = value or ""

    if (id_match := _ID_RE.search(selector)) is not None:
        hints.element_id = id_match.group(1)

    hints.classes = set(_CLASS_RE.findall(selector))

    head = selector.strip().split(">")[-1].strip()
    if (tag_match := _TAG_RE.match(head)) is not None:
        tag = tag_match.group(1).lower()
        if tag not in {"text", "has"}:
            hints.tag = tag

    return hints


def parse_dom(html: str) -> list[DomElement]:
    """Flatten an HTML snapshot into interactable candidate elements."""
    soup = BeautifulSoup(html or "", "lxml")
    interactable = {"a", "button", "input", "select", "textarea", "label", "option"}
    elements: list[DomElement] = []

    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        name = tag.name.lower()
        attrs = {k: (" ".join(v) if isinstance(v, list) else str(v)) for k, v in tag.attrs.items()}
        # Skip pure layout containers that carry no identifying signal.
        if name not in interactable and not (attrs.keys() & _IDENTIFYING_ATTRS):
            continue
        raw_id = tag.get("id")
        raw_classes = tag.get("class")
        elements.append(
            DomElement(
                tag=name,
                element_id=raw_id if isinstance(raw_id, str) else None,
                classes=raw_classes if isinstance(raw_classes, list) else [],
                attributes=attrs,
                text=tag.get_text(strip=True)[:160],
            )
        )
    return elements


_IDENTIFYING_ATTRS = {
    "id",
    "data-testid",
    "data-test-id",
    "data-test",
    "data-qa",
    "name",
    "aria-label",
    "role",
    "placeholder",
}


def snapshot_hash(html: str) -> str:
    """Stable content hash of a DOM snapshot for deduplicating healing events."""
    return hashlib.sha256((html or "").encode("utf-8")).hexdigest()
