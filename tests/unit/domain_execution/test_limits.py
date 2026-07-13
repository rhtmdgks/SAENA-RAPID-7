"""ResourceLimits — k3s spec §5.3 4-field carrier, per-JobKind defaults,
values.yaml conformance for JobKind.AGENT_RUNNER, and validation rejection."""

from __future__ import annotations

import pytest
from saena_domain.execution.errors import ResourceLimitsValidationError
from saena_domain.execution.job_kind import JobKind
from saena_domain.execution.limits import (
    DEFAULT_RESOURCE_LIMITS,
    ResourceLimits,
    resource_limits_for,
)


def test_every_job_kind_has_default_resource_limits() -> None:
    assert set(DEFAULT_RESOURCE_LIMITS.keys()) == set(JobKind)
    for kind in JobKind:
        assert resource_limits_for(kind) is DEFAULT_RESOURCE_LIMITS[kind]


def test_agent_runner_limits_match_values_yaml_verbatim() -> None:
    # deploy/charts/saena-forge/values.yaml agentRunner.job.activeDeadlineSeconds
    # / agentRunner.limits.{maxCostUsdPerRun,maxArtifactsMiBPerRun}
    limits = resource_limits_for(JobKind.AGENT_RUNNER)
    assert limits.active_deadline_seconds == 7200
    assert limits.max_cost_usd == 100
    assert limits.max_artifact_mib == 1024


def test_valid_resource_limits_construct() -> None:
    limits = ResourceLimits(
        active_deadline_seconds=60, max_retries=1, max_artifact_mib=1, max_cost_usd=1
    )
    assert limits.active_deadline_seconds == 60


def test_resource_limits_is_frozen() -> None:
    limits = ResourceLimits(
        active_deadline_seconds=60, max_retries=1, max_artifact_mib=1, max_cost_usd=1
    )
    with pytest.raises(AttributeError):
        limits.max_retries = 5  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name", ["active_deadline_seconds", "max_retries", "max_artifact_mib", "max_cost_usd"]
)
@pytest.mark.parametrize("bad_value", [0, -1])
def test_non_positive_field_rejected(field_name: str, bad_value: int) -> None:
    kwargs = {
        "active_deadline_seconds": 60,
        "max_retries": 1,
        "max_artifact_mib": 1,
        "max_cost_usd": 1,
    }
    kwargs[field_name] = bad_value
    with pytest.raises(ResourceLimitsValidationError):
        ResourceLimits(**kwargs)


@pytest.mark.parametrize(
    "field_name", ["active_deadline_seconds", "max_retries", "max_artifact_mib", "max_cost_usd"]
)
def test_bool_field_rejected(field_name: str) -> None:
    # bool is an int subclass in Python — must be explicitly excluded so
    # `max_retries=True` (i.e. 1) is never silently accepted as an int.
    kwargs = {
        "active_deadline_seconds": 60,
        "max_retries": 1,
        "max_artifact_mib": 1,
        "max_cost_usd": 1,
    }
    kwargs[field_name] = True
    with pytest.raises(ResourceLimitsValidationError):
        ResourceLimits(**kwargs)


@pytest.mark.parametrize(
    "field_name", ["active_deadline_seconds", "max_retries", "max_artifact_mib", "max_cost_usd"]
)
def test_non_int_field_rejected(field_name: str) -> None:
    kwargs = {
        "active_deadline_seconds": 60,
        "max_retries": 1,
        "max_artifact_mib": 1,
        "max_cost_usd": 1,
    }
    kwargs[field_name] = 1.5
    with pytest.raises(ResourceLimitsValidationError):
        ResourceLimits(**kwargs)
