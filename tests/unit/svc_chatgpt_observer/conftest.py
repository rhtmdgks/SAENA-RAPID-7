"""Shared fixtures/factories for the w4-08 browser-pool observer unit lane.

The package is a registered workspace member, so it imports normally (no
sys.path hack). Everything here is deterministic + offline — a FIXTURE browser
(`FixtureBrowserSessionFactory`) and an in-memory `FakeArtifactGateway`; the
real Playwright driver / HTTP artifact-registry adapter are never constructed
in this lane."""

from __future__ import annotations

import pytest
from saena_domain.execution import JobContext

TENANT_A = "acme-co"
TENANT_B = "globex-co"
RUN_ID = "run-2026-0713-0001"
ENGINE = "chatgpt-search"


def make_job_context(*, tenant_id: str = TENANT_A, run_id: str = RUN_ID) -> JobContext:
    return JobContext(
        tenant_id=tenant_id,
        workspace_id="ws-0001",
        project_id="proj-0001",
        run_id=run_id,
        trace_id="a" * 32,
        idempotency_key=f"{tenant_id}:{run_id}:w4-08",
        actor_id="actor-0001",
    )


@pytest.fixture
def job_context() -> JobContext:
    return make_job_context()
