"""`PatchUnitRunner` — the `JobKind.AGENT_RUNNER` execution orchestrator.

This is the ONE place every guard in this package is wired together, in a
fixed order, for a single job run:

1. `approval.verify_approval` — ADR-0003 fail-closed gate. Nothing below
   this line ever runs if this raises.
2. Per requested patch unit, in order:
   a. membership check — `patch_unit_id` must be in the APPROVED set
      (`verify_approval`'s return value) AND named in the contract itself
      (`contract.get_patch_unit`); otherwise refused, worktree never
      created.
   b. worktree provisioning + defense-in-depth re-checks
      (tenant/base-commit) — `errors.CrossTenantWorktreeError`/
      `BaseCommitMismatchError` if a (buggy/malicious) factory handed back
      a mismatched handle.
   c. per-file-write guards (`scope.guard_protected_path`,
      `scope.guard_scope`, `scope.resolve_within_worktree`) — cancellation/
      timeout checked before each write.
   d. diff-budget check (`contract.diff_budget`) — after all writes,
      before any command runs.
   e. per-command guards (`commands.guard_command`) — cancellation/timeout
      checked before each command; a nonzero `CommandResult` is treated as
      a patch-unit failure.
   f. commit + artifact registration + `patch.unit.completed.v1` payload
      construction — ONLY on a fully clean pass through (a)-(e).
3. On ANY failure in (b)-(e) for a given unit: `worktree.rollback()` is
   called before returning that unit's outcome — no partial commit is ever
   left behind, and no artifact/event is ever produced for that unit.
4. An audit entry is appended for EVERY per-unit decision (success or any
   refusal/denial), plus one entry if approval verification itself failed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from saena_domain.audit import InMemoryAuditChain
from saena_domain.execution import (
    JobContext,
    JobError,
    JobKind,
    JobStatus,
    build_patch_unit_completed_payload,
    resource_limits_for,
    transition,
)
from saena_domain.execution.protocols import CancellationSignal
from saena_domain.execution.skill_bundle import SkillBundleIntegrityError

from saena_agent_runner import audit as audit_mod
from saena_agent_runner import commands as commands_mod
from saena_agent_runner import scope as scope_mod
from saena_agent_runner.approval import ApprovalDecision, verify_approval
from saena_agent_runner.artifact import ArtifactRegistryGateway, build_patch_artifact
from saena_agent_runner.clock import Clock, SystemClock
from saena_agent_runner.contract import ChangeplanActionContract, get_patch_unit
from saena_agent_runner.errors import (
    AgentRunnerError,
    ApprovalRequiredError,
    BaseCommitMismatchError,
    CrossTenantWorktreeError,
    DiffBudgetExceededError,
    JobCancelledError,
    JobTimedOutError,
    PatchUnitNotApprovedError,
)
from saena_agent_runner.skill_bundle import (
    SkillBundleSource,
    enforce_skill_bundle_integrity,
)
from saena_agent_runner.worktree import CommandExecutor, WorktreeFactory


@dataclass(frozen=True, slots=True)
class FileWrite:
    """One file-write the caller wants applied inside a patch unit's worktree."""

    relative_path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class PatchUnitRequest:
    """One patch unit's requested work — writes + commands to run."""

    patch_unit_id: str
    file_writes: tuple[FileWrite, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class PatchUnitOutcome:
    """Result of attempting to execute (or refusing to execute) one patch unit."""

    patch_unit_id: str
    status: JobStatus
    decision: str
    error: JobError | None = None
    worktree_commit: str | None = None
    artifact: dict[str, Any] | None = None
    event_payload: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class JobRunResult:
    """Whole-run result — one outcome per requested patch unit."""

    job_status: JobStatus
    outcomes: tuple[PatchUnitOutcome, ...]


def _job_error(exc: AgentRunnerError) -> JobError:
    """Map an internal `AgentRunnerError` to the canonical wire-shaped `JobError`."""
    category = {
        ApprovalRequiredError: "policy_denied",
        PatchUnitNotApprovedError: "policy_denied",
        CrossTenantWorktreeError: "policy_denied",
        BaseCommitMismatchError: "policy_denied",
        JobTimedOutError: "unavailable",
        JobCancelledError: "unavailable",
    }
    error_category = "policy_denied"
    for exc_type, mapped_category in category.items():
        if isinstance(exc, exc_type):
            error_category = mapped_category
            break
    else:
        # Every other AgentRunnerError subclass here (scope/command/path/diff
        # budget denials) is a structural policy refusal, not a transient
        # condition — reuses the same category as the approval family.
        error_category = "policy_denied"
    summary = str(exc)
    if len(summary) > 500:
        summary = summary[:497] + "..."
    return JobError(
        error_code=f"saena.{error_category}.agent_runner_denied",
        summary=summary,
        retryable=exc.retryable,
    )


def _advance(current: JobStatus, target: JobStatus) -> JobStatus:
    return transition(current, target).status


@dataclass
class PatchUnitRunner:
    """Orchestrates `JobKind.AGENT_RUNNER` execution of one or more patch units."""

    worktree_factory: WorktreeFactory
    command_executor: CommandExecutor
    artifact_gateway: ArtifactRegistryGateway
    audit_chain: InMemoryAuditChain
    cancellation_signal: CancellationSignal | None = None
    clock: Clock = field(default_factory=SystemClock)
    #: F-5 skill-bundle integrity boundary. When a run is pinned to an
    #: `expected_skill_bundle_hash`, this source is read (before any worktree)
    #: and the bundle content is verified against the pin. Left None only for
    #: runs that carry no skill-bundle pin at all.
    skill_bundle_source: SkillBundleSource | None = None

    def run(
        self,
        *,
        job_context: JobContext,
        contract: ChangeplanActionContract,
        expected_contract_hash: str,
        approval: ApprovalDecision,
        requests: Sequence[PatchUnitRequest],
        expected_skill_bundle_hash: str | None = None,
    ) -> JobRunResult:
        """Execute `requests` against `contract`, fail-closed on approval AND
        on skill-bundle integrity.

        Raises the underlying `ApprovalRequiredError` subclass (NEVER
        returns a partial `JobRunResult`) if `approval` does not authorize
        executing `contract` at all — this is the ADR-0003 boundary: no
        patch unit is ever attempted, no worktree is ever created, if
        approval verification itself fails.

        Then, when `expected_skill_bundle_hash` is pinned, raises a
        `SkillBundleIntegrityError` subclass (F-5, k3s §10) if the actual
        skill bundle's content hash does not match — again BEFORE any worktree
        is created or executor invoked. The whole-contract `contract_hash`
        check inside `verify_approval` is the complementary defense; it does
        not, and cannot, prove the bundle files themselves are unaltered.
        """
        try:
            approved_ids = verify_approval(
                contract=contract,
                approval=approval,
                expected_contract_hash=expected_contract_hash,
                expected_tenant_id=job_context.tenant_id,
                expected_run_id=job_context.run_id,
            )
        except ApprovalRequiredError as exc:
            audit_mod.record_approval_refused(
                self.audit_chain,
                job_context=job_context,
                error_code=exc.error_code,
                recorded_at=self.clock.now_iso(),
            )
            raise

        # F-5 skill-bundle integrity — fail-closed, BEFORE any worktree /
        # executor. Only enforced when the run carries a pin (a run with no
        # skill bundle at all passes None and is not gated here).
        if expected_skill_bundle_hash is not None:
            try:
                enforce_skill_bundle_integrity(
                    expected_skill_bundle_hash=expected_skill_bundle_hash,
                    source=self.skill_bundle_source,
                    job_context=job_context,
                )
            except SkillBundleIntegrityError as exc:
                audit_mod.record_skill_bundle_refused(
                    self.audit_chain,
                    job_context=job_context,
                    error_code=exc.error_code,
                    recorded_at=self.clock.now_iso(),
                )
                raise

        deadline_seconds = resource_limits_for(JobKind.AGENT_RUNNER).active_deadline_seconds
        start_time = self.clock.monotonic()

        outcomes = tuple(
            self._run_one(
                job_context=job_context,
                contract=contract,
                expected_contract_hash=expected_contract_hash,
                approved_ids=approved_ids,
                request=request,
                start_time=start_time,
                deadline_seconds=deadline_seconds,
            )
            for request in requests
        )
        return JobRunResult(job_status=_aggregate_status(outcomes), outcomes=outcomes)

    def _check_liveness(
        self, *, job_context: JobContext, start_time: float, deadline_seconds: int
    ) -> None:
        if (
            self.cancellation_signal is not None
            and self.cancellation_signal.is_cancellation_requested(job_context=job_context)
        ):
            raise JobCancelledError(
                "cancellation requested — aborting patch unit execution", context={}
            )
        elapsed = self.clock.monotonic() - start_time
        if elapsed > deadline_seconds:
            raise JobTimedOutError(
                f"active_deadline_seconds ({deadline_seconds}) exceeded (elapsed={elapsed:.1f}s)",
                context={"deadline_seconds": deadline_seconds, "elapsed_seconds": elapsed},
            )

    def _run_one(
        self,
        *,
        job_context: JobContext,
        contract: ChangeplanActionContract,
        expected_contract_hash: str,
        approved_ids: frozenset[str],
        request: PatchUnitRequest,
        start_time: float,
        deadline_seconds: int,
    ) -> PatchUnitOutcome:
        patch_unit_id = request.patch_unit_id

        # --- membership: approved AND named in the contract itself ---------------
        if patch_unit_id not in approved_ids:
            not_approved_error = PatchUnitNotApprovedError(
                f"patch_unit_id {patch_unit_id!r} was not individually approved "
                "in ApprovalDecision.patch_unit_decisions — refusing execution",
                context={"patch_unit_id": patch_unit_id},
            )
            return self._deny(
                job_context=job_context,
                patch_unit_id=patch_unit_id,
                decision="refused_not_approved",
                error=not_approved_error,
            )
        try:
            patch_unit = get_patch_unit(contract, patch_unit_id)
        except PatchUnitNotApprovedError as not_in_contract_error:
            return self._deny(
                job_context=job_context,
                patch_unit_id=patch_unit_id,
                decision="refused_not_in_contract",
                error=not_in_contract_error,
            )

        # --- worktree provisioning + defense-in-depth re-checks -------------------
        worktree = self.worktree_factory.create(
            tenant_id=job_context.tenant_id,
            run_id=job_context.run_id,
            patch_unit_id=patch_unit_id,
            base_commit=contract.repo_commit.root,
        )
        if worktree.tenant_id != job_context.tenant_id:
            # Refuse before touching the (foreign) worktree any further —
            # NOT even a rollback() call, since this handle may belong to a
            # different tenant's isolated worktree entirely.
            cross_tenant_error = CrossTenantWorktreeError(
                "WorktreeHandle.tenant_id does not match the executing "
                "JobContext.tenant_id — refusing to touch this worktree",
                context={
                    "job_tenant_id": job_context.tenant_id,
                    "worktree_tenant_id": worktree.tenant_id,
                },
            )
            return self._deny(
                job_context=job_context,
                patch_unit_id=patch_unit_id,
                decision="denied_cross_tenant",
                error=cross_tenant_error,
            )
        if worktree.base_commit != contract.repo_commit.root:
            base_commit_error = BaseCommitMismatchError(
                "WorktreeHandle.base_commit does not match the approved "
                "ChangePlan.repo_commit — refusing execution",
                context={
                    "expected_base_commit": contract.repo_commit.root,
                    "worktree_base_commit": worktree.base_commit,
                },
            )
            return self._deny(
                job_context=job_context,
                patch_unit_id=patch_unit_id,
                decision="denied_base_commit_mismatch",
                error=base_commit_error,
            )

        try:
            for file_write in request.file_writes:
                self._check_liveness(
                    job_context=job_context,
                    start_time=start_time,
                    deadline_seconds=deadline_seconds,
                )
                scope_mod.guard_protected_path(file_write.relative_path)
                scope_mod.guard_scope(
                    file_write.relative_path,
                    patch_unit_files=patch_unit.files,
                    approved_scope=contract.approved_scope,
                )
                scope_mod.resolve_within_worktree(worktree.root, file_write.relative_path)
                worktree.write_file(file_write.relative_path, file_write.content)

            diff = worktree.diff_stat()
            if (
                diff.files_changed > contract.diff_budget.max_files
                or diff.lines_changed > contract.diff_budget.max_lines
            ):
                raise DiffBudgetExceededError(
                    f"diff_stat files_changed={diff.files_changed}/"
                    f"lines_changed={diff.lines_changed} exceeds diff_budget "
                    f"max_files={contract.diff_budget.max_files}/"
                    f"max_lines={contract.diff_budget.max_lines}",
                    context={
                        "files_changed": diff.files_changed,
                        "lines_changed": diff.lines_changed,
                        "max_files": contract.diff_budget.max_files,
                        "max_lines": contract.diff_budget.max_lines,
                    },
                )

            for argv in request.commands:
                self._check_liveness(
                    job_context=job_context,
                    start_time=start_time,
                    deadline_seconds=deadline_seconds,
                )
                commands_mod.guard_command(
                    argv, allowed_transformations=patch_unit.allowed_transformations
                )
                result = self.command_executor.run(argv, worktree=worktree)
                if not result.ok:
                    raise AgentRunnerError(
                        f"command {list(argv)!r} exited non-zero ({result.returncode})",
                        context={"argv": list(argv), "returncode": result.returncode},
                    )

            changed_files = worktree.changed_files()
            worktree_commit = worktree.commit(message=f"patch unit {patch_unit_id}")
        except (AgentRunnerError, JobTimedOutError, JobCancelledError) as exc:
            worktree.rollback()
            execution_error = (
                exc if isinstance(exc, AgentRunnerError) else AgentRunnerError(str(exc))
            )
            decision = _decision_for(execution_error)
            return self._deny(
                job_context=job_context,
                patch_unit_id=patch_unit_id,
                decision=decision,
                error=execution_error,
            )

        # --- success: register artifact, build event payload, audit --------------
        registered_ref = self.artifact_gateway.register(
            tenant_id=job_context.tenant_id,
            run_id=job_context.run_id,
            patch_unit_id=patch_unit_id,
            worktree_commit=worktree_commit,
            base_commit=contract.repo_commit.root,
            changed_files=changed_files,
        )
        evidence_ids = sorted(
            {
                evidence_id
                for hypothesis in contract.hypotheses
                for evidence_id in hypothesis.evidence_ids
            }
        )
        artifact = build_patch_artifact(
            tenant_id=job_context.tenant_id,
            run_id=job_context.run_id,
            patch_unit_id=patch_unit_id,
            worktree_commit=worktree_commit,
            base_commit=contract.repo_commit.root,
            changed_files=changed_files,
            # This job kind (agent-runner) never itself runs quality gates
            # (JobKind.QUALITY_EVAL owns that, a separate later Wave 3
            # unit) — the patch unit's own declared `tests` identifiers
            # (Algorithm §5.2 "tests" field, already required non-empty)
            # stand in as the gate ids a later quality-eval pass must run
            # against this artifact, satisfying PatchArtifact's own
            # `quality_gate_ids` minItems>=1 requirement honestly rather
            # than inventing a placeholder value.
            quality_gate_ids=list(patch_unit.tests),
            evidence_ids=evidence_ids,
            contract_hash=expected_contract_hash,
            rollback_ref=patch_unit.rollback,
            created_at=self.clock.now_iso(),
            registered_ref=registered_ref,
        )
        event_payload = build_patch_unit_completed_payload(
            patch_unit_id=patch_unit_id,
            worktree_commit=worktree_commit,
            manifest_uri=registered_ref.manifest_uri,
            changed_files=changed_files,
            quality_gate_ids=list(patch_unit.tests),
        )
        audit_mod.record_patch_unit_decision(
            self.audit_chain,
            job_context=job_context,
            patch_unit_id=patch_unit_id,
            decision="executed",
            worktree_commit=worktree_commit,
            recorded_at=self.clock.now_iso(),
        )
        status = _advance(_advance(JobStatus.PENDING, JobStatus.RUNNING), JobStatus.SUCCEEDED)
        return PatchUnitOutcome(
            patch_unit_id=patch_unit_id,
            status=status,
            decision="executed",
            worktree_commit=worktree_commit,
            artifact=artifact,
            event_payload=event_payload,
        )

    def _deny(
        self,
        *,
        job_context: JobContext,
        patch_unit_id: str,
        decision: str,
        error: AgentRunnerError,
    ) -> PatchUnitOutcome:
        job_error = _job_error(error)
        audit_mod.record_patch_unit_decision(
            self.audit_chain,
            job_context=job_context,
            patch_unit_id=patch_unit_id,
            decision=decision,
            error_code=error.error_code,
            recorded_at=self.clock.now_iso(),
        )
        terminal_status = _terminal_status_for(error)
        status = _advance(_advance(JobStatus.PENDING, JobStatus.RUNNING), terminal_status)
        return PatchUnitOutcome(
            patch_unit_id=patch_unit_id,
            status=status,
            decision=decision,
            error=job_error,
        )


def _terminal_status_for(error: AgentRunnerError) -> JobStatus:
    if isinstance(error, JobTimedOutError):
        return JobStatus.TIMED_OUT
    if isinstance(error, JobCancelledError):
        return JobStatus.CANCELLED
    return JobStatus.FAILED


def _decision_for(error: AgentRunnerError) -> str:
    mapping: dict[type[AgentRunnerError], str] = {
        JobTimedOutError: "timed_out",
        JobCancelledError: "cancelled",
    }
    for exc_type, decision in mapping.items():
        if isinstance(error, exc_type):
            return decision
    return f"denied_{error.error_code.rsplit('.', 1)[-1]}"


def _aggregate_status(outcomes: Sequence[PatchUnitOutcome]) -> JobStatus:
    if not outcomes:
        return JobStatus.SUCCEEDED
    statuses = {outcome.status for outcome in outcomes}
    if statuses == {JobStatus.SUCCEEDED}:
        return JobStatus.SUCCEEDED
    if JobStatus.CANCELLED in statuses:
        return JobStatus.CANCELLED
    if JobStatus.TIMED_OUT in statuses:
        return JobStatus.TIMED_OUT
    return JobStatus.FAILED


__all__ = [
    "FileWrite",
    "JobRunResult",
    "PatchUnitOutcome",
    "PatchUnitRequest",
    "PatchUnitRunner",
]
