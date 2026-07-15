"""Shared REAL-container composition helpers for w5-19/c5-01 (`tests/integration/
measurement_e2e`).

Deliberately NOT named `conftest.py` (a second `conftest.py` under a sibling
test package collides under pytest's default `prepend` import mode — same
rationale `measurement_e2e_harness.py` and `intelligence_e2e_harness.py`
document for themselves). This module builds `MeasurementPorts` backed by the
REAL w5-10 Postgres adapters (via the sync facades in
`tests/integration/measurement_pg/sync_facade.py`) and helpers to project a
composed run's `ExperimentOutcome` into the REAL w5-11 ClickHouse
`measurement_outcome` table and to feed the REAL w5-16 skill-bank
`IntakeGuard`.

Every builder in `tests/e2e/measurement/measurement_e2e_harness.py` (scenario
shapes, registration/confirmation/signal fixtures) is reused verbatim here —
this module adds ONLY the real-I/O wiring the pure-synthetic lane does not
need. The composed pipeline call (`saena_experiment_attribution.pipeline.
run_measurement`) is the SAME production function in both lanes; only the
`MeasurementPorts` implementation differs (in-memory vs. real Postgres), which
is exactly the seam this lane exists to prove: a scenario that would pass
against the in-memory fake but silently diverge against the real adapters
(wrong SQL, wrong idempotency semantics, a value that does not round-trip
through Postgres/asyncpg type coercion) fails HERE, not in production.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_MEASUREMENT_PG_DIR = _REPO_ROOT / "tests" / "integration" / "measurement_pg"
_E2E_HARNESS_DIR = _REPO_ROOT / "tests" / "e2e" / "measurement"
_ATTRIBUTION_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "experiment-attribution-service" / "src"
)
_SKILL_BANK_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "strategy-skill-bank-service" / "src"
)

for _p in (_MEASUREMENT_PG_DIR, _E2E_HARNESS_DIR, _ATTRIBUTION_SRC, _SKILL_BANK_SRC, _THIS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from measurement_e2e_harness import (  # noqa: E402
    ENGINE_ID,
    TENANT_1,
    TENANT_2,
    AlwaysTrustVerifier,
    MeasurementScenario,
    accept_confirmation,
    build_deployment_confirmation,
    build_fraud_scenario,
    build_late_deployment_scenario,
    build_pass_scenario,
    build_registration,
    build_registration_view,
    build_submission,
    build_weights_policy,
    evaluate_intake,
    fetch_manifest,
    fraud_signal,
    make_clock_policy,
    make_did_policy,
    make_gate_policy,
    make_grs_bundle_deny,
    make_grs_bundle_eligible,
    make_policies,
    measurement_outcome_row_from_outcome,
    publish_outcome_event,
    qualifying_signal,
    run_pass_pipeline,
)
from saena_domain.measurement.evidence import EvidenceBundleManifest  # noqa: E402
from saena_experiment_attribution.pipeline.inputs import MeasurementPorts  # noqa: E402
from sync_facade import (  # noqa: E402  (tests/integration/measurement_pg/sync_facade.py)
    SyncPgConfirmationStore,
    SyncPgEvidenceBundleStore,
    SyncPgMeasurementWindowStore,
    SyncPgOutcomeDecisionStore,
)

__all__ = [
    "ENGINE_ID",
    "TENANT_1",
    "TENANT_2",
    "AlwaysTrustVerifier",
    "MeasurementScenario",
    "accept_confirmation",
    "build_deployment_confirmation",
    "build_fraud_scenario",
    "build_late_deployment_scenario",
    "build_pass_scenario",
    "build_registration",
    "build_registration_view",
    "build_submission",
    "build_weights_policy",
    "evaluate_intake",
    "fetch_manifest",
    "fraud_signal",
    "make_clock_policy",
    "make_did_policy",
    "make_gate_policy",
    "make_grs_bundle_deny",
    "make_grs_bundle_eligible",
    "make_pg_ports",
    "make_policies",
    "measurement_outcome_row_from_outcome",
    "project_outcome_to_clickhouse",
    "publish_outcome_event",
    "qualifying_signal",
    "read_back_manifest",
    "run_pass_pipeline",
]


def make_pg_ports(postgres_url: str) -> MeasurementPorts:
    """Build a `MeasurementPorts` backed by the REAL w5-10 Postgres adapters
    (via the sync facades) — this is the ONLY difference from
    `measurement_e2e_harness.make_in_memory_ports`: every other builder
    (registration/confirmation/signals/policies) is reused verbatim so both
    lanes drive `run_measurement` with byte-identical inputs, differing only
    in WHERE the pipeline's writes physically land.
    """
    return MeasurementPorts(
        confirmation_store=SyncPgConfirmationStore(postgres_url),
        window_store=SyncPgMeasurementWindowStore(postgres_url),
        decision_store=SyncPgOutcomeDecisionStore(postgres_url),
        evidence_store=SyncPgEvidenceBundleStore(postgres_url),
    )


def read_back_manifest(
    postgres_url: str, tenant_id: str, manifest_hash: str
) -> EvidenceBundleManifest:
    """Read the evidence bundle manifest back from a FRESH
    `SyncPgEvidenceBundleStore` instance (a new connection/engine, not the one
    the pipeline wrote through) — proving physical persistence, not merely
    in-process object identity. SF-4 re-verification runs inside
    `mapping.row_to_evidence_bundle` on this read, same as `fetch_manifest`
    against the in-memory store."""
    store = SyncPgEvidenceBundleStore(postgres_url)
    stored = store.get(tenant_id, manifest_hash)
    return EvidenceBundleManifest(**dict(stored.manifest))


def project_outcome_to_clickhouse(outcome, scenario, *, row_id: str):  # noqa: ANN001, ANN201
    """Build the `MeasurementOutcomeRow` the real ClickHouse store receives
    for this outcome — thin re-export of the pure-synthetic lane's own
    builder (`measurement_e2e_harness.measurement_outcome_row_from_outcome`)
    so container-lane tests import everything from this one module."""
    return measurement_outcome_row_from_outcome(outcome, scenario, row_id=row_id)
