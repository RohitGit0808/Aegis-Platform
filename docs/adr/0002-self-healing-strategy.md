# ADR 0002 — Self-healing strategy (heuristic-first, LLM fallback, hybrid)

## Status

Accepted

## Context

UI tests break when locators drift: a `#id` is renamed, a class is restyled, a
DOM is restructured. Aegis's core value is recovering the *intended* element
automatically and recording an auditable healing event.

There is a real tension between approaches:

- A pure **heuristic** matcher is fast, free, deterministic and offline — but
  limited on genuinely ambiguous DOM changes.
- A pure **LLM** matcher generalises well — but adds latency and per-call cost,
  can be non-deterministic, may refuse, and introduces an external dependency
  that can fail. It also cannot be a hard requirement, because a product
  constraint is that the platform must run with **no API key** configured.

We also need a principled way to decide when a machine-proposed locator is
trustworthy enough to apply automatically versus when a human should review it.

## Decision

Adopt a **heuristic-first, LLM-fallback, hybrid-merge** engine
(`aegis.healing.engine.SelfHealingEngine`) gated by a single confidence
threshold, `healing_min_confidence` (default **0.6**).

1. **Heuristic first** (`HeuristicHealer`): score every candidate element in the
   DOM snapshot against the broken selector's signals and synthesise the most
   robust selector for the winner. Weights sum to 1.0, with the most stable
   signal dominating: `data-testid` **0.60**, `id` 0.18, text 0.10, class 0.07,
   tag 0.03, other attrs 0.02. A single exact `data-testid` match clears the
   default threshold on its own — matching real-world locator best practice.
2. **LLM fallback** (`ClaudeHealingLLM`, `claude-opus-4-8`): consulted **only**
   when the heuristic's confidence is below the threshold. Constrained to a
   strict JSON schema (structured outputs) so the response is always parseable.
3. **Hybrid merge** (`_combine`): if heuristic and LLM independently agree on the
   same selector, tag the result `HYBRID` and boost confidence by `+0.1`
   (capped at 1.0); otherwise the higher-confidence proposal wins.
4. **Confidence threshold → human review**: the executor auto-accepts a heal
   (`HealingEvent.accepted = True`) when `confidence >= threshold`; below it the
   event is left `accepted = None` (pending) and surfaced for review via
   `POST /healing/{event_id}/review`.
5. **Graceful degradation**: with no `AEGIS_ANTHROPIC_API_KEY`, `build_llm()`
   returns `NullHealingLLM` and the engine is heuristic-only — no code change.
   The Claude call is fronted by a 20s timeout and a circuit breaker
   (`failure_threshold=4`); any failure logs a warning and falls back to the
   heuristic proposal.

Every attempt is recorded to Prometheus
(`aegis_healing_attempts_total{strategy,outcome}`, `aegis_healing_confidence`)
and persisted as a `HealingEvent` with strategy, confidence, rationale and a DOM
snapshot hash for audit.

## Consequences

**Positive**
- The common case (a stable `data-testid` exists) is resolved instantly, for free,
  offline — the LLM is never even called.
- The LLM adds recall exactly where the heuristic is weak, without paying its cost
  or latency on every step.
- The platform runs identically with or without an API key; an LLM outage
  degrades to heuristic-only rather than failing runs.
- One tunable (`healing_min_confidence`) governs LLM invocation, auto-accept, and
  review routing — easy to reason about and adjust per environment.
- Full auditability: strategy, confidence and rationale are persisted per event.

**Negative / trade-offs**
- The heuristic weights are hand-tuned; pathological DOMs may need re-tuning.
- The threshold is a blunt single knob — the same value gates very different
  decisions (consult LLM vs auto-accept).
- LLM proposals are non-deterministic, complicating exact-output assertions in
  tests (mitigated by the `HealingLLM` protocol + `NullHealingLLM` in tests).
- A truly structural-only locator (no recoverable signal, e.g.
  `div > div:nth-child(3)`) still cannot heal and fails honestly — by design.

## Alternatives considered

- **Pure heuristic, no LLM** — cheapest and fully deterministic, but lower recall
  on ambiguous changes; rejected as the *sole* strategy (kept as the first line).
- **Pure LLM for every heal** — best recall but adds cost/latency to every step,
  introduces non-determinism and a hard external dependency, and violates the
  zero-key run constraint. Rejected.
- **Always run both and merge** — wasteful: the LLM is unnecessary when the
  heuristic is already confident. We merge only on the fallback path.
- **Record-and-replay / locator versioning** — orthogonal and heavier; could
  complement this engine later but doesn't address novel DOM drift.
