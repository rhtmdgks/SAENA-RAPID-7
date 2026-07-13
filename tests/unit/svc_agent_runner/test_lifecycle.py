"""Timeout (`active_deadline_seconds`) + cooperative cancellation."""

from __future__ import annotations

from runner_factories import (
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    VALID_SKILL_BUNDLE_PIN,
    build_approval_decision,
    build_change_plan,
    make_skill_bundle_source,
)
from saena_agent_runner.approval import parse_approval_decision
from saena_agent_runner.artifact import FakeArtifactRegistryGateway
from saena_agent_runner.clock import FakeClock
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.runner import FileWrite, PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory
from saena_domain.audit import InMemoryAuditChain
from saena_domain.execution import JobKind, JobStatus, resource_limits_for


class _AlwaysCancel:
    def is_cancellation_requested(self, *, job_context) -> bool:
        return True


class _NeverCancel:
    def is_cancellation_requested(self, *, job_context) -> bool:
        return False


class _JumpingClock:
    """`Clock` whose `monotonic()` jumps PAST the deadline on its second
    call — simulates real elapsed time passing DURING `PatchUnitRunner.run`
    (the first call captures `start_time`; the second, inside
    `_check_liveness`, must observe an elapsed duration past the deadline).
    A plain `FakeClock.advance()` called before `run()` cannot exercise this
    path, since `start_time` is captured fresh at the top of `run()` — both
    calls would see the same already-advanced value, and elapsed time would
    read as zero.
    """

    def __init__(self, *, jump_to: float) -> None:
        self._calls = 0
        self._jump_to = jump_to

    def monotonic(self) -> float:
        self._calls += 1
        return 0.0 if self._calls == 1 else self._jump_to

    def now_iso(self) -> str:
        return "2026-01-01T00:00:00Z"


def test_cancellation_signal_aborts_execution_and_rolls_back(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        cancellation_signal=_AlwaysCancel(),
        clock=clock,
        skill_bundle_source=make_skill_bundle_source(),
    )
    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        expected_skill_bundle_hash=VALID_SKILL_BUNDLE_PIN,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/readme.md", b"x"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.CANCELLED
    assert outcome.decision == "cancelled"
    assert result.job_status == JobStatus.CANCELLED
    assert outcome.worktree_commit is None
    handle = worktree_factory.created[0]
    assert not (handle.root / "apps" / "web" / "docs" / "readme.md").exists()


def test_active_deadline_exceeded_times_out_and_rolls_back(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())
    deadline = resource_limits_for(JobKind.AGENT_RUNNER).active_deadline_seconds
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        cancellation_signal=_NeverCancel(),
        clock=_JumpingClock(jump_to=deadline + 1),
        skill_bundle_source=make_skill_bundle_source(),
    )

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        expected_skill_bundle_hash=VALID_SKILL_BUNDLE_PIN,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/readme.md", b"x"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.TIMED_OUT
    assert outcome.decision == "timed_out"
    assert result.job_status == JobStatus.TIMED_OUT
