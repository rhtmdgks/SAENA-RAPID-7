"""Core value objects shared by every hook in the ladder (w3-06).

Spec basis: `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §11
("Required hook checks") — this module models the vocabulary every one of
the five hooks (`session_start`, `pre_tool_use`, `post_tool_use`,
`subagent_start`, `before_handoff`) decides in and reports through:

- `Decision` — the closed set of outcomes a hook can return. Not every hook
  uses every member (`session_start`/`pre_tool_use`/`subagent_start` only
  ever return `ALLOW`/`DENY`; `post_tool_use` additionally returns
  `UNSTABLE`; `before_handoff` returns `PASS`/`CONDITIONAL_PASS`/`FAIL`
  instead of `ALLOW`/`DENY`) — kept as one enum so `AuditRecord.decision`
  has one closed vocabulary across the whole ladder rather than five
  separate ad-hoc string sets.
- `ReasonCode` — the closed set of reasons a hook denies/fails, one entry
  per named "Blocks:" condition in the task instructions plus the
  fail-closed/parse-failure codes every hook needs.
- `TimeoutBudget` — the engine-side timeout representation. Per-hook
  timeouts are fail-closed (§11 + task instructions: "engine receives
  elapsed/deadline and treats overrun as DENY"): every hook function checks
  `budget.expired` FIRST, before any other check, and returns the
  overrun-appropriate deny-class decision if it is `True`.
- `AuditRecord` / `HookDecision` — the per-decision audit shape (task
  instructions: "Audit record per decision: ts, hook, decision, reason_code,
  tenant_id, run_id, trace_id") and the full typed decision every hook
  function returns.

Nothing in this module performs I/O, network, or subprocess calls — pure
value objects and one pure timeout-budget helper only, per the task
instructions' "Pure decision engine" design requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Decision(str, Enum):
    """Closed outcome vocabulary across the whole hook ladder.

    `str` mixin so `Decision.DENY == "DENY"` holds (JSON-fixture-friendly —
    corpus fixtures and audit records compare against plain strings without
    a separate serialization step).
    """

    ALLOW = "ALLOW"
    DENY = "DENY"
    UNSTABLE = "UNSTABLE"
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class ReasonCode(str, Enum):
    """Closed reason-code vocabulary. One entry per §11 "Blocks:" condition
    (task instructions), plus the fail-closed parse/timeout codes every hook
    needs regardless of which named check produced them."""

    OK = "OK"

    # session_start
    CONTRACT_MISSING = "CONTRACT_MISSING"
    CONTRACT_HASH_MISMATCH = "CONTRACT_HASH_MISMATCH"
    ENGINE_SCOPE_VIOLATION = "ENGINE_SCOPE_VIOLATION"
    DIRTY_WORKTREE = "DIRTY_WORKTREE"
    POLICY_SIGNATURE_INVALID = "POLICY_SIGNATURE_INVALID"
    SECRET_DETECTED = "SECRET_DETECTED"

    # pre_tool_use
    OUT_OF_SCOPE_FILE_WRITE = "OUT_OF_SCOPE_FILE_WRITE"
    DEPLOY_PUSH_CMS_DNS = "DEPLOY_PUSH_CMS_DNS"
    UNAPPROVED_NETWORK_EGRESS = "UNAPPROVED_NETWORK_EGRESS"
    UNPINNED_DEPENDENCY_INSTALL = "UNPINNED_DEPENDENCY_INSTALL"
    MISSING_ACTION_CONTRACT = "MISSING_ACTION_CONTRACT"
    COMMAND_NORMALIZE_FAILURE = "COMMAND_NORMALIZE_FAILURE"

    # post_tool_use
    AUDIT_APPEND_FAILURE = "AUDIT_APPEND_FAILURE"
    UNEXPLAINED_FILE_CHANGE = "UNEXPLAINED_FILE_CHANGE"

    # subagent_start
    WRITER_LEASE_MISMATCH = "WRITER_LEASE_MISMATCH"
    READ_ONLY_ROLE_WRITE_LEASE = "READ_ONLY_ROLE_WRITE_LEASE"
    BROWSER_UNSCOPED_NETWORK = "BROWSER_UNSCOPED_NETWORK"

    # before_handoff
    MISSING_CRITIC_REVIEW = "MISSING_CRITIC_REVIEW"
    FAILED_REQUIRED_GATE = "FAILED_REQUIRED_GATE"
    MISSING_ROLLBACK_MANIFEST = "MISSING_ROLLBACK_MANIFEST"
    DEPLOYMENT_CMD_IN_PATCH = "DEPLOYMENT_CMD_IN_PATCH"
    NON_REQUIRED_GATE_FAILED = "NON_REQUIRED_GATE_FAILED"

    # generic, any hook
    TIMEOUT_EXCEEDED = "TIMEOUT_EXCEEDED"


# Per-hook timeout budgets, seconds (§11: session_start 30s, pre_tool_use 5s
# per call, post_tool_use 10s, subagent_start 5s, before_handoff 60s).
HOOK_TIMEOUT_SECONDS: dict[str, float] = {
    "session_start": 30.0,
    "pre_tool_use": 5.0,
    "post_tool_use": 10.0,
    "subagent_start": 5.0,
    "before_handoff": 60.0,
}


@dataclass(frozen=True, slots=True)
class TimeoutBudget:
    """Engine-side timeout representation — no wall-clock access here.

    Callers (the effectful runtime adapter, out of this package's scope)
    measure `elapsed_seconds` themselves and pass it in alongside the
    hook's `deadline_seconds` (normally one of `HOOK_TIMEOUT_SECONDS`'
    values, but overridable per call so tests can exercise the overrun path
    deterministically without a real clock or a real 30s sleep).
    """

    elapsed_seconds: float
    deadline_seconds: float

    @property
    def expired(self) -> bool:
        """`True` iff `elapsed_seconds` has reached or passed the deadline —
        overrun is treated as expired (>=, not >), matching "engine receives
        elapsed/deadline and treats overrun as DENY" (fail-closed: a
        same-instant deadline hit is not given the benefit of the doubt)."""
        return self.elapsed_seconds >= self.deadline_seconds


def budget_for(hook: str, *, elapsed_seconds: float) -> TimeoutBudget:
    """Build a `TimeoutBudget` for `hook` using its `HOOK_TIMEOUT_SECONDS`
    entry as the deadline. Raises `KeyError` for an unknown hook name — a
    caller asking for a budget for a hook this ladder does not define is a
    programming error, not a runtime decision, so it is not swallowed."""
    return TimeoutBudget(
        elapsed_seconds=elapsed_seconds, deadline_seconds=HOOK_TIMEOUT_SECONDS[hook]
    )


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Append-only audit entry — task instructions: "Audit record per
    decision: ts, hook, decision, reason_code, tenant_id, run_id,
    trace_id". `detail` is an additional, ALWAYS-REDACTED free-text field
    (never required by the task instructions' minimum field list, but every
    hook in this ladder attaches one — see each hook module's redaction
    handling, and `saena_hooks_runtime.redact`)."""

    ts: str
    hook: str
    decision: Decision
    reason_code: ReasonCode
    tenant_id: str
    run_id: str
    trace_id: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class HookDecision:
    """The full typed return value of every hook function in the ladder.

    `remediation` is populated only by `before_handoff` (task instructions:
    "Output PASS/CONDITIONAL_PASS/FAIL + remediation list") — every other
    hook returns it empty.
    """

    decision: Decision
    reason_code: ReasonCode
    detail: str
    audit: AuditRecord
    remediation: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        """`True` for any outcome a caller must treat as non-green:
        `DENY`/`FAIL` always; `UNSTABLE` (post_tool_use audit-append
        failure) counts as blocked too — task instructions list it under
        that hook's "Blocks:" line even though it does not roll back an
        already-executed tool call. `CONDITIONAL_PASS` is deliberately NOT
        blocked (it is a green-with-remediation outcome, not a hard stop)."""
        return self.decision in (Decision.DENY, Decision.FAIL, Decision.UNSTABLE)


__all__ = [
    "HOOK_TIMEOUT_SECONDS",
    "AuditRecord",
    "Decision",
    "HookDecision",
    "ReasonCode",
    "TimeoutBudget",
    "budget_for",
]
