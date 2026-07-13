"""Record factory helpers for `saena_domain.measurement.ports` unit tests (w5-09).

Imported by its own unique dotted name (`measurement_factories`, inserted onto
`sys.path` by this directory's `conftest.py`) rather than as a second
`conftest` module — same collision-avoidance rationale as
`tests/unit/domain_persistence/persistence_factories.py`.
"""

from __future__ import annotations

from typing import Any

from saena_domain.measurement.ports import (
    ConfirmationRecord,
    EvidenceBundle,
    MeasurementWindow,
    OutcomeDecisionRecord,
)

TENANT_A = "acme-co"
TENANT_B = "globex-co"


def make_confirmation(**overrides: Any) -> ConfirmationRecord:
    """A schema-valid `ConfirmationRecord` with deterministic defaults."""
    base: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "confirmation_key": "acme-co:run-0007:capsule-042",
        "measurement_kind": "citation_confirmation",
        "payload": {"citation_id": "cit-042", "confirmed_at": "2026-07-14T09:00:00Z"},
    }
    base.update(overrides)
    return ConfirmationRecord(**base)


def make_window(**overrides: Any) -> MeasurementWindow:
    """A schema-valid `MeasurementWindow` (active, no end) with defaults."""
    base: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "experiment_id": "exp-042",
        "starts_at": "2026-07-14T00:00:00Z",
        "ends_at": None,
        "policy_version": "1.0.0",
    }
    base.update(overrides)
    return MeasurementWindow(**base)


def make_decision(**overrides: Any) -> OutcomeDecisionRecord:
    """A schema-valid `OutcomeDecisionRecord` — decision + evidence ref +
    policy metadata bound into ONE frozen record (no partial-state API)."""
    base: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "decision_key": ("exp-042", "primary"),
        "outcome": "lift_confirmed",
        "evidence_bundle_ref": "sha256:" + "a" * 64,
        "policy_metadata": {"policy_version": "1.0.0", "gate": "quality-eval"},
    }
    base.update(overrides)
    return OutcomeDecisionRecord(**base)


def make_bundle(**overrides: Any) -> EvidenceBundle:
    """A schema-valid `EvidenceBundle` (content payload only — the
    manifest_hash is supplied separately to `put`, content-addressed)."""
    base: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "manifest": {"artifacts": ["sha256:" + "b" * 64], "count": 1},
    }
    base.update(overrides)
    return EvidenceBundle(**base)
