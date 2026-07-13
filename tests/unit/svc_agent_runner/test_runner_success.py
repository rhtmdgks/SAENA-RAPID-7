"""`PatchUnitRunner` — happy-path execution end-to-end."""

from __future__ import annotations

from runner_factories import (
    BASE_COMMIT,
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
from saena_domain.execution import JobStatus


def test_approved_patch_unit_executes_and_produces_artifact_and_event(
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
        clock=clock,
    )
    request = PatchUnitRequest(
        patch_unit_id=PATCH_UNIT_ID,
        file_writes=(FileWrite("apps/web/docs/readme.md", b"hello world\n"),),
        commands=(("pytest", "-q"),),
    )

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[request],
    )

    assert result.job_status == JobStatus.SUCCEEDED
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.SUCCEEDED
    assert outcome.decision == "executed"
    assert outcome.worktree_commit is not None
    assert outcome.artifact is not None
    assert outcome.artifact["base_commit"] == BASE_COMMIT
    assert outcome.artifact["contract_hash"] == CONTRACT_HASH
    assert outcome.event_payload is not None
    assert outcome.event_payload["patch_unit_id"] == PATCH_UNIT_ID
    assert outcome.event_payload["worktree_commit"] == outcome.worktree_commit

    # Command actually invoked via the fake executor (never a real subprocess).
    assert command_executor.invocations == [("pytest", "-q")]
    # Artifact registered via the gateway, never a direct blob write.
    assert len(artifact_gateway.registrations) == 1
    # Audit trail carries the "executed" decision.
    assert any(entry.payload.get("decision") == "executed" for entry in audit_chain.entries)
    assert audit_chain.verify() == (True, None)


def test_multiple_approved_patch_units_each_get_isolated_worktrees(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract_dict = build_change_plan(
        approved_scope=["apps/web/docs/*"],
        patch_units=[
            {
                "id": "PU-01",
                "files": ["apps/web/docs/a.md"],
                "allowed_transformations": ["git commit"],
                "tests": ["t1"],
                "rollback": "git-revert:PU-01",
            },
            {
                "id": "PU-02",
                "files": ["apps/web/docs/b.md"],
                "allowed_transformations": ["git commit"],
                "tests": ["t2"],
                "rollback": "git-revert:PU-02",
            },
        ],
    )
    contract = parse_change_plan(contract_dict)
    approval = parse_approval_decision(
        build_approval_decision(
            patch_unit_decisions=[
                {"patch_unit_id": "PU-01", "decision": "approved"},
                {"patch_unit_id": "PU-02", "decision": "approved"},
            ]
        )
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
                patch_unit_id="PU-01",
                file_writes=(FileWrite("apps/web/docs/a.md", b"a"),),
            ),
            PatchUnitRequest(
                patch_unit_id="PU-02",
                file_writes=(FileWrite("apps/web/docs/b.md", b"b"),),
            ),
        ],
    )
    assert result.job_status == JobStatus.SUCCEEDED
    assert {o.patch_unit_id for o in result.outcomes} == {"PU-01", "PU-02"}
    roots = {handle.root for handle in worktree_factory.created}
    assert len(roots) == 2, "each patch unit must get its own isolated worktree root"
