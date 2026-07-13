"""Sanity checks that this unit's two services stay aligned with the
shared `saena_domain.execution` (w3-01) foundation they build on — both are
browser-pool, read-only (no Git write), no-Git-credential job kinds per
ADR-0004 (execution-runtime.md's job/SA mapping table)."""

from __future__ import annotations

from saena_domain.execution import JOB_KIND_PROFILES, ExecutionPool, JobKind


def test_site_discovery_profile_is_browser_pool_read_only() -> None:
    profile = JOB_KIND_PROFILES[JobKind.SITE_DISCOVERY]
    assert profile.pool == ExecutionPool.BROWSER
    assert profile.read_only is True
    assert profile.producer_id == "site-discovery-service"


def test_chatgpt_observer_profile_is_browser_pool_read_only() -> None:
    profile = JOB_KIND_PROFILES[JobKind.CHATGPT_OBSERVER]
    assert profile.pool == ExecutionPool.BROWSER
    assert profile.read_only is True
    assert profile.producer_id == "chatgpt-observer-service"
