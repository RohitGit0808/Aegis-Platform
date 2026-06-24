"""Run executor — the heart of the platform.

Executes a queued :class:`TestRun` end to end: for each step it simulates
running the locator against the page's current DOM, and when a selector has
*drifted* (no longer matches) it invokes the :class:`SelfHealingEngine` to
recover a robust locator, retries, and records the healing event. Progress is
streamed to subscribers over the cache pub/sub channel so the UI sees results
live. The simulated browser keeps the whole platform runnable with no external
services while exercising every real code path (DB, healing, metrics, events).

Simulation contract (deterministic, no real browser):
  * Steps with a stable locator (``[data-testid=…]``, class- or attribute-based)
    pass cleanly — those selectors survive DOM change.
  * Steps that pin a brittle signal (an ``#id`` or a pure structural path) have
    *drifted*; the healer attempts recovery from the captured DOM snapshot.
  * A drifted selector that still carries recoverable signal (a test-id, classes)
    heals with high confidence and the step is marked HEALED; one with no signal
    (e.g. ``div > div:nth-child(3)``) cannot be healed and the step FAILS.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from aegis.cache.redis import get_cache
from aegis.core.config import settings
from aegis.core.logging import get_logger
from aegis.core.metrics import ACTIVE_RUNS, RUN_DURATION, RUNS_TOTAL, WORKER_TASKS
from aegis.db.models import HealingEvent, StepResult
from aegis.db.session import SessionLocal
from aegis.domain.enums import RunStatus, StepAction, StepStatus
from aegis.domain.schemas import StepSpec
from aegis.healing.dom import SelectorHints, parse_selector, snapshot_hash
from aegis.healing.engine import SelfHealingEngine
from aegis.repositories.runs import RunRepository
from aegis.repositories.suites import SuiteRepository

log = get_logger(__name__)

_STABLE_ATTRS = ("name", "aria-label", "placeholder", "role", "type")
_TAG_FOR_ACTION = {
    StepAction.CLICK: "button",
    StepAction.FILL: "input",
    StepAction.ASSERT_TEXT: "span",
    StepAction.ASSERT_VISIBLE: "div",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _is_stable(hints: SelectorHints) -> bool:
    """A locator is stable if it survives DOM change (no brittle #id / structure)."""
    if hints.element_id:
        return False
    if hints.test_id or hints.classes:
        return True
    return any(hints.attributes.get(attr) for attr in _STABLE_ATTRS)


@dataclass(slots=True)
class StepOutcome:
    drifted: bool
    clean: bool
    duration_ms: int


class SimulatedStepExecutor:
    """A deterministic stand-in for a real browser driver (Playwright/Selenium)."""

    def build_page(self, steps: list[StepSpec]) -> str:
        """Render the page's *current* DOM from a case's steps."""
        nodes: list[str] = []
        for index, step in enumerate(steps):
            if step.selector is None or step.action in (StepAction.NAVIGATE, StepAction.WAIT):
                continue
            hints = parse_selector(step.selector)
            testid = hints.test_id or f"tid-{index}"
            tag = _TAG_FOR_ACTION.get(step.action, "div")
            # Only carry real text signal — never the action name, or unrelated
            # elements would all share text and "heal" to each other.
            text = step.expected or step.value or ""
            classes = " ".join(sorted(hints.classes))
            class_attr = f' class="{classes}"' if classes else ""
            nodes.append(f'<{tag} data-testid="{testid}"{class_attr}>{text}</{tag}>')
        return "<html><body><main>" + "".join(nodes) + "</main></body></html>"

    def run_step(self, step: StepSpec, index: int) -> StepOutcome:
        duration = 15 + (index % 5) * 7  # deterministic pseudo-latency
        if step.selector is None or step.action in (StepAction.NAVIGATE, StepAction.WAIT):
            return StepOutcome(drifted=False, clean=True, duration_ms=duration)
        hints = parse_selector(step.selector)
        if _is_stable(hints):
            return StepOutcome(drifted=False, clean=True, duration_ms=duration)
        return StepOutcome(drifted=True, clean=False, duration_ms=duration)


async def _publish(run_id: uuid.UUID, event: str, payload: dict[str, Any]) -> None:
    """Best-effort live event; pub/sub failures never abort a run."""
    try:
        await get_cache().publish(f"run:{run_id}", json.dumps({"event": event, **payload}))
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("run.publish_failed", error=str(exc))


async def execute_run(run_id: uuid.UUID) -> None:
    """Execute a queued run to completion. Opens its own DB session."""
    async with SessionLocal() as session:
        runs = RunRepository(session)
        suites = SuiteRepository(session)

        run = await runs.get(run_id)
        if run is None or run.status != RunStatus.QUEUED:
            log.warning("run.skip", run_id=str(run_id), reason="missing or not queued")
            return
        suite = await suites.get_with_cases(run.suite_id)
        if suite is None:
            run.status = RunStatus.ERROR
            run.error = "Suite no longer exists."
            await session.commit()
            return

        run.status = RunStatus.RUNNING
        run.started_at = _now()
        ACTIVE_RUNS.inc()
        await session.commit()
        await _publish(run.id, "run.started", {"run_id": str(run.id), "suite": suite.slug})

        engine = SelfHealingEngine()
        executor = SimulatedStepExecutor()
        passed = failed = healed = 0
        started = perf_counter()

        try:
            for case in suite.cases:
                steps = [StepSpec.model_validate(s) for s in case.steps]
                page_html = executor.build_page(steps)
                for index, step in enumerate(steps):
                    outcome = executor.run_step(step, index)
                    status = StepStatus.PASSED
                    healed_selector: str | None = None
                    message: str | None = None

                    if outcome.drifted:
                        proposal = await engine.heal(
                            step.selector or "",
                            page_html,
                            context=step.expected or step.value,
                        )
                        event = HealingEvent(
                            run_id=run.id,
                            original_selector=step.selector or "",
                            healed_selector=proposal.healed_selector,
                            strategy=proposal.strategy,
                            confidence=proposal.confidence,
                            dom_snapshot_hash=snapshot_hash(page_html),
                            rationale=proposal.rationale,
                        )
                        if proposal.healed_selector is not None:
                            event.succeeded = True
                            event.accepted = (
                                True
                                if proposal.confidence >= settings.healing_min_confidence
                                else None
                            )
                            status = StepStatus.HEALED
                            healed_selector = proposal.healed_selector
                            message = f"Healed via {proposal.strategy.value}: {proposal.rationale}"
                            healed += 1
                        else:
                            event.succeeded = False
                            status = StepStatus.FAILED
                            message = "Selector drifted and could not be healed."
                            failed += 1
                        session.add(event)
                    elif outcome.clean:
                        passed += 1
                    else:  # pragma: no cover - defensive
                        status = StepStatus.FAILED
                        failed += 1

                    result = StepResult(
                        run_id=run.id,
                        case_id=case.id,
                        case_name=case.name,
                        step_index=index,
                        action=step.action,
                        status=status,
                        original_selector=step.selector,
                        healed_selector=healed_selector,
                        message=message,
                        duration_ms=outcome.duration_ms,
                    )
                    session.add(result)
                    await session.flush()
                    await _publish(
                        run.id,
                        "step.completed",
                        {
                            "case": case.name,
                            "step_index": index,
                            "status": status.value,
                            "healed_selector": healed_selector,
                        },
                    )

            run.passed_count = passed
            run.failed_count = failed
            run.healed_count = healed
            run.status = RunStatus.PASSED if failed == 0 else RunStatus.FAILED
        except Exception as exc:  # pragma: no cover - defensive
            run.status = RunStatus.ERROR
            run.error = str(exc)
            log.exception("run.error", run_id=str(run.id))
        finally:
            run.finished_at = _now()
            run.duration_ms = int((perf_counter() - started) * 1000)
            ACTIVE_RUNS.dec()
            RUNS_TOTAL.labels(status=run.status.value).inc()
            RUN_DURATION.observe(run.duration_ms / 1000.0)
            WORKER_TASKS.labels(task="execute_run", outcome=run.status.value).inc()
            await session.commit()
            await _publish(
                run.id,
                "run.finished",
                {
                    "status": run.status.value,
                    "passed": run.passed_count,
                    "failed": run.failed_count,
                    "healed": run.healed_count,
                    "duration_ms": run.duration_ms,
                },
            )
            log.info(
                "run.finished",
                run_id=str(run.id),
                status=run.status.value,
                passed=passed,
                failed=failed,
                healed=healed,
            )
