"""Factory helpers for `tests/integration/failure_modes` — real-Postgres
half of the rollback verification gate.

Deliberately NOT named `conftest.py`'s own module surface (see that file's
own docstring for the collision rationale) and deliberately a LOCAL
duplicate of `tests/integration/persistence_postgres/postgres_factories.py`
(outside this patch unit's exclusive write paths — not imported from).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from saena_domain.audit.chain import AuditEntry, build_entry
from saena_domain.events import EnvelopeFactory
from saena_domain.identity import TenantId

TENANT_A = "acme-co"
TENANT_B = "globex-co"

RUN_ID = "run-w3-09-0001"
PATCH_UNIT_ID = "PU-ROLLBACK-01"


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Plain `asyncio.run` — no pytest-asyncio plugin is installed in this
    workspace (see `tests/unit/domain_identity/test_execution_context.py`'s
    own precedent, reused across every integration suite in this repo)."""
    return asyncio.run(coro)


def make_refused_patch_unit_audit_entry(
    *, tenant_id: str = TENANT_A, run_id: str = RUN_ID, prev_hash: str | None = None
) -> AuditEntry:
    """Mirrors the REAL shape `saena_agent_runner.audit.
    record_patch_unit_decision` builds for a denied-and-rolled-back patch
    unit — same action name, same payload shape, so this fixture is
    representative of the actual audit record a real rollback produces, not
    an unrelated ad-hoc shape."""
    return build_entry(
        prev_hash=prev_hash,
        action="agent_runner.patch_unit.decision.v1",
        recorded_at="2026-07-13T00:00:00Z",
        scope="tenant",
        trace_id="a" * 32,
        payload={
            "patch_unit_id": PATCH_UNIT_ID,
            "decision": "denied_out_of_scope_write",
            "error_code": "saena.agent_runner.out_of_scope_write",
        },
        tenant_id=tenant_id,
        run_id=run_id,
        actor={"actor_id": "actor-runner"},
        error_code="saena.agent_runner.out_of_scope_write",
    )


def make_executed_patch_unit_audit_entry(
    *, tenant_id: str = TENANT_A, run_id: str = RUN_ID, prev_hash: str | None = None
) -> AuditEntry:
    return build_entry(
        prev_hash=prev_hash,
        action="agent_runner.patch_unit.decision.v1",
        recorded_at="2026-07-13T00:05:00Z",
        scope="tenant",
        trace_id="b" * 32,
        payload={
            "patch_unit_id": PATCH_UNIT_ID,
            "decision": "executed",
            "worktree_commit": "c" * 40,
        },
        tenant_id=tenant_id,
        run_id=run_id,
        actor={"actor_id": "actor-runner"},
    )


def make_patch_unit_completed_envelope(
    *,
    tenant_id: str = TENANT_A,
    run_id: str = RUN_ID,
    patch_unit_id: str = PATCH_UNIT_ID,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """A real `patch.unit.completed.v1` envelope — the SAME event_type/
    producer pairing the real AsyncAPI catalog binds to `agent-runner-
    service` (`events/catalog/README.md`), representing the retry-after-
    rollback SUCCESS this gate's own "duplicate-event dedup"/"outbox
    replay" properties are proven against."""
    key = idempotency_key or f"{tenant_id}:{run_id}:{patch_unit_id}"
    return EnvelopeFactory.build_tenant_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        tenant_id=tenant_id,
        run_id=run_id,
        idempotency_key=key,
        payload={
            "patch_unit_id": patch_unit_id,
            "worktree_commit": "c" * 40,
            "manifest_uri": f"manifest://{tenant_id}/{patch_unit_id}/{'c' * 40}",
            "changed_files": ["apps/web/docs/readme.md"],
            "quality_gate_ids": ["tests-01"],
        },
    )


__all__ = [
    "PATCH_UNIT_ID",
    "RUN_ID",
    "TENANT_A",
    "TENANT_B",
    "TenantId",
    "make_executed_patch_unit_audit_entry",
    "make_patch_unit_completed_envelope",
    "make_refused_patch_unit_audit_entry",
    "run_async",
]
