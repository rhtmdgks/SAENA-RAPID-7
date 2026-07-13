"""F-8 Scope creep (k3s spec §10 row 8, failure-mode matrix `F-8`).

Fixture: an agent asked to fix one route also "helpfully" refactors an
unrelated file it noticed along the way. k3s: "agent adds unrelated refactor
→ Ponytail + patch review rejects".

Wired against TWO real layers ("patch review" = the Release Gate's own
boundary gates; "Ponytail" — the mission's own patch-review/approved-scope
enforcement persona — has no separate service in this repo yet, so this
test wires the concrete mechanism Ponytail's review would be BACKED BY):

1. `saena_agent_runner.scope.guard_scope` (`runner.py`'s own per-write
   boundary, checked for EVERY write before a byte reaches disk) — the
   unrelated file is outside the executing patch unit's own `files`
   manifest AND/OR the plan's `approved_scope` globs → `OutOfScopeWriteError`,
   rolled back, no partial state.
2. `saena_quality_eval.gates.gate_boundary` — the SAME scope-creep shape as
   a Release Gate row: any changed file outside `approved_scope` fails
   `boundary`, independent of whether execution-time enforcement somehow
   let it through (defense in depth — two independently-reportable rejects
   for the identical shape, matching this package's own "pluggable checks
   over adapter output" design).
"""

from __future__ import annotations

from factories import build_gate_input_bundle, build_quality_eval_request
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
from saena_domain.execution import JobContext, JobStatus
from saena_quality_eval.engine import run_quality_evaluation
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gates import gate_boundary
from saena_quality_eval.inputs import BoundaryOutcome

REQUESTED_FIX = "apps/web/routes/checkout.tsx"
UNRELATED_REFACTOR_TARGET = "apps/web/lib/unrelated_utils.ts"


def test_agent_runner_denies_and_rolls_back_the_unrelated_refactor_write(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    contract = parse_change_plan(
        build_change_plan(
            approved_scope=["apps/web/routes/*"],
            patch_units=[
                {
                    "id": PATCH_UNIT_ID,
                    "files": [REQUESTED_FIX],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{PATCH_UNIT_ID}",
                }
            ],
        )
    )
    approval = parse_approval_decision(build_approval_decision())
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
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(
                    FileWrite(REQUESTED_FIX, b"the requested fix"),
                    FileWrite(UNRELATED_REFACTOR_TARGET, b"an unrelated 'while I'm here' refactor"),
                ),
            )
        ],
    )

    outcome = result.outcomes[0]
    assert outcome.status == JobStatus.FAILED
    assert outcome.decision == "denied_out_of_scope_write"
    assert outcome.worktree_commit is None
    assert outcome.artifact is None

    # partial-state-absence: neither write survives — guard_scope fires on
    # the SECOND (out-of-scope) write, and the whole patch unit is rolled
    # back, including the FIRST, otherwise-legitimate write.
    handle = worktree_factory.created[0]
    assert not (handle.root / UNRELATED_REFACTOR_TARGET).exists()
    assert not (handle.root / REQUESTED_FIX).exists()


def test_quality_eval_boundary_gate_flags_the_unrelated_refactor_file() -> None:
    outcome = gate_boundary(
        BoundaryOutcome(
            changed_files=(REQUESTED_FIX, UNRELATED_REFACTOR_TARGET),
            approved_scope_globs=("apps/web/routes/*",),
            out_of_scope_files=(UNRELATED_REFACTOR_TARGET,),
        )
    )
    assert outcome.gate_id == GateId.BOUNDARY
    assert outcome.passed is False
    failure = outcome.failures[0]
    assert UNRELATED_REFACTOR_TARGET in failure.redacted_detail["out_of_scope_files"]


def test_release_gate_forbids_promotion_on_scope_creep_end_to_end() -> None:
    gate_inputs = build_gate_input_bundle(
        boundary=BoundaryOutcome(
            changed_files=(REQUESTED_FIX, UNRELATED_REFACTOR_TARGET),
            approved_scope_globs=("apps/web/routes/*",),
            out_of_scope_files=(UNRELATED_REFACTOR_TARGET,),
        )
    )
    request = build_quality_eval_request(gate_inputs=gate_inputs)

    outcome = run_quality_evaluation(request)

    assert outcome.forbids_promotion is True
    assert outcome.gate_result_for(GateId.BOUNDARY)["status"] == "failed"
