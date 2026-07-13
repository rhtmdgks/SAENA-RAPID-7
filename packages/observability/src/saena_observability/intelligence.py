"""Wave 4 (Intelligence) metric/span name constants + attribute allowlist
helper (w4-15).

Registers the `saena.<domain>.<name>` metric names and
`saena.<capability>.<operation>` span names for the six intelligence
workloads named in the w4-15 mission:

- demand-graph builds (services/intelligence/demand-graph-service, w4-02)
- entity-resolution runs (services/intelligence/entity-resolution-service,
  w4-03)
- claim-evidence ledger / publishability evaluation
  (services/intelligence/claim-evidence-service, w4-04)
- citation normalization (services/intelligence/citation-intelligence-service,
  w4-05)
- browser-pool observation capture
  (services/acquisition/chatgpt-observer-service, w4-08)
- experiment registration (packages/domain/src/saena_domain/experiment +
  services/experimentation/experiment-attribution-service, w4-09)

Every name below is validated at import time via
`saena_observability.naming.validate_metric_name` /
`validate_span_name` — a typo that breaks the `saena.<domain>.<name>` /
`saena.<capability>.<operation>` shape fails at collection time, not
silently at emit time.

**Scope discipline (CLAUDE.md W4 constraints)**: every metric below is a
counter, gauge, or latency/duration histogram — operational/health
telemetry only. There is deliberately NO outcome/lift/DiD/causal-estimate
metric here (that is Wave 5 scope, `saena_domain.experiment.models.
FORBIDDEN_OUTCOME_TOKENS` pins the same discipline at the domain-model
level); `test_intelligence.py`'s `test_no_forbidden_outcome_tokens_in_any_metric_name`
asserts this as an executable regression guard, not just a comment.

**Attribute discipline**: this module also exposes
`INTELLIGENCE_ATTRIBUTE_NAMES`, the frozenset of every `saena.*` attribute
name a caller emitting one of these spans/metrics/logs is expected to use
(a subset of the full registry in `registry/attributes.yaml`/
`attributes.json` — the W0 core set plus the w4-15 additions). This is a
convenience constant only; `saena_observability.redaction.decide_redaction`
remains the single enforcement point (allowlist-first against the full
registry), not this module.
"""

from __future__ import annotations

from saena_observability.naming import validate_metric_name, validate_span_name

# ---------------------------------------------------------------------------
# demand-graph builds (w4-02)
# ---------------------------------------------------------------------------

METRIC_DEMAND_GRAPH_BUILD_TOTAL = "saena.demand_graph.build_total"
"""Counter: number of `build_demand_graph` invocations, by outcome."""

METRIC_DEMAND_GRAPH_CLUSTER_COUNT = "saena.demand_graph.cluster_count"
"""Gauge/histogram: number of `QueryCluster`s produced by one build."""

METRIC_DEMAND_GRAPH_BUILD_DURATION_SECONDS = "saena.demand_graph.build_duration_seconds"
"""Histogram: wall-clock duration of one `build_demand_graph` call."""

SPAN_DEMAND_GRAPH_BUILD = "saena.demand_graph.build"
"""Span: one `build_demand_graph` call."""

# ---------------------------------------------------------------------------
# entity-resolution runs (w4-03)
# ---------------------------------------------------------------------------

METRIC_ENTITY_RESOLUTION_RUN_TOTAL = "saena.entity_resolution.run_total"
"""Counter: number of `resolve_entities` invocations, by outcome."""

METRIC_ENTITY_RESOLUTION_ENTITY_COUNT = "saena.entity_resolution.entity_count"
"""Gauge/histogram: number of `EntityRecord`s produced by one run."""

METRIC_ENTITY_RESOLUTION_RUN_DURATION_SECONDS = "saena.entity_resolution.run_duration_seconds"
"""Histogram: wall-clock duration of one `resolve_entities` call."""

SPAN_ENTITY_RESOLUTION_RUN = "saena.entity_resolution.run"
"""Span: one `resolve_entities` call."""

# ---------------------------------------------------------------------------
# claim-evidence ledger / publishability (w4-04)
# ---------------------------------------------------------------------------

METRIC_CLAIM_EVIDENCE_CLAIM_APPENDED_TOTAL = "saena.claim_evidence.claim_appended_total"
"""Counter: number of `append_claim` calls that appended a NEW ledger entry
(no-op replays are not counted — see `append_claim` docstring)."""

METRIC_CLAIM_EVIDENCE_EVIDENCE_APPENDED_TOTAL = "saena.claim_evidence.evidence_appended_total"
"""Counter: number of `append_evidence` calls that appended a NEW ledger
entry."""

METRIC_CLAIM_EVIDENCE_PUBLISHABILITY_EVALUATED_TOTAL = (
    "saena.claim_evidence.publishability_evaluated_total"
)
"""Counter: number of `evaluate_claim_publishability` evaluations, by
`saena.claim_publishable` outcome (boolean attribute, never claim content)."""

