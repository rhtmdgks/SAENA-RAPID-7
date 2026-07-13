"""F-5 Skill compromise (k3s spec §10 row 5, failure-mode matrix `F-5`).

Fixture: a third-party skill (or a compromised local one) silently changes
the COMMANDS a patch unit is allowed to run — e.g. widening
`allowed_transformations` to include a destructive/unreviewed command —
after the contract it lives inside was approved and hashed. k3s spec: "third
-party skill changes commands → pinned hash mismatch → run blocked".

This repository has no separate `skill_bundle_hash` validator implemented
yet (`docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §9.1 lists
`skill_bundle_hash` in the run-trace envelope shape, but no service owns
verifying it against a pinned value — confirmed by repo-wide search, no
`skill_bundle_hash`/`SkillBundle` implementation exists under `packages/`
or `services/`; noted here, not fixed — out of this patch unit's exclusive
write paths). The REAL, already-implemented hash-pin mechanism this failure
mode maps onto 1:1 is `ActionContract.contract_hash` /
`ApprovalDecision.contract_hash` — a signed, content-derived hash covering
`patch_units[].allowed_transformations` (among every other field). A skill
that mutates commands changes the contract's own recomputed hash, which is
EXACTLY the "pinned hash mismatch" k3s describes — this test proves that
mechanism blocks the tampered run, at BOTH layers that check it:

1. `saena_hooks_runtime.contract.validate_contract` /
   `hooks.session_start.verify_run_context` — `CONTRACT_HASH_MISMATCH` DENY.
2. `saena_agent_runner.approval.verify_approval` — a stale
   `ApprovalDecision.contract_hash` (signed against the PRE-tamper contract)
   no longer matches the post-tamper contract's `expected_contract_hash` —
   `ApprovalContractHashMismatchError`, run blocked before any worktree is
   touched.
"""

from __future__ import annotations

import dataclasses

import pytest
from hooks_runtime_factories import (
    RUN_ID,
    TENANT_ID,
    TRACE_ID,
    TS,
    make_budget,
    make_contract,
    make_patch_unit,
)
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
from saena_agent_runner.errors import ApprovalContractHashMismatchError
from saena_agent_runner.runner import PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory
from saena_domain.audit import InMemoryAuditChain
from saena_domain.execution import JobContext
from saena_hooks_runtime.contract import compute_contract_hash, validate_contract
from saena_hooks_runtime.hooks.session_start import SessionStartInput, session_start
from saena_hooks_runtime.models import Decision, ReasonCode

ORIGINAL_TRANSFORMATIONS = ("metadata-edit",)
#: What the compromised third-party skill silently rewrites the patch unit's
#: allowed commands to — a destructive command never reviewed/approved.
SKILL_TAMPERED_TRANSFORMATIONS = ("metadata-edit", "rm -rf node_modules")


def test_hooks_runtime_contract_hash_pin_blocks_skill_tampered_commands() -> None:
    approved_contract = make_contract(
        patch_units=(make_patch_unit(allowed_transformations=ORIGINAL_TRANSFORMATIONS),)
    )
    # Sanity: the originally-approved contract is itself hash-valid.
    assert validate_contract(approved_contract) is None

    # The compromised skill mutates the LIVE contract object's commands
    # in-place-equivalent (a new object with the tampered field) but the
    # `contract_hash` string travelling alongside it is the STALE,
    # pre-tamper one — exactly what "a skill changes commands" without
    # re-earning approval looks like on the wire.
    tampered_patch_unit = dataclasses.replace(
        approved_contract.patch_units[0], allowed_transformations=SKILL_TAMPERED_TRANSFORMATIONS
    )
    tampered_contract = dataclasses.replace(
        approved_contract,
        patch_units=(tampered_patch_unit,),
        # contract_hash intentionally left as the ORIGINAL (stale) value.
    )

    assert tampered_contract.contract_hash != compute_contract_hash(tampered_contract)
    assert validate_contract(tampered_contract) == ReasonCode.CONTRACT_HASH_MISMATCH

    decision = session_start(
        SessionStartInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=tampered_contract,
            worktree_dirty=False,
            policy_signature_valid=True,
            secret_findings=(),
            budget=make_budget("session_start"),
        )
    )
    assert decision.decision == Decision.DENY
    assert decision.blocked is True
    assert decision.reason_code == ReasonCode.CONTRACT_HASH_MISMATCH
    assert decision.audit.reason_code == ReasonCode.CONTRACT_HASH_MISMATCH


def test_agent_runner_blocks_execution_when_skill_tampered_contract_hash_is_stale(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """A skill silently widens `allowed_transformations` on the ChangePlan
    AFTER approval was signed against the original contract_hash — the
    approval's `contract_hash` (still the ORIGINAL) no longer matches
    `expected_contract_hash` computed over the tampered contract, so
    execution is refused before any worktree is created."""
    tampered_contract = parse_change_plan(
        build_change_plan(
            patch_units=[
                {
                    "id": PATCH_UNIT_ID,
                    "files": ["apps/web/docs/readme.md"],
                    "allowed_transformations": list(SKILL_TAMPERED_TRANSFORMATIONS),
                    "tests": ["t"],
                    "rollback": f"git-revert:{PATCH_UNIT_ID}",
                }
            ]
        )
    )
    # The ApprovalDecision was signed for the ORIGINAL, pre-tamper contract
    # hash — a skill-driven post-approval command mutation can never make
    # this equal `expected_contract_hash` again without re-earning approval.
    approval = parse_approval_decision(build_approval_decision(contract_hash=CONTRACT_HASH))
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )

    tampered_expected_hash = "sha256:" + "5" * 64
    assert tampered_expected_hash != CONTRACT_HASH

    with pytest.raises(ApprovalContractHashMismatchError):
        runner.run(
            job_context=job_context,
            contract=tampered_contract,
            expected_contract_hash=tampered_expected_hash,
            approval=approval,
            requests=[PatchUnitRequest(patch_unit_id=PATCH_UNIT_ID)],
        )

    assert worktree_factory.created == [], "run blocked before any worktree is ever provisioned"
    assert command_executor.invocations == []
    assert any(
        e.error_code == "saena.agent_runner.approval_contract_hash_mismatch"
        for e in audit_chain.entries
    )
