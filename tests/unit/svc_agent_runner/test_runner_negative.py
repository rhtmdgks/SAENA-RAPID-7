"""`PatchUnitRunner` — fail-closed negative tests (mission-required list).

Covers every ABSOLUTELY FORBIDDEN case named in the mission instruction:
execution before approval, writing outside approved scope, protected-path
write, git push/kubectl/helm/deploy commands in a patch, over-limit diff,
non-allowlisted command, symlink/traversal escape, cross-tenant worktree
access — plus unapproved-contract-hash execution and a forged
ApprovalDecision.
"""

from __future__ import annotations

import pytest
from runner_factories import (
    BASE_COMMIT,
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    TENANT_A,
    TENANT_B,
    build_approval_decision,
    build_change_plan,
)
from saena_agent_runner.approval import ApprovalDecision, parse_approval_decision
from saena_agent_runner.artifact import FakeArtifactRegistryGateway
from saena_agent_runner.clock import FakeClock
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.errors import (
    ApprovalContractHashMismatchError,
    ApprovalIdentityMismatchError,
)
from saena_agent_runner.runner import FileWrite, PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory
from saena_domain.audit import InMemoryAuditChain
from saena_domain.execution import JobStatus


def _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock):
    return PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )


# --- 1. execution before approval / unapproved-contract-hash --------------------------


def test_unapproved_contract_hash_execution_attempt_blocks_all_execution(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """NEGATIVE: unapproved-contract-hash execution attempt — the whole run
    must be refused before any worktree is even created."""
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision(contract_hash="sha256:" + "9" * 64))
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock)

    with pytest.raises(ApprovalContractHashMismatchError):
        runner.run(
            job_context=job_context,
            contract=contract,
            expected_contract_hash=CONTRACT_HASH,
            approval=approval,
            requests=[
                PatchUnitRequest(
                    patch_unit_id=PATCH_UNIT_ID,
                    file_writes=(FileWrite("apps/web/docs/readme.md", b"x"),),
                )
            ],
        )
    assert worktree_factory.created == [], "no worktree may ever be created without approval"
    assert command_executor.invocations == []
    assert any(
        e.error_code == "saena.agent_runner.approval_contract_hash_mismatch"
        for e in audit_chain.entries
    )


def test_forged_approval_decision_identity_mismatch_blocks_execution(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """NEGATIVE: a forged ApprovalDecision claiming a DIFFERENT tenant_id's
    run must not authorize this run."""
    contract = parse_change_plan(build_change_plan())
    forged = ApprovalDecision.model_validate(build_approval_decision(tenant_id=TENANT_B))
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock)

    with pytest.raises(ApprovalIdentityMismatchError):
        runner.run(
            job_context=job_context,
            contract=contract,
            expected_contract_hash=CONTRACT_HASH,
            approval=forged,
            requests=[PatchUnitRequest(patch_unit_id=PATCH_UNIT_ID)],
        )
    assert worktree_factory.created == []


# --- 2. patch unit not in the approved set --------------------------------------------


def test_patch_unit_not_named_in_approval_refused_without_touching_worktree(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())  # only approves PU-01
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock)

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[PatchUnitRequest(patch_unit_id="PU-99-not-approved")],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "refused_not_approved"
    assert worktree_factory.created == [], "an unapproved patch unit must never get a worktree"


# --- 3. out-of-scope write --------------------------------------------------------------


def test_out_of_scope_write_denied_and_rolled_back(
    job_context,
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
                    "files": ["apps/api/secret_config.py"],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{PATCH_UNIT_ID}",
                }
            ],
        )
    )
    approval = parse_approval_decision(build_approval_decision())
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock)

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/api/secret_config.py", b"malicious"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_out_of_scope_write"
    assert outcome.worktree_commit is None
    assert outcome.artifact is None
    handle = worktree_factory.created[0]
    assert not (handle.root / "apps" / "api" / "secret_config.py").exists()


