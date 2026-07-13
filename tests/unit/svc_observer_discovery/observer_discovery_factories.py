"""Factory helpers for `tests/unit/svc_observer_discovery`.

Deliberately NOT named `conftest.py` — see
`tests/unit/svc_artifact_registry/registry_factories.py`'s module docstring
for why a second `conftest.py` in a sibling test directory causes an import
collision when the full `tests/unit` suite is collected together. Imported
by its own unique dotted name (`observer_discovery_factories`), inserted
onto `sys.path` by this directory's `conftest.py`.
"""

from __future__ import annotations

from saena_domain.execution import JobContext

TENANT_A = "acme-co"
TENANT_B = "globex-co"

CHATGPT_SEARCH_ENGINE_ID = "chatgpt-search"


def build_job_context(
    *,
    tenant_id: str = TENANT_A,
    workspace_id: str = "workspace-0001",
    project_id: str = "project-0001",
    run_id: str = "run-0001",
    trace_id: str = "a" * 32,
    idempotency_key: str = "acme-co:run-0001:w3-05",
    actor_id: str = "actor-0001",
) -> JobContext:
    return JobContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
    )
