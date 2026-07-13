"""Shared fixtures/builders for saena_domain.experiment tests."""

from __future__ import annotations

from typing import Any

from saena_domain.experiment.models import (
    ExperimentArm,
    ExperimentRegistration,
    MetricDefinition,
)


def asset_design_arms() -> tuple[ExperimentArm, ...]:
    return (
        ExperimentArm(arm_id="arm-baseline", role="baseline", asset_ref="sha256:" + "a" * 64),
        ExperimentArm(arm_id="arm-treatment", role="treatment", asset_ref="sha256:" + "b" * 64),
    )


def matched_cluster_arms() -> tuple[ExperimentArm, ...]:
    return (
        ExperimentArm(arm_id="arm-baseline", role="baseline", query_cluster_ref="qc-1"),
        ExperimentArm(arm_id="arm-matched", role="matched_cluster", query_cluster_ref="qc-2"),
    )


def metric_definitions() -> tuple[MetricDefinition, ...]:
    return (MetricDefinition(metric_id="citation_presence", description="cited in response"),)


def registration(**overrides: Any) -> ExperimentRegistration:
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
        "asset_hash": "sha256:" + "c" * 64,
        "code_version_hash": "sha256:" + "d" * 64,
        "created_by": "actor-b-dept-01",
        "approved_by": "actor-approver-01",
        "created_at": "2026-07-13T09:00:00Z",
    }
    base.update(overrides)
    return ExperimentRegistration(**base)