METRIC_CLAIM_EVIDENCE_LEDGER_INTEGRITY_CHECK_TOTAL = (
    "saena.claim_evidence.ledger_integrity_check_total"
)
"""Counter: number of `verify_ledger_chain` calls, by pass/fail outcome."""

SPAN_CLAIM_EVIDENCE_APPEND_CLAIM = "saena.claim_evidence.append_claim"
"""Span: one `append_claim` call."""

SPAN_CLAIM_EVIDENCE_APPEND_EVIDENCE = "saena.claim_evidence.append_evidence"
"""Span: one `append_evidence` call."""

SPAN_CLAIM_EVIDENCE_EVALUATE_PUBLISHABILITY = "saena.claim_evidence.evaluate_publishability"
"""Span: one `evaluate_claim_publishability` call."""

# ---------------------------------------------------------------------------
# citation normalization (w4-05)
# ---------------------------------------------------------------------------

METRIC_CITATION_NORMALIZE_TOTAL = "saena.citation.normalize_total"
"""Counter: number of `normalize_url` calls, by outcome (success/
`UrlNormalizationError`)."""

METRIC_CITATION_NORMALIZE_DURATION_SECONDS = "saena.citation.normalize_duration_seconds"
"""Histogram: wall-clock duration of one `normalize_url` call."""

SPAN_CITATION_NORMALIZE = "saena.citation.normalize"
"""Span: one `normalize_url` call."""

# ---------------------------------------------------------------------------
# browser-pool observation capture (w4-08)
# ---------------------------------------------------------------------------

METRIC_BROWSER_POOL_SESSION_ACQUIRE_TOTAL = "saena.browser_pool.session_acquire_total"
"""Counter: number of `BrowserPool.acquire` calls, by outcome (success/
`BrowserPoolExhaustedError`)."""

METRIC_BROWSER_POOL_SESSION_RECYCLE_TOTAL = "saena.browser_pool.session_recycle_total"
"""Counter: number of sessions recycled on `release` (unhealthy or
exceeded `max_uses_per_session`)."""

METRIC_BROWSER_POOL_ACTIVE_SESSIONS = "saena.browser_pool.active_sessions"
"""Gauge: number of currently acquired (in-use) sessions."""

METRIC_BROWSER_POOL_OBSERVATION_CAPTURED_TOTAL = "saena.browser_pool.observation_captured_total"
"""Counter: number of `PlatformObservation` captures completed, by
`saena.engine_id` (closed enum, chatgpt-search only)."""

SPAN_BROWSER_POOL_ACQUIRE = "saena.browser_pool.acquire"
"""Span: one `BrowserPool.acquire` call."""

SPAN_BROWSER_POOL_CAPTURE_OBSERVATION = "saena.browser_pool.capture_observation"
"""Span: one observation-capture cycle (render + store)."""

# ---------------------------------------------------------------------------
# experiment registration (w4-09)
# ---------------------------------------------------------------------------

METRIC_EXPERIMENT_REGISTER_TOTAL = "saena.experiment.register_total"
"""Counter: number of `saena_domain.experiment.ledger.register` calls, by
outcome (new/no-op-replay/`ConflictError`/`RejectedError`)."""

METRIC_EXPERIMENT_LEDGER_VERIFY_TOTAL = "saena.experiment.ledger_verify_total"
"""Counter: number of experiment-ledger chain verifications, by pass/fail
outcome."""

SPAN_EXPERIMENT_REGISTER = "saena.experiment.register"
"""Span: one experiment-registration `register` call."""

# ---------------------------------------------------------------------------
# Aggregated name sets
# ---------------------------------------------------------------------------

INTELLIGENCE_METRIC_NAMES: frozenset[str] = frozenset(
    {
        METRIC_DEMAND_GRAPH_BUILD_TOTAL,
        METRIC_DEMAND_GRAPH_CLUSTER_COUNT,
        METRIC_DEMAND_GRAPH_BUILD_DURATION_SECONDS,
        METRIC_ENTITY_RESOLUTION_RUN_TOTAL,
        METRIC_ENTITY_RESOLUTION_ENTITY_COUNT,
        METRIC_ENTITY_RESOLUTION_RUN_DURATION_SECONDS,
        METRIC_CLAIM_EVIDENCE_CLAIM_APPENDED_TOTAL,
        METRIC_CLAIM_EVIDENCE_EVIDENCE_APPENDED_TOTAL,
        METRIC_CLAIM_EVIDENCE_PUBLISHABILITY_EVALUATED_TOTAL,
        METRIC_CLAIM_EVIDENCE_LEDGER_INTEGRITY_CHECK_TOTAL,
        METRIC_CITATION_NORMALIZE_TOTAL,
        METRIC_CITATION_NORMALIZE_DURATION_SECONDS,
        METRIC_BROWSER_POOL_SESSION_ACQUIRE_TOTAL,
        METRIC_BROWSER_POOL_SESSION_RECYCLE_TOTAL,
        METRIC_BROWSER_POOL_ACTIVE_SESSIONS,
        METRIC_BROWSER_POOL_OBSERVATION_CAPTURED_TOTAL,
        METRIC_EXPERIMENT_REGISTER_TOTAL,
        METRIC_EXPERIMENT_LEDGER_VERIFY_TOTAL,
    }
)

