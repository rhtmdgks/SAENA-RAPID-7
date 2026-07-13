"""Tests for saena_domain.experiment.models — ExperimentRegistration shape/validators."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from saena_domain.experiment.models import ExperimentArm, ExperimentRegistration

from .conftest import asset_design_arms, matched_cluster_arms, metric_definitions, registration


def test_registration_round_trips_all_named_fields() -> None:
    reg = registration()
    assert reg.experiment_id == "exp-2026-0713-0001"
    assert reg.tenant_id == "acme-co"
    assert reg.run_id == "run-2026-0713-0001"
    assert len(reg.arms) == 2
    assert len(reg.metric_definitions) == 1
    assert reg.query_cluster_ref == "qc-primary"
    assert reg.locale == "en-US"
    assert reg.browser_policy == "desktop-default"
    assert reg.repeat_count == 5
    assert reg.asset_hash.startswith("sha256:")
    assert reg.code_version_hash.startswith("sha256:")
    assert reg.created_by == "actor-b-dept-01"
    assert reg.approved_by == "actor-approver-01"
    assert reg.created_at is not None
    assert reg.canonical_hash is None
    assert reg.previous_hash is None


def test_tenant_id_is_mandatory() -> None:
    with pytest.raises(ValidationError):
        registration(tenant_id=None)


def test_registration_is_frozen() -> None:
    reg = registration()
    with pytest.raises(ValidationError):
        reg.repeat_count = 6


def test_registration_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        registration(unknown_field="nope")


# --- arm design validation -----------------------------------------------------------


def test_matched_cluster_design_accepted() -> None:
    reg = registration(arms=matched_cluster_arms())
    assert {arm.role for arm in reg.arms} == {"baseline", "matched_cluster"}


def test_asset_design_accepted() -> None:
    reg = registration(arms=asset_design_arms())
    assert {arm.role for arm in reg.arms} == {"baseline", "treatment"}


def test_arms_require_exactly_one_baseline() -> None:
    arms = (
        ExperimentArm(arm_id="a1", role="treatment", asset_ref="sha256:" + "a" * 64),
        ExperimentArm(arm_id="a2", role="control", asset_ref="sha256:" + "b" * 64),
    )
    with pytest.raises(ValidationError):
        registration(arms=arms)


def test_arms_require_at_least_one_non_baseline() -> None:
    arms = (
        ExperimentArm(arm_id="a1", role="baseline", asset_ref="sha256:" + "a" * 64),
        ExperimentArm(arm_id="a2", role="baseline", asset_ref="sha256:" + "b" * 64),
    )
    with pytest.raises(ValidationError):
        registration(arms=arms)


def test_arms_reject_mixed_asset_and_matched_cluster_design() -> None:
    arms = (
        ExperimentArm(arm_id="a1", role="baseline", asset_ref="sha256:" + "a" * 64),
        ExperimentArm(arm_id="a2", role="treatment", asset_ref="sha256:" + "b" * 64),
        ExperimentArm(arm_id="a3", role="matched_cluster", query_cluster_ref="qc-2"),
    )
    with pytest.raises(ValidationError):
        registration(arms=arms)


def test_arm_ids_must_be_unique() -> None:
    arms = (
        ExperimentArm(arm_id="dup", role="baseline", asset_ref="sha256:" + "a" * 64),
        ExperimentArm(arm_id="dup", role="treatment", asset_ref="sha256:" + "b" * 64),
    )
    with pytest.raises(ValidationError):
        registration(arms=arms)


def test_metric_definitions_require_at_least_one() -> None:
    with pytest.raises(ValidationError):
        ExperimentRegistration(
            experiment_id="exp-x",
            tenant_id="acme-co",
            run_id="run-x",
            arms=asset_design_arms(),
            metric_definitions=(),
            query_cluster_ref="qc-primary",
            locale="en-US",
            browser_policy="desktop-default",
            repeat_count=5,
            asset_hash="sha256:" + "c" * 64,
            code_version_hash="sha256:" + "d" * 64,
            created_by="actor-b-dept-01",
            approved_by="actor-approver-01",
            created_at=datetime(2026, 7, 13, 9, 0, 0, tzinfo=UTC),
        )


def test_repeat_count_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        registration(repeat_count=0)


def test_metric_definitions_present_from_conftest_helper() -> None:
    assert len(metric_definitions()) == 1
