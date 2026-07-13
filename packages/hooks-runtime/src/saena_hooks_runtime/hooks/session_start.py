"""`session_start` hook (B-department prompt package v1 §11):

"session_start: verify_run_context, verify_policy_signature, secret_scan.
timeout 30s, fail-closed. Blocks: contract missing, dirty worktree,
detected secrets."

Check order (first failing check wins — matches the §11 listing order):
timeout budget -> `verify_run_context` (contract presence/hash/engine-scope
+ dirty worktree) -> `verify_policy_signature` -> `secret_scan`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..contract import ActionContract, validate_contract
from ..models import Decision, HookDecision, ReasonCode, TimeoutBudget
from ..redact import redact_known
from ._common import build_decision

HOOK_NAME = "session_start"


@dataclass(frozen=True, slots=True)
class SkillBundleIntegrityResult:
    """Outcome of the injected F-5 skill-bundle integrity check. `ok=False`
    denies session start. `redacted_detail` MUST already be free of any raw
    bundle content (the adapter is responsible for redaction — the pure
    `saena_domain.execution.skill_bundle` verifier only ever surfaces
    digests, never file bytes)."""

    ok: bool
    redacted_detail: str = ""


@runtime_checkable
class SkillBundleIntegrityPort(Protocol):
    """Injected F-5 boundary. hooks-runtime is a stdlib-only leaf and cannot
    import the concrete verifier (`saena_domain.execution.skill_bundle`); the
    runtime host wraps that verifier as this Port. `verify` returns a result,
    never raises — a raising adapter is treated as fail-closed by
    `check_skill_bundle_integrity` below."""

    def verify(self, *, expected_skill_bundle_hash: str | None) -> SkillBundleIntegrityResult: ...


@dataclass(slots=True)
class AllowingSkillBundlePort:
    """Reference fake for callers/tests with no bundle to check (returns ok)."""

    def verify(self, *, expected_skill_bundle_hash: str | None) -> SkillBundleIntegrityResult:
        return SkillBundleIntegrityResult(ok=True)


@dataclass(slots=True)
class StubSkillBundlePort:
    """Test fake with a fixed verdict, recording whether it was consulted."""

    result: SkillBundleIntegrityResult
    consulted: bool = field(default=False)

    def verify(self, *, expected_skill_bundle_hash: str | None) -> SkillBundleIntegrityResult:
        self.consulted = True
        return self.result


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
    """Input for the EXECUTION session_start boundary. A `session_start` guards
    a write session that WILL run skill-derived commands, so the F-5 skill-bundle
    gate is UNCONDITIONAL: `expected_skill_bundle_hash` and `skill_bundle_port`
    are REQUIRED fields (no default) — you cannot even construct this input
    without them. A None pin or None port is still a fail-closed DENY at runtime
    (defense in depth). There is NO opt-out flag: this input type cannot express
    "skip the bundle gate". (A genuinely non-executing session would need a
    SEPARATE input type + entry point that this execution `session_start` cannot
    accept — none exists because no non-executing session-start caller exists.)"""

    ts: str
    run_id: str
    tenant_id: str
    trace_id: str
    contract: ActionContract | None
    worktree_dirty: bool
    policy_signature_valid: bool
    secret_findings: tuple[SecretFinding, ...]
    budget: TimeoutBudget
    #: F-5 pin for this run's skill bundle (`sha256:<hex>`). REQUIRED — a None
    #: value is a fail-closed DENY at the (unconditional) bundle gate.
    expected_skill_bundle_hash: str | None
    #: Injected verifier (wraps saena_domain.execution.skill_bundle). REQUIRED —
    #: a None port is a fail-closed DENY (cannot prove integrity).
    skill_bundle_port: SkillBundleIntegrityPort | None


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


def check_skill_bundle_integrity(input: SessionStartInput) -> tuple[ReasonCode | None, str]:
    """F-5 dedicated skill-bundle integrity gate — UNCONDITIONAL, fail-closed.

    Every execution `session_start` MUST carry a valid `expected_skill_bundle_hash`
    pin AND a wired `skill_bundle_port`. A missing pin (None), a missing port, or
    a port that raises is a DENY. There is NO opt-out path of any kind — the
    input type cannot even express "skip this gate"."""
    if input.expected_skill_bundle_hash is None:
        return (
            ReasonCode.SKILL_BUNDLE_INTEGRITY,
            "no skill_bundle_hash pinned for a write session — fail-closed",
        )
    port = input.skill_bundle_port
    if port is None:
        return (
            ReasonCode.SKILL_BUNDLE_INTEGRITY,
            "skill_bundle_hash pinned but no integrity verifier is wired — fail-closed",
        )
    try:
        result = port.verify(expected_skill_bundle_hash=input.expected_skill_bundle_hash)
    except Exception:
        # A raising adapter is fail-closed; never surface its message (may
        # embed bundle content) — a fixed, content-free reason only.
        return (
            ReasonCode.SKILL_BUNDLE_INTEGRITY,
            "skill-bundle integrity verification errored — fail-closed",
        )
    if not result.ok:
        return ReasonCode.SKILL_BUNDLE_INTEGRITY, (
            result.redacted_detail or "skill bundle failed integrity verification — run blocked"
        )
    return None, ""


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

    for scan in (check_skill_bundle_integrity, secret_scan):
        reason, detail = scan(input)
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
    "AllowingSkillBundlePort",
    "SecretFinding",
    "SessionStartInput",
    "SkillBundleIntegrityPort",
    "SkillBundleIntegrityResult",
    "StubSkillBundlePort",
    "check_skill_bundle_integrity",
    "secret_scan",
    "session_start",
    "verify_policy_signature",
    "verify_run_context",
]
