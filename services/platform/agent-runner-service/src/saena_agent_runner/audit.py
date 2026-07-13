"""Audit-event recording for `saena_agent_runner` decisions.

Reuses `saena_domain.audit.InMemoryAuditChain`/`build_entry` directly (no
second hash-chain implementation) — this module only fixes the `action`
naming convention and a payload shape that is guaranteed to pass
`saena_domain.audit.guard.guard_payload` (no credential/PII/source-content
-shaped keys: never `diff`/`patch`/`file_content`, never a secret/token/PII
key). One entry is appended per patch-unit DECISION `runner.py` makes —
executed, refused (not approved), or denied (scope/diff-budget/command/
path/cross-tenant/timeout/cancellation) — so the audit trail records every
decision, not only successes.

`error_code` here is the SPECIFIC `saena_agent_runner.errors.AgentRunnerError`
subclass code (e.g. `saena.agent_runner.approval_contract_hash_mismatch`),
not the coarser 9-category `JobError.error_code` `runner.py` separately
attaches to a `PatchUnitOutcome` for external/wire consumers — both shapes
satisfy `AuditEvent.error_code`'s pattern (`^saena\\.[a-z_]+\\.[a-z_]+$`),
and the audit trail is this package's own INTERNAL record, so it keeps the
more specific, more useful-for-forensics code rather than collapsing to the
same coarse category every denial reason would otherwise share.

`recorded_at` is always caller-supplied (never sourced internally by this
module) — `runner.py` threads its own injected `Clock.now_iso()` through, so
this module stays pure/deterministic and testable without monkeypatching
wall-clock time.
"""

from __future__ import annotations

from typing import Any

from saena_domain.audit import AuditEntry, InMemoryAuditChain
from saena_domain.execution import JobContext

#: `AuditEvent.action` pattern: `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,3}\.v[0-9]+$`.
#: Both actions below are 4 dot-segments (`agent_runner.<subject>.<verb>.v1`),
#: safely inside the `{2,3}` middle-group bound.
_APPROVAL_ACTION = "agent_runner.approval.refused.v1"
_PATCH_UNIT_ACTION = "agent_runner.patch_unit.decision.v1"


def record_approval_refused(
    chain: InMemoryAuditChain,
    *,
    job_context: JobContext,
    error_code: str,
    recorded_at: str,
) -> AuditEntry:
    """Record a whole-run ADR-0003 approval refusal (before any execution)."""
    return chain.append(
        action=_APPROVAL_ACTION,
        recorded_at=recorded_at,
        scope="tenant",
        trace_id=job_context.trace_id,
        tenant_id=job_context.tenant_id,
        run_id=job_context.run_id,
        actor={"actor_id": job_context.actor_id},
        error_code=error_code,
        payload={"decision": "refused", "error_code": error_code},
    )


def record_patch_unit_decision(
    chain: InMemoryAuditChain,
    *,
    job_context: JobContext,
    patch_unit_id: str,
    decision: str,
    recorded_at: str,
    error_code: str | None = None,
    worktree_commit: str | None = None,
) -> AuditEntry:
    """Record one patch-unit execution DECISION.

    `decision` is a short closed label this package controls (e.g.
    `"executed"`, `"refused_not_approved"`, `"denied_out_of_scope_write"`,
    `"denied_diff_budget_exceeded"`, `"denied_command_not_allowlisted"`,
    `"denied_path_traversal"`, `"denied_protected_path_write"`,
    `"denied_cross_tenant"`, `"denied_base_commit_mismatch"`, `"timed_out"`,
    `"cancelled"`) — never free-text, so the payload never accidentally
    carries diagnostic prose that might trip `guard_payload`'s content
    checks.
    """
    payload: dict[str, Any] = {"patch_unit_id": patch_unit_id, "decision": decision}
    if worktree_commit is not None:
        payload["worktree_commit"] = worktree_commit
    if error_code is not None:
        payload["error_code"] = error_code
    return chain.append(
        action=_PATCH_UNIT_ACTION,
        recorded_at=recorded_at,
        scope="tenant",
        trace_id=job_context.trace_id,
        tenant_id=job_context.tenant_id,
        run_id=job_context.run_id,
        actor={"actor_id": job_context.actor_id},
        error_code=error_code,
        payload=payload,
    )


__all__ = ["record_approval_refused", "record_patch_unit_decision"]