def test_protected_path_write_denied_regardless_of_scope(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(
        build_change_plan(
            approved_scope=["packages/contracts/*"],
            patch_units=[
                {
                    "id": PATCH_UNIT_ID,
                    "files": ["packages/contracts/evil.schema.json"],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{PATCH_UNIT_ID}",
                }
            ],
        )
    )
    approval = parse_approval_decision(build_approval_decision())
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock)

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("packages/contracts/evil.schema.json", b"x"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_protected_path_write"


# --- 4. over-limit diff -----------------------------------------------------------------


def test_diff_over_budget_denied_and_rolled_back(
    job_context,
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
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock)

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
    assert not (handle.root / "apps" / "web" / "docs" / "big.md").exists()


# --- 5. non-allowlisted command + deploy/push command in a patch ------------------------


def test_non_allowlisted_command_denied(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock)

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                commands=(("rm", "-rf", "/"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_command_not_allowlisted"
    assert command_executor.invocations == []


@pytest.mark.parametrize(
    "forbidden_argv",
    [
        ("git", "push", "origin", "main"),
        ("kubectl", "apply", "-f", "deploy.yaml"),
        ("helm", "upgrade", "saena-forge", "."),
    ],
)
def test_deploy_or_push_command_in_patch_unit_denied_even_if_contract_allows_it(
    job_context,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
    forbidden_argv: tuple[str, ...],
) -> None:
    """NEGATIVE (mission ABSOLUTELY FORBIDDEN): git push / kubectl apply /
    helm upgrade must be refused even if a (malicious/buggy) contract names
    the exact command string in its own `allowed_transformations`."""
    contract = parse_change_plan(
        build_change_plan(
            patch_units=[
                {
                    "id": PATCH_UNIT_ID,
                    "files": ["apps/web/docs/readme.md"],
                    "allowed_transformations": [" ".join(forbidden_argv)],
                    "tests": ["t"],
                    "rollback": f"git-revert:{PATCH_UNIT_ID}",
                }
            ]
        )
    )
    approval = parse_approval_decision(build_approval_decision())
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock)

    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[PatchUnitRequest(patch_unit_id=PATCH_UNIT_ID, commands=(forbidden_argv,))],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_forbidden_command"
    assert command_executor.invocations == []


# --- 6. symlink / traversal escape -------------------------------------------------------


def test_symlink_traversal_escape_write_denied(
    job_context,
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
                    "files": ["apps/web/docs/escape/payload.txt"],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{PATCH_UNIT_ID}",
                }
            ],
        )
    )
    approval = parse_approval_decision(build_approval_decision())

    handle = worktree_factory.create(
        tenant_id=TENANT_A, run_id="run-0001", patch_unit_id=PATCH_UNIT_ID, base_commit=BASE_COMMIT
    )
    outside_dir = handle.root.parent / "outside-escape-target"
    outside_dir.mkdir(exist_ok=True)
    (handle.root / "apps" / "web" / "docs").mkdir(parents=True, exist_ok=True)
    (handle.root / "apps" / "web" / "docs" / "escape").symlink_to(
        outside_dir, target_is_directory=True
    )

    class _ReuseFactory:
        def create(self, *, tenant_id, run_id, patch_unit_id, base_commit):
            return handle

    result = runner_with_factory(
        _ReuseFactory(), command_executor, artifact_gateway, audit_chain, clock
    ).run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/escape/payload.txt", b"escaped content"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_path_traversal"
    assert not (outside_dir / "payload.txt").exists()


def runner_with_factory(worktree_factory, command_executor, artifact_gateway, audit_chain, clock):
    return PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )


# --- 7. cross-tenant worktree access -----------------------------------------------------


def test_cross_tenant_worktree_access_denied(
    job_context,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """NEGATIVE: even if a (buggy/malicious) WorktreeFactory hands back a
    worktree belonging to a DIFFERENT tenant, the runner must refuse to
    touch it — defense-in-depth beyond trusting the factory."""
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())
    inner_factory = FakeWorktreeFactory()

    class _CrossTenantFactory:
        def create(self, *, tenant_id, run_id, patch_unit_id, base_commit):
            # Maliciously ignores the requested tenant_id (TENANT_A) and
            # returns a worktree provisioned for a DIFFERENT tenant.
            return inner_factory.create(
                tenant_id=TENANT_B,
                run_id=run_id,
                patch_unit_id=patch_unit_id,
                base_commit=base_commit,
            )

    runner = runner_with_factory(
        _CrossTenantFactory(), command_executor, artifact_gateway, audit_chain, clock
    )
    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/readme.md", b"x"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_cross_tenant"
    assert command_executor.invocations == []
    inner_factory.cleanup()


# --- 8. base-commit pinning ---------------------------------------------------------------


def test_base_commit_mismatch_denied(
    job_context,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(build_change_plan(repo_commit=BASE_COMMIT))
    approval = parse_approval_decision(build_approval_decision())
    inner_factory = FakeWorktreeFactory()

    class _WrongBaseCommitFactory:
        def create(self, *, tenant_id, run_id, patch_unit_id, base_commit):
            return inner_factory.create(
                tenant_id=tenant_id,
                run_id=run_id,
                patch_unit_id=patch_unit_id,
                base_commit="f" * 40,
            )

    runner = runner_with_factory(
        _WrongBaseCommitFactory(), command_executor, artifact_gateway, audit_chain, clock
    )
    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[PatchUnitRequest(patch_unit_id=PATCH_UNIT_ID)],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_base_commit_mismatch"
    inner_factory.cleanup()
