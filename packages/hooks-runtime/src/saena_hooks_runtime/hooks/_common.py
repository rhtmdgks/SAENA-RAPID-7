"""Shared construction helpers for the 5 hook modules — not public API
(not re-exported from `saena_hooks_runtime.hooks.__init__`)."""

from __future__ import annotations

from ..models import AuditRecord, Decision, HookDecision, ReasonCode


def build_decision(
    *,
    ts: str,
    hook: str,
    decision: Decision,
    reason_code: ReasonCode,
    detail: str,
    tenant_id: str,
    run_id: str,
    trace_id: str,
    remediation: tuple[str, ...] = (),
) -> HookDecision:
    audit = AuditRecord(
        ts=ts,
        hook=hook,
        decision=decision,
        reason_code=reason_code,
        tenant_id=tenant_id,
        run_id=run_id,
        trace_id=trace_id,
        detail=detail,
    )
    return HookDecision(
        decision=decision,
        reason_code=reason_code,
        detail=detail,
        audit=audit,
        remediation=remediation,
    )


__all__ = ["build_decision"]
