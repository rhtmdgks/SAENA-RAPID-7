"""`before_handoff` hook (B-department prompt package v1 §11):

"before_handoff: run_quality_matrix, require_independent_critic,
require_rollback_manifest. timeout 60s, fail-closed. Output
PASS/CONDITIONAL_PASS/FAIL + remediation list. Blocks: missing critic
review, failed required gate, missing rollback manifest, deployment cmd in
patch."

Quality-matrix gate severity (task instructions list the exact gate names:
"build, tests, lint, links, schema, a11y, performance, fidelity,
security"):

- `REQUIRED_GATES` (`build`, `tests`, `lint`, `security`) — a failure here
  is a hard block: `FAILED_REQUIRED_GATE` -> `Decision.FAIL`.
- every other listed gate (`links`, `schema`, `a11y`, `performance`,
  `fidelity`) — a failure here is soft: `NON_REQUIRED_GATE_FAILED` ->
  contributes remediation entries and, absent any hard-block condition,
  downgrades the outcome to `Decision.CONDITIONAL_PASS` rather than
  `Decision.PASS`.

Aggregation rule: ANY hard-block condition present (failed required gate,
missing/non-independent critic review, missing/unverified rollback
manifest, a deployment command detected in the patch) -> `Decision.FAIL`.
Else, if any soft finding is present -> `Decision.CONDITIONAL_PASS`. Else
-> `Decision.PASS`. `remediation` lists every finding (hard AND soft),
always in the same fixed check order, regardless of which decision they
produced — a `CONDITIONAL_PASS` caller still gets a full remediation list,
not just the soft ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..command_normalize import has_pipe_to_interpreter, normalize_command
from ..models import Decision, HookDecision, ReasonCode, TimeoutBudget
from ..redact import redact_patterns
from ..rules.deploy_push import matches_deploy_push_cms_dns
from ._common import build_decision

HOOK_NAME = "before_handoff"

REQUIRED_GATES: tuple[str, ...] = ("build", "tests", "lint", "security")
NON_REQUIRED_GATES: tuple[str, ...] = ("links", "schema", "a11y", "performance", "fidelity")
ALL_GATES: tuple[str, ...] = REQUIRED_GATES + NON_REQUIRED_GATES

_GATE_STATUS_PASS = "PASS"
_GATE_STATUS_SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class QualityMatrixResult:
    """`gates` maps gate name -> status string (`"PASS"`/`"FAIL"`/`"SKIP"`).
    A gate absent from the mapping is treated the same as `"FAIL"` for a
    required gate (fail-closed: an unreported required gate is not given
    the benefit of the doubt) and the same as `"SKIP"` for a non-required
    one."""

    gates: dict[str, str]


@dataclass(frozen=True, slots=True)
class CriticReview:
    reviewer_id: str
    independent: bool
    verdict: str  # "approve" | "reject"


@dataclass(frozen=True, slots=True)
class RollbackManifest:
    patch_unit_id: str
    command: str
    verified: bool


@dataclass(frozen=True, slots=True)
class BeforeHandoffInput:
    ts: str
    run_id: str
    tenant_id: str
    trace_id: str
    quality_matrix: QualityMatrixResult
    critic_review: CriticReview | None
    rollback_manifest: RollbackManifest | None
    patch_commands: tuple[str, ...]
    budget: TimeoutBudget


def run_quality_matrix(input: BeforeHandoffInput) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Returns `(hard_findings, quality_soft)` — human-readable remediation
    strings, one per failed gate."""
    hard: list[str] = []
    soft: list[str] = []
    for gate in REQUIRED_GATES:
        status = input.quality_matrix.gates.get(gate, "FAIL")
        if status != _GATE_STATUS_PASS:
            hard.append(f"required quality gate '{gate}' is {status} — must pass before handoff")
    for gate in NON_REQUIRED_GATES:
        status = input.quality_matrix.gates.get(gate, _GATE_STATUS_SKIP)
        if status not in (_GATE_STATUS_PASS, _GATE_STATUS_SKIP):
            soft.append(f"quality gate '{gate}' is {status} — remediate before external claim")
    return tuple(hard), tuple(soft)


def require_independent_critic(input: BeforeHandoffInput) -> str | None:
    review = input.critic_review
    if review is None:
        return "no critic review recorded — an independent critic review is required"
    if not review.independent:
        return (
            f"critic review by '{review.reviewer_id}' is not independent "
            "— self-review does not count"
        )
    if review.verdict != "approve":
        return (
            f"critic review by '{review.reviewer_id}' did not approve (verdict: {review.verdict})"
        )
    return None


