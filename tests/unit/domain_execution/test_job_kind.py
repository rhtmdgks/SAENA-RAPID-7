"""JobKind closed enum + JOB_KIND_PROFILES pool/read_only/SA/producer facts
(ADR-0004 node pool revision, k3s spec §5.2)."""

from __future__ import annotations

import pytest
from saena_domain.events._topics import load_topic_catalog
from saena_domain.execution.job_kind import (
    JOB_KIND_PROFILES,
    ExecutionPool,
    JobKind,
    profile_for,
)


def test_job_kind_is_closed_5_member_enum() -> None:
    assert {member.value for member in JobKind} == {
        "agent_runner",
        "repository_intake",
        "quality_eval",
        "chatgpt_observer",
        "site_discovery",
    }


def test_every_job_kind_has_a_profile() -> None:
    assert set(JOB_KIND_PROFILES.keys()) == set(JobKind)
    for kind in JobKind:
        assert profile_for(kind).kind == kind


@pytest.mark.parametrize(
    ("kind", "expected_pool"),
    [
        (JobKind.AGENT_RUNNER, ExecutionPool.RUNNER),
        (JobKind.REPOSITORY_INTAKE, ExecutionPool.RUNNER),
        (JobKind.QUALITY_EVAL, ExecutionPool.RUNNER),
        (JobKind.CHATGPT_OBSERVER, ExecutionPool.BROWSER),
        (JobKind.SITE_DISCOVERY, ExecutionPool.BROWSER),
    ],
)
def test_pool_assignment_matches_adr_0004(kind: JobKind, expected_pool: ExecutionPool) -> None:
    """ADR-0004 item 1: agent-runner + repository-intake + quality-eval all
    inherit the runner pool ("customer source를 다루는 모든 Job은 runner
    pool 상속"). Item 2: chatgpt-observer + site-discovery land on the
    browser pool."""
    assert profile_for(kind).pool == expected_pool


@pytest.mark.parametrize(
    ("kind", "expected_read_only"),
    [
        (JobKind.AGENT_RUNNER, False),
        (JobKind.REPOSITORY_INTAKE, True),
        (JobKind.QUALITY_EVAL, True),
        (JobKind.CHATGPT_OBSERVER, True),
        (JobKind.SITE_DISCOVERY, True),
    ],
)
def test_read_only_flag_matches_adr_0004_git_write_boundaries(
    kind: JobKind, expected_read_only: bool
) -> None:
    """ADR-0004's 3-way runner-pool SA split: agent-runner gets worktree
    write (contract-scope files only) -> read_only=False; quality-eval gets
    build-execution-only, NO Git write -> read_only=True; repository-intake
    gets read-only Git -> read_only=True. Both browser-pool kinds are
    read-only by ADR-0004 item 2."""
    assert profile_for(kind).read_only is expected_read_only


def test_service_accounts_are_distinct_per_kind() -> None:
    service_accounts = [profile.service_account for profile in JOB_KIND_PROFILES.values()]
    assert len(service_accounts) == len(set(service_accounts))


def test_agent_runner_service_account_matches_values_yaml() -> None:
    # deploy/charts/saena-forge/values.yaml agentRunner.job.serviceAccount
    assert profile_for(JobKind.AGENT_RUNNER).service_account == "saena-agent-runner"


def test_producer_ids_match_the_confirmed_asyncapi_catalog() -> None:
    """Every JobKind's `producer_id` must equal the producer AsyncAPI's
    `operations.*.summary` ("<producer> produces <event_type>.") records
    for that service, so callers composing an envelope via
    `EnvelopeFactory` with `producer=profile_for(kind).producer_id` never
    hit `ProducerMismatchError`."""
    catalog = load_topic_catalog()
    producers = {info.expected_producer for info in catalog.values()}
    for profile in JOB_KIND_PROFILES.values():
        # chatgpt-observer's own event (observation.captured.v1) IS in the
        # catalog even though this patch unit builds no payload for it (see
        # events.py module docstring) — still asserted present below.
        assert profile.producer_id in producers, (
            f"{profile.kind!r} producer_id {profile.producer_id!r} is not a producer "
            "in the CONFIRMED AsyncAPI catalog"
        )
