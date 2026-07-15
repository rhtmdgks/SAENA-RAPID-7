"""Shared builders for the w5-06 B-gate unit tests.

Deterministic, pure constructors only — no fixtures with hidden state. The
default builders produce a *sufficient, evidence-intact, on-time* context so
each test can perturb exactly one axis and assert the resulting verdict flip
(guard-mutation friendly).
"""

from __future__ import annotations

from typing import Any

from saena_domain.measurement.b_gate import (
    EvidenceCheck,
    GatePolicy,
    PolicyProvenance,
    SignalResult,
    WindowState,
)
from saena_domain.measurement.outcome_layer import OutcomeLayer


def signal(
    layer: OutcomeLayer,
    *,
    basis: str | None = None,
    treatment_raw_delta: float = 1.0,
    control_raw_delta: float = 0.0,
    net_of_control_lift: float = 1.0,
    has_control_adjusted_lift: bool = True,
    sufficient_data: bool = True,
    has_raw_evidence_ref: bool = True,
) -> SignalResult:
    return SignalResult(
        layer=layer,
        evidence_basis_id=basis if basis is not None else f"basis-{layer.value}",
        treatment_raw_delta=treatment_raw_delta,
        control_raw_delta=control_raw_delta,
        net_of_control_lift=net_of_control_lift,
        has_control_adjusted_lift=has_control_adjusted_lift,
        sufficient_data=sufficient_data,
        has_raw_evidence_ref=has_raw_evidence_ref,
    )


def two_independent_positive() -> tuple[SignalResult, ...]:
    """Two distinct layers, distinct bases, both strictly-positive net lift."""
    return (
        signal(OutcomeLayer.CITATION, basis="basis-A"),
        signal(OutcomeLayer.PROMINENCE, basis="basis-B"),
    )


def intact_evidence() -> EvidenceCheck:
    return EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True)


def healthy_window() -> WindowState:
    return WindowState(complete=True, deployment_confirmed=True)


def production_policy(**overrides: Any) -> GatePolicy:
    base: dict[str, Any] = {
        "version": "grs-v1",
        "hash": "sha256:" + "0" * 64,
        "provenance": PolicyProvenance.PRODUCTION,
    }
    base.update(overrides)
    return GatePolicy(**base)


def fixture_policy(**overrides: Any) -> GatePolicy:
    base: dict[str, Any] = {
        "version": "grs-test",
        "hash": "sha256:" + "f" * 64,
        "provenance": PolicyProvenance.TEST_FIXTURE,
    }
    base.update(overrides)
    return GatePolicy(**base)
