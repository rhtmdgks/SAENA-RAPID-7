"""Rollback verification gate (testing-strategy.md sec F-7): "other tenants
unaffected" after a rollback.

Wired against the REAL cross-tenant defense-in-depth check
`PatchUnitRunner._run_one`'s `WorktreeHandle.tenant_id != job_context.
tenant_id` guard (`runner.py` module docstring point 2b: "worktree
provisioning + defense-in-depth re-checks (tenant/base-commit) —
`CrossTenantWorktreeError`... if a (buggy/malicious) factory handed back a
mismatched handle") plus a same-process, two-tenant scenario proving tenant
B's own successful run and audit trail are completely unaffected by tenant
A's denied-and-rolled-back attempt sharing the SAME `InMemoryAuditChain`/
`WorktreeFactory` instances.
"""

from __future__ import annotations

from runner_factories import (
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    TENANT_A,
    TENANT_B,
    VALID_SKILL_BUNDLE_PIN,
    build_approval_decision,
    build_change_plan,
    build_job_context,
    make_skill_bundle_source,
)
from saena_agent_runner.approval import parse_approval_decision
from saena_agent_runner.artifact import FakeArtifactRegistryGateway
from saena_agent_runner.clock import FakeClock
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.runner import FileWrite, PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory
from saena_domain.audit import InMemoryAuditChain


def test_cross_tenant_worktree_handoff_is_refused_worktree_never_touched(
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(build_change_plan(tenant_id=TENANT_A))
    approval = parse_approval_decision(build_approval_decision(tenant_id=TENANT_A))
    tenant_b_factory = FakeWorktreeFactory()

    class _WrongTenantFactory:
        """Simulates a buggy/compromised factory that hands tenant A's job
        a worktree actually provisioned for tenant B."""

        def create(self, *, tenant_id, run_id, patch_unit_id, base_commit):
            return tenant_b_factory.create(
                tenant_id=TENANT_B,
                run_id=run_id,
                patch_unit_id=patch_unit_id,
                base_commit=base_commit,
            )

    runner = PatchUnitRunner(
        worktree_factory=_WrongTenantFactory(),
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
        skill_bundle_source=make_skill_bundle_source(),
    )

    result = runner.run(
        job_context=build_job_context(tenant_id=TENANT_A),
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        expected_skill_bundle_hash=VALID_SKILL_BUNDLE_PIN,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/readme.md", b"tenant A attempt"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.decision == "denied_cross_tenant"
    assert command_executor.invocations == [], (
        "the foreign worktree is never touched, not even read"
    )

    tenant_b_factory.cleanup()


def test_tenant_bs_own_successful_run_is_unaffected_by_tenant_as_rollback(
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """Two DIFFERENT tenants, sharing the same `WorktreeFactory`/
    `InMemoryAuditChain` process-level instances (as two jobs on the same
    node genuinely would) — tenant A's patch unit is denied+rolled back;
    tenant B's own, entirely separate patch unit executes successfully and
    is completely unaffected: distinct worktree root, distinct audit
    entries, no cross-contamination of either's state."""
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
        skill_bundle_source=make_skill_bundle_source(),
    )

    # tenant A: denied (out-of-scope write) and rolled back.
    tenant_a_contract = parse_change_plan(
        build_change_plan(
            tenant_id=TENANT_A,
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
    tenant_a_approval = parse_approval_decision(build_approval_decision(tenant_id=TENANT_A))
    tenant_a_result = runner.run(
        job_context=build_job_context(tenant_id=TENANT_A),
        contract=tenant_a_contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=tenant_a_approval,
        expected_skill_bundle_hash=VALID_SKILL_BUNDLE_PIN,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/api/secret_config.py", b"malicious"),),
            )
        ],
    )
    assert tenant_a_result.outcomes[0].decision == "denied_out_of_scope_write"

    # tenant B: a wholly separate, legitimate run — same process, same
    # shared `WorktreeFactory`/`InMemoryAuditChain` instances.
    tenant_b_contract = parse_change_plan(build_change_plan(tenant_id=TENANT_B))
    tenant_b_approval = parse_approval_decision(build_approval_decision(tenant_id=TENANT_B))
    tenant_b_result = runner.run(
        job_context=build_job_context(tenant_id=TENANT_B),
        contract=tenant_b_contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=tenant_b_approval,
        expected_skill_bundle_hash=VALID_SKILL_BUNDLE_PIN,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/readme.md", b"tenant B's own fix"),),
            )
        ],
    )
    tenant_b_outcome = tenant_b_result.outcomes[0]
    assert tenant_b_outcome.decision == "executed"
    assert tenant_b_outcome.artifact is not None
    assert tenant_b_outcome.artifact["tenant_id"] == TENANT_B

    # worktree isolation: two distinct roots, tenant B's root has no trace
    # of tenant A's attempted (and rolled back) write.
    tenant_a_handle, tenant_b_handle = worktree_factory.created
    assert tenant_a_handle.tenant_id == TENANT_A
    assert tenant_b_handle.tenant_id == TENANT_B
    assert tenant_a_handle.root != tenant_b_handle.root
    assert not (tenant_b_handle.root / "apps" / "api" / "secret_config.py").exists()

    # audit isolation: each tenant's own decision is scoped to itself.
    tenant_scopes = {(e.tenant_id.root, e.payload["decision"]) for e in audit_chain.entries}
    assert (TENANT_A, "denied_out_of_scope_write") in tenant_scopes
    assert (TENANT_B, "executed") in tenant_scopes
    ok, bad_index = audit_chain.verify()
    assert ok is True and bad_index is None
