"""Plain-dict payload builders for the integration suite.

These mirror the Pydantic ``*Create`` DTOs (``UserCreate``, ``SuiteCreate``,
``TestCaseCreate``/``StepSpec``, ``RunCreate``) but stay as dicts on purpose: the
API is the unit under test, so we let *it* validate the wire payloads. Each
builder takes keyword overrides for the few fields a given test cares about.

The suite factory deliberately mixes selector kinds so a run exercises the
self-healing engine end to end:

* a **stable** ``[data-testid=...]`` locator -> survives DOM drift -> PASSED.
* a **brittle** ``#id`` locator -> drifts -> the heuristic healer recovers it
  from the rebuilt DOM (the simulated page re-renders a ``data-testid`` node
  carrying the step's text, which matches the healing ``context``) -> HEALED.
"""

from __future__ import annotations

import uuid


def _unique_email() -> str:
    # ``example.com`` is reserved for examples and passes email-validator; the
    # ``.test`` TLD is rejected as a special-use/reserved name.
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def user_create(
    *,
    email: str | None = None,
    full_name: str = "Ed Engineer",
    password: str = "super-secret-pw",
    role: str = "engineer",
) -> dict:
    """Payload for ``POST /auth/register`` (UserCreate)."""
    return {
        "email": email or _unique_email(),
        "full_name": full_name,
        "password": password,
        "role": role,
    }


def stable_case(name: str = "Login — stable locators") -> dict:
    """A case whose steps all use stable ``[data-testid]`` locators (PASS)."""
    return {
        "name": name,
        "order_index": 0,
        "steps": [
            {"action": "navigate", "value": "/login"},
            {
                "action": "fill",
                "selector": "[data-testid='username']",
                "value": "ada@example.com",
            },
            {
                "action": "click",
                "selector": "[data-testid='submit']",
                "expected": "Sign in",
            },
            {
                "action": "assert_text",
                "selector": "[data-testid='welcome']",
                "expected": "Welcome back",
            },
        ],
    }


def brittle_case(name: str = "Checkout — brittle #id locator") -> dict:
    """A case with a brittle ``#id`` locator that drifts and must be HEALED.

    The ``expected`` text gives the healer a recoverable signal: the simulated
    executor re-renders the element with that text and a ``data-testid``, and the
    healing context (the step's expected text) matches it, so the heuristic
    proposes a robust ``[data-testid]`` selector.
    """
    return {
        "name": name,
        "order_index": 1,
        "steps": [
            {
                "action": "click",
                "selector": "#place-order-button",
                "expected": "Place order",
            },
        ],
    }


def suite_create(
    *,
    name: str = "Aegis Demo Suite",
    slug: str | None = None,
    target_base_url: str = "https://shop.example.com",
    tags: list[str] | None = None,
    cases: list[dict] | None = None,
) -> dict:
    """Payload for ``POST /suites`` (SuiteCreate) with a mix of cases."""
    return {
        "name": name,
        "slug": slug or f"suite-{uuid.uuid4().hex[:10]}",
        "description": "Integration-test fixture suite.",
        "target_base_url": target_base_url,
        "tags": tags if tags is not None else ["smoke", "checkout"],
        "cases": cases if cases is not None else [stable_case(), brittle_case()],
    }


def test_case_create(
    *, name: str = "Added later", order_index: int = 5, steps: list[dict] | None = None
) -> dict:
    """Payload for ``POST /suites/{id}/cases`` (TestCaseCreate)."""
    return {
        "name": name,
        "order_index": order_index,
        "steps": steps
        if steps is not None
        else [{"action": "assert_visible", "selector": "[data-testid='banner']"}],
    }


def run_create(*, trigger: str = "manual") -> dict:
    """Payload for ``POST /suites/{id}/runs`` (RunCreate)."""
    return {"trigger": trigger}