INTELLIGENCE_SPAN_NAMES: frozenset[str] = frozenset(
    {
        SPAN_DEMAND_GRAPH_BUILD,
        SPAN_ENTITY_RESOLUTION_RUN,
        SPAN_CLAIM_EVIDENCE_APPEND_CLAIM,
        SPAN_CLAIM_EVIDENCE_APPEND_EVIDENCE,
        SPAN_CLAIM_EVIDENCE_EVALUATE_PUBLISHABILITY,
        SPAN_CITATION_NORMALIZE,
        SPAN_BROWSER_POOL_ACQUIRE,
        SPAN_BROWSER_POOL_CAPTURE_OBSERVATION,
        SPAN_EXPERIMENT_REGISTER,
    }
)

#: Every `saena.*` attribute name relevant to the six intelligence
#: workloads above — the W0 core required-attribute set plus the w4-15
#: registry additions (`attributes.yaml`). This is a documentation/
#: convenience constant; `saena_observability.redaction.decide_redaction`
#: (driven by the full `registry/attributes.json`) is the actual
#: allowlist-enforcement point, not this frozenset.
INTELLIGENCE_ATTRIBUTE_NAMES: frozenset[str] = frozenset(
    {
        "saena.tenant_id",
        "saena.run_id",
        "saena.engine_id",
        "saena.context",
        "saena.demand_graph_version",
        "saena.entity_graph_version",
        "saena.claim_id",
        "saena.evidence_id",
        "saena.claim_publishable",
        "saena.citation_normalized_uri_hash",
        "saena.browser_pool_state",
        "saena.experiment_id",
        "saena.intent_label",
    }
)

# Fail collection (not just at first call) if any name above regresses on
# the `saena.<domain>.<name>` / `saena.<capability>.<operation>` naming
# rule — a typo here must never silently ship.
for _metric_name in INTELLIGENCE_METRIC_NAMES:
    validate_metric_name(_metric_name)
for _span_name in INTELLIGENCE_SPAN_NAMES:
    validate_span_name(_span_name)
del _metric_name, _span_name


__all__ = [
    "INTELLIGENCE_ATTRIBUTE_NAMES",
    "INTELLIGENCE_METRIC_NAMES",
    "INTELLIGENCE_SPAN_NAMES",
    "METRIC_BROWSER_POOL_ACTIVE_SESSIONS",
    "METRIC_BROWSER_POOL_OBSERVATION_CAPTURED_TOTAL",
    "METRIC_BROWSER_POOL_SESSION_ACQUIRE_TOTAL",
    "METRIC_BROWSER_POOL_SESSION_RECYCLE_TOTAL",
    "METRIC_CITATION_NORMALIZE_DURATION_SECONDS",
    "METRIC_CITATION_NORMALIZE_TOTAL",
    "METRIC_CLAIM_EVIDENCE_CLAIM_APPENDED_TOTAL",
    "METRIC_CLAIM_EVIDENCE_EVIDENCE_APPENDED_TOTAL",
    "METRIC_CLAIM_EVIDENCE_LEDGER_INTEGRITY_CHECK_TOTAL",
    "METRIC_CLAIM_EVIDENCE_PUBLISHABILITY_EVALUATED_TOTAL",
    "METRIC_DEMAND_GRAPH_BUILD_DURATION_SECONDS",
    "METRIC_DEMAND_GRAPH_BUILD_TOTAL",
    "METRIC_DEMAND_GRAPH_CLUSTER_COUNT",
    "METRIC_ENTITY_RESOLUTION_ENTITY_COUNT",
    "METRIC_ENTITY_RESOLUTION_RUN_DURATION_SECONDS",
    "METRIC_ENTITY_RESOLUTION_RUN_TOTAL",
    "METRIC_EXPERIMENT_LEDGER_VERIFY_TOTAL",
    "METRIC_EXPERIMENT_REGISTER_TOTAL",
    "SPAN_BROWSER_POOL_ACQUIRE",
    "SPAN_BROWSER_POOL_CAPTURE_OBSERVATION",
    "SPAN_CITATION_NORMALIZE",
    "SPAN_CLAIM_EVIDENCE_APPEND_CLAIM",
    "SPAN_CLAIM_EVIDENCE_APPEND_EVIDENCE",
    "SPAN_CLAIM_EVIDENCE_EVALUATE_PUBLISHABILITY",
    "SPAN_DEMAND_GRAPH_BUILD",
    "SPAN_ENTITY_RESOLUTION_RUN",
    "SPAN_EXPERIMENT_REGISTER",
]
