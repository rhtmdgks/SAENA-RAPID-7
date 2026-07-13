"""Rollback verification gate (testing-strategy.md sec F-7): patch-unit
rollback leaves no partial commit; failed-worktree cleanup.

Wired against the REAL `saena_agent_runner.worktree.FakeWorktreeHandle.
rollback()` (its own docstring's guarantee: "after this call, the
worktree's on-disk state is exactly what it was immediately after
construction (or immediately after the last successful `commit()`)") and
`PatchUnitRunner._run_one`'s own `except (...): worktree.rollback()`
boundary (module docstring point 3: "no partial commit is ever left
behind, and no artifact/event is ever produced for that unit").
"""

from __future__ import annotations

from runner_factories import (
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    build_approval_decision,
    build_change_plan,
)
from saena_agent_runner.approval import parse_approval_decision
from saena_agent_runner.artifact import FakeArtifactRegistryGateway
from saena_agent_runner.clock import FakeClock
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.runner import FileWrite, PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory
from saena_domain.audit import InMemoryAuditChain
from saena_domain.execution import JobContext, JobStatus


def test_diff_budget_denial_leaves_worktree_exactly_at_pre_write_state(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(
        build_change_plan(
            approved_scope=["apps/web/docs/*"],
            patch_units=[
                {
                    "id": PATCH_UNIT_ID,
                    "files": ["apps/web/docs/big.md"],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{PATCH_UNIT_ID}",
                }
            ],
            max_files=1,
            max_lines=2,
        )
    )
    approval = parse_approval_decision(build_approval_decision())
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/big.md", b"l1\nl2\nl3\nl4\nl5\n"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_diff_budget_exceeded"

    handle = worktree_factory.created[0]
    # no partial commit: the write is fully discarded, not partially applied.
    assert not (handle.root / "apps" / "web" / "docs" / "big.md").exists()
    assert handle.changed_files() == []
    diff = handle.diff_stat()
    assert diff.files_changed == 0
    assert diff.lines_changed == 0
    assert handle.last_commit is None
    # no artifact/event produced for a rolled-back unit.
    assert outcome.artifact is None
    assert outcome.event_payload is None


def test_command_failure_denial_rolls_back_writes_that_already_landed(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """A patch unit whose file write SUCCEEDS but whose subsequent command
    fails (non-allowlisted) — proves rollback discards writes that already
    landed on disk before the failure, not merely writes still in flight."""
    from saena_agent_runner.worktree import CommandResult

    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())
    command_executor.register_result(
        ("pytest", "-q"), CommandResult(returncode=1, stderr="1 failed")
    )
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/readme.md", b"landed content"),),
                commands=(("git", "add", "."), ("pytest", "-q")),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED

    handle = worktree_factory.created[0]
    assert not (handle.root / "apps" / "web" / "docs" / "readme.md").exists()
    assert handle.changed_files() == []


def test_failed_worktree_cleanup_removes_every_provisioned_root_from_disk() -> None:
    """`WorktreeFactory.cleanup()` (test-double, mirrors a real adapter's own
    obligation to reclaim a failed run's disk space) removes every worktree
    root it provisioned this run — no orphaned failed-worktree directory
    survives a cleanup pass."""
    factory = FakeWorktreeFactory()
    handle_one = factory.create(
        tenant_id="acme-co", run_id="run-0001", patch_unit_id="PU-01", base_commit="a" * 40
    )
    handle_two = factory.create(
        tenant_id="acme-co", run_id="run-0001", patch_unit_id="PU-02", base_commit="a" * 40
    )
    handle_one.write_file("x.txt", b"some in-flight write")
    assert handle_one.root.exists()
    assert handle_two.root.exists()

    factory.cleanup()

    assert not handle_one.root.exists()
    assert not handle_two.root.exists()
