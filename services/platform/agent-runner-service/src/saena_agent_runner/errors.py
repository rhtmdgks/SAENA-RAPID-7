"""Exception hierarchy for `saena_agent_runner` (`JobKind.AGENT_RUNNER`).

Follows the same shape every other service/domain package in this repo uses
(`saena_artifact_registry.errors`, `saena_domain.execution.errors`): every
exception carries an `error_code` (`saena.agent_runner.<reason>`, ADR-0015
taxonomy shape) and a structured, log-safe `.context` dict — never
free-text-only, never a raw blob/secret.

Every exception below maps to a `saena_domain.execution.JobError` at the
runner's outermost boundary (`runner.py`) — this module's exceptions are the
INTERNAL, more specific vocabulary; `JobError` is the canonical, wire-shaped
value object this package hands back to callers/events/audit.

ADR-0003 boundary: `ApprovalRequiredError` and its subclasses are the
fail-closed refusal this whole package pivots on — "no execution without a
valid approved contract_hash + ApprovalDecision" is enforced by raising one
of these BEFORE any worktree is touched, never by a best-effort check deep
inside execution.
"""

from __future__ import annotations

from typing import Any


class AgentRunnerError(Exception):
    """Base class for every error raised by `saena_agent_runner`."""

    error_code: str = "saena.agent_runner.error"
    #: Whether a caller could retry the SAME request and plausibly succeed.
    #: Every security-boundary refusal below is `retryable = False` — retrying
    #: an unapproved-execution/out-of-scope/forbidden-command attempt with the
    #: same inputs can never succeed, by construction.
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


# --- ADR-0003 approval boundary ------------------------------------------------------


class ApprovalRequiredError(AgentRunnerError):
    """Base class for every ADR-0003 approval-boundary refusal.

    Raised BEFORE any worktree/command/file operation — this package never
    executes a single byte of a patch unit without first passing every check
    in this family.
    """

    error_code = "saena.agent_runner.approval_required"


class ApprovalMissingError(ApprovalRequiredError):
    """No `ApprovalDecision` was supplied at all."""

    error_code = "saena.agent_runner.approval_missing"


class ApprovalContractHashMismatchError(ApprovalRequiredError):
    """`ApprovalDecision.contract_hash` does not match the contract actually
    being executed — a forged, stale, or mismatched approval, or an
    unapproved-contract-hash execution attempt."""

    error_code = "saena.agent_runner.approval_contract_hash_mismatch"


class ApprovalIdentityMismatchError(ApprovalRequiredError):
    """`ApprovalDecision.tenant_id`/`.run_id` do not match the `JobContext`
    actually executing — defense-in-depth against a replayed/cross-run
    approval instance."""

    error_code = "saena.agent_runner.approval_identity_mismatch"


class ApprovalRejectedError(ApprovalRequiredError):
    """`ApprovalDecision.decision == "rejected"` — B-department explicitly
    rejected this ChangePlan; never executed regardless of any other field."""

    error_code = "saena.agent_runner.approval_rejected"


class ApprovalSignatureInvalidError(ApprovalRequiredError):
    """`ApprovalDecision.signature`/`.signature_algorithm` failed structural
    validation (empty, or not a well-formed opaque signature per the
    contract's own shape) — a forged/malformed `ApprovalDecision`."""

    error_code = "saena.agent_runner.approval_signature_invalid"


class PatchUnitNotApprovedError(AgentRunnerError):
    """A patch unit named in the `ChangePlan` was not individually approved
    in `ApprovalDecision.patch_unit_decisions` (or was individually
    rejected) — refused even though the overall decision is `approved`
    (per-patch-unit granularity, H-7)."""

    error_code = "saena.agent_runner.patch_unit_not_approved"


# --- scope / diff-budget boundary ----------------------------------------------------


class OutOfScopeWriteError(AgentRunnerError):
    """A write target is not both (a) declared in the patch unit's own
    `files` list and (b) matched by at least one `approved_scope` glob."""

    error_code = "saena.agent_runner.out_of_scope_write"


class ProtectedPathWriteError(AgentRunnerError):
    """A write target falls under a structurally protected path
    (CLAUDE.md "Protected paths") — denied unconditionally, regardless of
    `approved_scope`."""

    error_code = "saena.agent_runner.protected_path_write"


class PathTraversalError(AgentRunnerError):
    """A write/read target resolves outside the isolated worktree root —
    `..`-traversal, an absolute path, or a symlink escape."""

    error_code = "saena.agent_runner.path_traversal"


class DiffBudgetExceededError(AgentRunnerError):
    """The realized diff for a patch unit exceeds `diff_budget.max_files`
    or `.max_lines`."""

    error_code = "saena.agent_runner.diff_budget_exceeded"


# --- command allowlist boundary -------------------------------------------------------


class CommandNotAllowlistedError(AgentRunnerError):
    """A requested command is not present in the executing patch unit's own
    `allowed_transformations` — default DENY (an unrecognized command is
    refused, never silently run)."""

    error_code = "saena.agent_runner.command_not_allowlisted"


class ForbiddenCommandError(AgentRunnerError):
    """A requested command matches an ABSOLUTE, structural deny rule
    (`git push`, `kubectl`, `helm`, credential-file reads, ...) — refused
    unconditionally, even if a (buggy or malicious) contract's own
    `allowed_transformations` were to name it."""

    error_code = "saena.agent_runner.forbidden_command"


# --- worktree / tenancy boundary -------------------------------------------------------


class CrossTenantWorktreeError(AgentRunnerError):
    """A worktree handle's own `tenant_id` does not match the executing
    `JobContext.tenant_id` — refused before any read/write against it."""

    error_code = "saena.agent_runner.cross_tenant_worktree"


class BaseCommitMismatchError(AgentRunnerError):
    """A worktree handle's `base_commit` does not match the approved
    `ChangePlan.repo_commit` — refused before any operation runs against it."""

    error_code = "saena.agent_runner.base_commit_mismatch"


# --- lifecycle boundary -----------------------------------------------------------------


class JobTimedOutError(AgentRunnerError):
    """`resource_limits_for(JobKind.AGENT_RUNNER).active_deadline_seconds`
    was exceeded during execution of a patch unit."""

    error_code = "saena.agent_runner.job_timed_out"
    retryable = True


class JobCancelledError(AgentRunnerError):
    """`CancellationSignal.is_cancellation_requested` returned `True` during
    execution of a patch unit."""

    error_code = "saena.agent_runner.job_cancelled"
    retryable = True


class ContractValidationError(AgentRunnerError):
    """The supplied `ChangePlan`/`ApprovalDecision` dict does not conform to
    its own signed, closed JSON Schema contract."""

    error_code = "saena.agent_runner.contract_invalid"


__all__ = [
    "AgentRunnerError",
    "ApprovalContractHashMismatchError",
    "ApprovalIdentityMismatchError",
    "ApprovalMissingError",
    "ApprovalRejectedError",
    "ApprovalRequiredError",
    "ApprovalSignatureInvalidError",
    "BaseCommitMismatchError",
    "CommandNotAllowlistedError",
    "ContractValidationError",
    "CrossTenantWorktreeError",
    "DiffBudgetExceededError",
    "ForbiddenCommandError",
    "JobCancelledError",
    "JobTimedOutError",
    "OutOfScopeWriteError",
    "PathTraversalError",
    "PatchUnitNotApprovedError",
    "ProtectedPathWriteError",
]
