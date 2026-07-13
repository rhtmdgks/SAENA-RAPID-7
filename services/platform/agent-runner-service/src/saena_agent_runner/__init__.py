"""saena_agent_runner — `JobKind.AGENT_RUNNER` execution service (W3, Wave 3).

Executes an APPROVED `ChangePlan` (Action Contract)'s patch units inside
per-patch-unit isolated worktrees, strictly bounded by ADR-0003 (approval
authority), the contract's own `approved_scope`/`diff_budget`, a per-patch-unit
command allowlist (default DENY), and the worktree filesystem boundary
(no symlink/traversal escape). See `docs/architecture/execution-runtime.md`
for the shared execution-domain layer this package builds on
(`saena_domain.execution`).

Pure-domain core (`approval.py`, `contract.py`, `scope.py`, `commands.py`,
`runner.py`) + `typing.Protocol` adapters (`worktree.py`'s
`WorktreeFactory`/`WorktreeHandle`/`CommandExecutor`, `artifact.py`'s
`ArtifactRegistryGateway`) with in-memory fakes for every adapter — no real
`git`/`subprocess` call anywhere in this package or its unit tests.

Public API:
    PatchUnitRunner / PatchUnitRequest / FileWrite / PatchUnitOutcome / JobRunResult
    parse_change_plan / get_patch_unit / ChangeplanActionContract / PatchUnit
    parse_approval_decision / verify_approval / ApprovalDecision
    WorktreeHandle / WorktreeFactory / CommandExecutor / CommandResult / DiffStat
    FakeWorktreeHandle / FakeWorktreeFactory / FakeCommandExecutor
    ArtifactRegistryGateway / FakeArtifactRegistryGateway / RegisteredArtifactRef
    build_patch_artifact
    Clock / SystemClock / FakeClock
    Every `saena_agent_runner.errors` exception
"""

from __future__ import annotations

from saena_agent_runner.approval import ApprovalDecision, parse_approval_decision, verify_approval
from saena_agent_runner.artifact import (
    ArtifactRegistryGateway,
    FakeArtifactRegistryGateway,
    RegisteredArtifactRef,
    build_patch_artifact,
)
from saena_agent_runner.clock import Clock, FakeClock, SystemClock
from saena_agent_runner.contract import (
    ChangeplanActionContract,
    PatchUnit,
    get_patch_unit,
    parse_change_plan,
)
from saena_agent_runner.errors import (
    AgentRunnerError,
    ApprovalContractHashMismatchError,
    ApprovalIdentityMismatchError,
    ApprovalMissingError,
    ApprovalRejectedError,
    ApprovalRequiredError,
    ApprovalSignatureInvalidError,
    BaseCommitMismatchError,
    CommandNotAllowlistedError,
    ContractValidationError,
    CrossTenantWorktreeError,
    DiffBudgetExceededError,
    ForbiddenCommandError,
    JobCancelledError,
    JobTimedOutError,
    OutOfScopeWriteError,
    PatchUnitNotApprovedError,
    PathTraversalError,
    ProtectedPathWriteError,
)
from saena_agent_runner.runner import (
    FileWrite,
    JobRunResult,
    PatchUnitOutcome,
    PatchUnitRequest,
    PatchUnitRunner,
)
from saena_agent_runner.skill_bundle import (
    InMemorySkillBundleSource,
    RecordingSkillBundleSource,
    SkillBundleSource,
    enforce_skill_bundle_integrity,
)
from saena_agent_runner.worktree import (
    CommandExecutor,
    CommandResult,
    DiffStat,
    FakeCommandExecutor,
    FakeWorktreeFactory,
    FakeWorktreeHandle,
    WorktreeFactory,
    WorktreeHandle,
)

__all__ = [
    "AgentRunnerError",
    "ApprovalContractHashMismatchError",
    "ApprovalDecision",
    "ApprovalIdentityMismatchError",
    "ApprovalMissingError",
    "ApprovalRejectedError",
    "ApprovalRequiredError",
    "ApprovalSignatureInvalidError",
    "ArtifactRegistryGateway",
    "BaseCommitMismatchError",
    "ChangeplanActionContract",
    "Clock",
    "CommandExecutor",
    "CommandNotAllowlistedError",
    "CommandResult",
    "ContractValidationError",
    "CrossTenantWorktreeError",
    "DiffBudgetExceededError",
    "DiffStat",
    "FakeArtifactRegistryGateway",
    "FakeClock",
    "FakeCommandExecutor",
    "FakeWorktreeFactory",
    "FakeWorktreeHandle",
    "FileWrite",
    "ForbiddenCommandError",
    "JobCancelledError",
    "JobRunResult",
    "JobTimedOutError",
    "OutOfScopeWriteError",
    "PatchUnit",
    "PatchUnitNotApprovedError",
    "PatchUnitOutcome",
    "PatchUnitRequest",
    "PatchUnitRunner",
    "InMemorySkillBundleSource",
    "RecordingSkillBundleSource",
    "SkillBundleSource",
    "enforce_skill_bundle_integrity",
    "PathTraversalError",
    "ProtectedPathWriteError",
    "RegisteredArtifactRef",
    "SystemClock",
    "WorktreeFactory",
    "WorktreeHandle",
    "build_patch_artifact",
    "get_patch_unit",
    "parse_approval_decision",
    "parse_change_plan",
    "verify_approval",
]
