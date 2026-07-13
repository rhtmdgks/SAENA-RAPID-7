"""`session_start` hook (B-department prompt package v1 §11):

"session_start: verify_run_context, verify_policy_signature, secret_scan.
timeout 30s, fail-closed. Blocks: contract missing, dirty worktree,
detected secrets."

Check order (first failing check wins — matches the §11 listing order):
timeout budget -> `verify_run_context` (contract presence/hash/engine-scope
+ dirty worktree) -> `verify_policy_signature` -> `secret_scan`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contract import ActionContract, validate_contract
from ..models import Decision, HookDecision, ReasonCode, TimeoutBudget
from ..redact import redact_known
from ._common import build_decision

HOOK_NAME = "session_start"


@dataclass(frozen=True, slots=True)
class SecretFinding:
    """One secret-scan hit. `raw_value` is the actual detected secret
    text — carried here ONLY so the engine can redact it; it must never
    reach `HookDecision.detail`/`AuditRecord.detail` unredacted (see
    `secret_scan` below and `redact.redact_known`)."""

    location: str
    rule_id: str
    raw_value: str


@dataclass(frozen=True, slots=True)
class SessionStartInput:
    ts: str
    run_id: str
    tenant_id: str
    trace_id: str
    contract: ActionContract | None
    worktree_dirty: bool
    policy_signature_valid: bool
    secret_findings: tuple[SecretFinding, ...]
    budget: TimeoutBudget


def verify_run_context(input: SessionStartInput) -> ReasonCode | None:
    """Contract presence/hash/engine-scope (`contract.validate_contract`)
    plus dirty-worktree check. Contract validity is checked FIRST — a
    dirty worktree under a missing/invalid contract is still reported as
    the contract problem, matching §11's listed check ordering."""
    contract_issue = validate_contract(input.contract)
    if contract_issue is not None:
        return contract_issue
    if input.worktree_dirty:
        return ReasonCode.DIRTY_WORKTREE
    return None


def verify_policy_signature(input: SessionStartInput) -> ReasonCode | None:
    if not input.policy_signature_valid:
        return ReasonCode.POLICY_SIGNATURE_INVALID
    return None


def secret_scan(input: SessionStartInput) -> tuple[ReasonCode | None, str]:
    """Returns `(None, "")` if no secrets were found, else
    `(ReasonCode.SECRET_DETECTED, <redacted detail>)`. The detail names
    LOCATIONS and RULE IDS only — never the raw matched value, and
    `redact_known` additionally strips every raw value (defense in depth,
    in case a location/rule_id string itself happened to embed one)."""
    if not input.secret_findings:
        return None, ""
    locations = ", ".join(f"{f.location} ({f.rule_id})" for f in input.secret_findings)
    detail = redact_known(
        f"secret(s) detected: {locations}",
        tuple(f.raw_value for f in input.secret_findings),
    )
    return ReasonCode.SECRET_DETECTED, detail


_DEFAULT_DETAIL: dict[ReasonCode, str] = {
    ReasonCode.CONTRACT_MISSING: "no Action Contract present for this run — fail-closed",
    ReasonCode.CONTRACT_HASH_MISMATCH: (
        "Action Contract contract_hash does not match its own content — fail-closed"
    ),
    ReasonCode.ENGINE_SCOPE_VIOLATION: (
        "Action Contract engine_scope is not exactly ['chatgpt-search'] — fail-closed"
    ),
    ReasonCode.DIRTY_WORKTREE: "worktree is dirty at session start — fail-closed",
    ReasonCode.POLICY_SIGNATURE_INVALID: "policy bundle signature did not verify — fail-closed",
}


def session_start(input: SessionStartInput) -> HookDecision:
    if input.budget.expired:
        return build_decision(
            ts=input.ts,
            hook=HOOK_NAME,
            decision=Decision.DENY,
            reason_code=ReasonCode.TIMEOUT_EXCEEDED,
            detail="session_start exceeded its timeout budget — fail-closed deny",
            tenant_id=input.tenant_id,
            run_id=input.run_id,
            trace_id=input.trace_id,
        )

    for check in (verify_run_context, verify_policy_signature):
        reason = check(input)
        if reason is not None:
            return build_decision(
                ts=input.ts,
                hook=HOOK_NAME,
                decision=Decision.DENY,
                reason_code=reason,
                detail=_DEFAULT_DETAIL.get(reason, reason.value),
                tenant_id=input.tenant_id,
                run_id=input.run_id,
                trace_id=input.trace_id,
            )

    reason, detail = secret_scan(input)
    if reason is not None:
        return build_decision(
            ts=input.ts,
            hook=HOOK_NAME,
            decision=Decision.DENY,
            reason_code=reason,
            detail=detail,
            tenant_id=input.tenant_id,
            run_id=input.run_id,
            trace_id=input.trace_id,
        )

    return build_decision(
        ts=input.ts,
        hook=HOOK_NAME,
        decision=Decision.ALLOW,
        reason_code=ReasonCode.OK,
        detail="",
        tenant_id=input.tenant_id,
        run_id=input.run_id,
        trace_id=input.trace_id,
    )


__all__ = [
    "SecretFinding",
    "SessionStartInput",
    "secret_scan",
    "session_start",
    "verify_policy_signature",
    "verify_run_context",
]
