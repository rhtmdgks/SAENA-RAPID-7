"""Shared builders for saena_domain.measurement.binding tests.

Every builder returns a fully-consistent, ACCEPT-path artifact; individual
tests mutate exactly one field to isolate the guard under test. Registrations
are run through the real W4 `register` so `anchored_hash`/`content_fingerprint`
are the genuine ledger-anchored values (never hand-stamped), which is what
makes the integrity-guard tests real rather than tautological.
"""

from __future__ import annotations

from typing import Any

from saena_domain.experiment.ledger import register
from saena_domain.experiment.models import (
    ExperimentArm,
    ExperimentRegistration,
    MetricDefinition,
)
from saena_domain.measurement.binding import (
    MeasurementCell,
    MeasurementMetricInput,
    MeasurementSubmission,
    Observation,
    compute_metric_fingerprint,
)

TREATMENT_ASSET = "sha256:" + "b" * 64
REGISTERED_ASSET_HASH = "sha256:" + "c" * 64


def asset_design_arms() -> tuple[ExperimentArm, ...]:
    return (
        ExperimentArm(arm_id="arm-baseline", role="baseline", asset_ref="sha256:" + "a" * 64),
        ExperimentArm(arm_id="arm-treatment", role="treatment", asset_ref=TREATMENT_ASSET),
        ExperimentArm(arm_id="arm-control", role="control", asset_ref="sha256:" + "e" * 64),
    )


def matched_cluster_arms() -> tuple[ExperimentArm, ...]:
    return (
        ExperimentArm(arm_id="arm-baseline", role="baseline", query_cluster_ref="qc-1"),
        ExperimentArm(arm_id="arm-matched", role="matched_cluster", query_cluster_ref="qc-2"),
    )


def metric_definitions() -> tuple[MetricDefinition, ...]:
    return (
        MetricDefinition(metric_id="citation_presence", description="cited in response"),
        MetricDefinition(metric_id="prominence_rank", description="position in answer"),
    )


def raw_registration(**overrides: Any) -> ExperimentRegistration:
    base: dict[str, Any] = {
        "experiment_id": "exp-2026-0713-0001",
        "tenant_id": "acme-co",
        "run_id": "run-2026-0713-0001",
        "arms": asset_design_arms(),
        "metric_definitions": metric_definitions(),
        "query_cluster_ref": "qc-primary",
        "locale": "en-US",
        "browser_policy": "desktop-default",
        "repeat_count": 5,
        "asset_hash": REGISTERED_ASSET_HASH,
        "code_version_hash": "sha256:" + "d" * 64,
        "created_by": "actor-b-dept-01",
        "approved_by": "actor-approver-01",
        "created_at": "2026-07-13T09:00:00Z",
    }
    base.update(overrides)
    return ExperimentRegistration(**base)


def anchored_registration(**overrides: Any) -> ExperimentRegistration:
    """A registration as STORED in a fresh ledger — hash/fingerprint populated."""
    _, entry = register((), raw_registration(**overrides))
    return entry


def registered_metric_inputs(
    registration: ExperimentRegistration,
) -> tuple[MeasurementMetricInput, ...]:
    return tuple(
        MeasurementMetricInput(
            metric_id=m.metric_id,
            metric_hash=compute_metric_fingerprint(m),
            weight=1.0,
        )
        for m in registration.metric_definitions
    )


def registered_weights() -> dict[str, float]:
    return {"citation_presence": 1.0, "prominence_rank": 1.0}


def matching_cell() -> MeasurementCell:
    return MeasurementCell(
        locale="en-US",
        browser_policy="desktop-default",
        query_cluster_ref="qc-primary",
        repeat_count=5,
    )


def clean_observations() -> tuple[Observation, ...]:
    cell = matching_cell()
    return (
        Observation(
            observation_id="obs-1",
            arm_id="arm-treatment",
            cell=cell,
            asset_hash=REGISTERED_ASSET_HASH,
        ),
        Observation(
            observation_id="obs-2",
            arm_id="arm-control",
            cell=cell,
            asset_hash=REGISTERED_ASSET_HASH,
        ),
    )


def submission(registration: ExperimentRegistration, **overrides: Any) -> MeasurementSubmission:
    from saena_domain.experiment.ledger import compute_content_fingerprint

    base: dict[str, Any] = {
        "experiment_id": registration.experiment_id,
        "tenant_id": registration.tenant_id,
        "anchored_hash": registration.canonical_hash,
        "content_fingerprint": compute_content_fingerprint(registration),
        "metrics": registered_metric_inputs(registration),
        "observations": clean_observations(),
    }
    base.update(overrides)
    return MeasurementSubmission(**base)
