"""F-4 Code conflict (k3s spec §10 row 4, failure-mode matrix `F-4`).

Fixture: two agents (two patch units of the SAME `ChangePlan`, run in the
SAME job) both modify the same route file — `apps/web/routes/checkout.tsx`.
k3s: "two agents modify same route → isolated worktrees, integrator only".

Wired against the REAL `saena_agent_runner.worktree.WorktreeFactory`/
`PatchUnitRunner` isolation boundary: `WorktreeFactory.create` is keyed by
the full `(tenant_id, run_id, patch_unit_id)` triple (`worktree.py` module
docstring: "Every `WorktreeHandle` is scoped to exactly one ... triple") —
two patch units NEVER share a filesystem root, so two agents "modifying the
same route" can never race or corrupt each other's writes; each commits its
OWN isolated worktree independently. Reconciling the two into one shared
route is then, structurally, NOT something this package can do at all
(ADR-0004 "quality-eval: 빌드 실행 권한만, Git write 없음" / this package's own
scope note that its Git write capability never extends past one patch
unit's own isolated worktree) — "integrator only" is proven by absence: no
API in this package merges two worktrees together.
"""

from __future__ import annotations

from runner_factories import (
    CONTRACT_HASH,
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
from saena_domain.execution import JobContext, JobStatus

CONTESTED_ROUTE = "apps/web/routes/checkout.tsx"
AGENT_A_UNIT = "PU-AGENT-A"
AGENT_B_UNIT = "PU-AGENT-B"


def _two_agent_contract():
    return parse_change_plan(
        build_change_plan(
            approved_scope=["apps/web/routes/*"],
            patch_units=[
                {
                    "id": AGENT_A_UNIT,
                    "files": [CONTESTED_ROUTE],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{AGENT_A_UNIT}",
                },
                {
                    "id": AGENT_B_UNIT,
                    "files": [CONTESTED_ROUTE],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{AGENT_B_UNIT}",
                },
            ],
        )
    )


def test_two_agents_writing_the_same_route_get_fully_isolated_worktrees(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = _two_agent_contract()
    approval = parse_approval_decision(
        build_approval_decision(
            patch_unit_decisions=[
                {"patch_unit_id": AGENT_A_UNIT, "decision": "approved"},
                {"patch_unit_id": AGENT_B_UNIT, "decision": "approved"},
            ]
        )
    )
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
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
                patch_unit_id=AGENT_A_UNIT,
                file_writes=(FileWrite(CONTESTED_ROUTE, b"export default function AgentA() {}"),),
            ),
            PatchUnitRequest(
                patch_unit_id=AGENT_B_UNIT,
                file_writes=(FileWrite(CONTESTED_ROUTE, b"export default function AgentB() {}"),),
            ),
        ],
    )

    assert result.job_status == JobStatus.SUCCEEDED
    outcome_a, outcome_b = result.outcomes
    assert outcome_a.status == JobStatus.SUCCEEDED
    assert outcome_b.status == JobStatus.SUCCEEDED

    # isolated worktrees: two distinct, non-overlapping filesystem roots —
    # neither agent's write is visible in the other's worktree at all.
    assert len(worktree_factory.created) == 2
    root_a, root_b = (h.root for h in worktree_factory.created)
    assert root_a != root_b
    assert root_a not in root_b.parents
    assert root_b not in root_a.parents

    content_a = (root_a / CONTESTED_ROUTE).read_bytes()
    content_b = (root_b / CONTESTED_ROUTE).read_bytes()
    assert b"AgentA" in content_a
    assert b"AgentB" not in content_a
    assert b"AgentB" in content_b
    assert b"AgentA" not in content_b

    # independently committed — two distinct worktree_commits, two distinct
    # artifacts. Reconciling them into ONE shared route file is a step this
    # package structurally never performs (no merge API exists here) —
    # "integrator only" is exactly the absence proven by these two outcomes
    # remaining two separate, un-merged artifacts.
    assert outcome_a.worktree_commit != outcome_b.worktree_commit
    assert outcome_a.artifact is not None
    assert outcome_b.artifact is not None
    assert outcome_a.artifact["worktree_commit"] != outcome_b.artifact["worktree_commit"]


def test_a_patch_unit_cannot_write_a_file_outside_its_own_declared_files_list(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """A second dimension of the same failure mode: agent A's patch unit
    does not itself declare `CONTESTED_ROUTE`, only a DIFFERENT file — even
    though `CONTESTED_ROUTE` is inside the plan-level `approved_scope`
    glob, `guard_scope` still refuses it (each patch unit's OWN `files`
    manifest is a second, independent boundary, not a rubber stamp)."""
    contract = parse_change_plan(
        build_change_plan(
            approved_scope=["apps/web/routes/*"],
            patch_units=[
                {
                    "id": AGENT_A_UNIT,
                    "files": ["apps/web/routes/other-page.tsx"],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{AGENT_A_UNIT}",
                }
            ],
        )
    )
    approval = parse_approval_decision(
        build_approval_decision(
            patch_unit_decisions=[{"patch_unit_id": AGENT_A_UNIT, "decision": "approved"}]
        )
    )
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
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
                patch_unit_id=AGENT_A_UNIT,
                file_writes=(FileWrite(CONTESTED_ROUTE, b"unrelated agent overreach"),),
            )
        ],
    )
    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_out_of_scope_write"