def require_rollback_manifest(input: BeforeHandoffInput) -> str | None:
    manifest = input.rollback_manifest
    if manifest is None:
        return "no rollback manifest recorded for this patch"
    if not manifest.verified:
        return f"rollback manifest for patch unit '{manifest.patch_unit_id}' is not verified"
    return None


def _deployment_cmd_in_patch(patch_commands: tuple[str, ...]) -> str | None:
    for raw in patch_commands:
        if has_pipe_to_interpreter(raw):
            return "patch contains a command that pipes output into a shell/script interpreter"
        for seg in normalize_command(raw):
            match = matches_deploy_push_cms_dns(seg)
            if match is not None:
                return f"patch contains a deployment command: {match}"
    return None


def before_handoff(input: BeforeHandoffInput) -> HookDecision:
    if input.budget.expired:
        return build_decision(
            ts=input.ts,
            hook=HOOK_NAME,
            decision=Decision.FAIL,
            reason_code=ReasonCode.TIMEOUT_EXCEEDED,
            detail="before_handoff exceeded its 60s budget — fail-closed FAIL",
            tenant_id=input.tenant_id,
            run_id=input.run_id,
            trace_id=input.trace_id,
            remediation=("re-run before_handoff within its 60s timeout budget",),
        )

    quality_hard, quality_soft = run_quality_matrix(input)
    critic_finding = require_independent_critic(input)
    rollback_finding = require_rollback_manifest(input)
    deploy_finding = _deployment_cmd_in_patch(input.patch_commands)

    hard_findings = list(quality_hard)
    for finding in (critic_finding, rollback_finding, deploy_finding):
        if finding is not None:
            hard_findings.append(redact_patterns(finding))

    remediation = tuple(hard_findings) + tuple(quality_soft)

    if hard_findings:
        reason = _primary_hard_reason(
            quality_failed=bool(quality_hard),
            critic_finding=critic_finding,
            rollback_finding=rollback_finding,
            deploy_finding=deploy_finding,
        )
        return build_decision(
            ts=input.ts,
            hook=HOOK_NAME,
            decision=Decision.FAIL,
            reason_code=reason,
            detail="; ".join(hard_findings),
            tenant_id=input.tenant_id,
            run_id=input.run_id,
            trace_id=input.trace_id,
            remediation=remediation,
        )

    if quality_soft:
        return build_decision(
            ts=input.ts,
            hook=HOOK_NAME,
            decision=Decision.CONDITIONAL_PASS,
            reason_code=ReasonCode.NON_REQUIRED_GATE_FAILED,
            detail="; ".join(quality_soft),
            tenant_id=input.tenant_id,
            run_id=input.run_id,
            trace_id=input.trace_id,
            remediation=remediation,
        )

    return build_decision(
        ts=input.ts,
        hook=HOOK_NAME,
        decision=Decision.PASS,
        reason_code=ReasonCode.OK,
        detail="",
        tenant_id=input.tenant_id,
        run_id=input.run_id,
        trace_id=input.trace_id,
        remediation=(),
    )


def _primary_hard_reason(
    *,
    quality_failed: bool,
    critic_finding: str | None,
    rollback_finding: str | None,
    deploy_finding: str | None,
) -> ReasonCode:
    """First-hit precedence for `AuditRecord.reason_code` when more than
    one hard-block condition fires in the same call: required-gate failure
    first (it is checked first by §11's own listed order), then missing
    critic, then missing rollback manifest, then deployment cmd in patch.
    `remediation` (not this) is what carries the FULL finding list — this
    is only the one-code audit summary."""
    if quality_failed:
        return ReasonCode.FAILED_REQUIRED_GATE
    if critic_finding is not None:
        return ReasonCode.MISSING_CRITIC_REVIEW
    if rollback_finding is not None:
        return ReasonCode.MISSING_ROLLBACK_MANIFEST
    assert deploy_finding is not None
    return ReasonCode.DEPLOYMENT_CMD_IN_PATCH


__all__ = [
    "ALL_GATES",
    "NON_REQUIRED_GATES",
    "REQUIRED_GATES",
    "BeforeHandoffInput",
    "CriticReview",
    "QualityMatrixResult",
    "RollbackManifest",
    "before_handoff",
    "require_independent_critic",
    "require_rollback_manifest",
    "run_quality_matrix",
]
