"""Rollback verification gate (testing-strategy.md sec F-7): approval-ledger
immutability, audit-chain preservation, artifact immutability.

After a rollback, the mission requires: "approval ledger unchanged, audit
verifiable". This suite has no separate `approval-ledger-service`
implementation to call (agent-runner's own `saena_agent_runner.approval`
module is a stateless VERIFIER, not a ledger store) — the actual immutable,
append-only, hash-chained record of every approval/patch-unit DECISION this
codebase persists is `saena_domain.audit.InMemoryAuditChain` /
`AuditEntry` (`saena_agent_runner.audit.record_approval_refused` /
`record_patch_unit_decision` write directly into it — see those modules'
own docstrings). This is the REAL mechanism wired here.
"""

from __future__ import annotations

import pydantic
import pytest
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
from saena_domain.audit.chain import verify_chain
from saena_domain.execution import JobContext, JobStatus


def _run_one_denied_unit(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
):
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )
    return runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[PatchUnitRequest(patch_unit_id="PU-NOT-APPROVED")],
    )


def test_audit_entry_is_structurally_immutable_once_appended(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    _run_one_denied_unit(
        job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
    )
    entry = audit_chain.entries[0]

    with pytest.raises(pydantic.ValidationError, match="frozen"):
        entry.action = "tampered.action.v1"  # type: ignore[misc]
    with pytest.raises(pydantic.ValidationError, match="frozen"):
        entry.payload = {"decision": "silently-approved"}  # type: ignore[misc]


def test_audit_chain_stays_verifiable_across_a_full_run_including_a_rollback(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """audit verifiable: the hash chain remains intact and self-verifying
    after recording a refusal/rollback decision — the exact "audit
    verifiable" post-rollback condition the mission names."""
    result = _run_one_denied_unit(
        job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
    )
    assert result.outcomes[0].status == JobStatus.FAILED

    ok, bad_index = audit_chain.verify()
    assert ok is True
    assert bad_index is None
    assert len(audit_chain.entries) == 1
    assert audit_chain.entries[0].payload["decision"] == "refused_not_approved"


def test_retroactive_tamper_of_an_already_appended_refusal_entry_is_detected(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """Simulates an attacker who, unable to mutate the frozen `AuditEntry`
    in place, instead swaps a FORGED replacement entry (same event_hash
    claimed, different payload — e.g. rewriting a denied patch unit's
    audit record to read "executed") into a copy of the chain. `verify_chain`
    (the same function `InMemoryAuditChain.verify()` calls) detects it —
    tamper anywhere is caught, per `chain.py`'s own documented guarantee."""
    _run_one_denied_unit(
        job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
    )
    genuine_entry = audit_chain.entries[0]
    forged_entry = genuine_entry.model_copy(
        update={"payload": {"patch_unit_id": "PU-NOT-APPROVED", "decision": "executed"}}
    )
    assert forged_entry.event_hash == genuine_entry.event_hash  # attacker kept the old hash

    ok, bad_index = verify_chain([forged_entry])
    assert ok is False
    assert bad_index == 0


def test_forged_approval_decision_never_reaches_the_ledger_as_executed(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    """ "approval ledger unchanged" after a blocked run: a forged/mismatched
    ApprovalDecision.contract_hash records exactly ONE refusal entry — no
    approval, no execution, no worktree — the ledger is not polluted with
    any half-executed state either."""
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision(contract_hash="sha256:" + "9" * 64))
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )

    with pytest.raises(ApprovalContractHashMismatchError):
        runner.run(
            job_context=job_context,
            contract=contract,
            expected_contract_hash=CONTRACT_HASH,
            approval=approval,
            requests=[PatchUnitRequest(patch_unit_id=PATCH_UNIT_ID)],
        )

    assert len(audit_chain.entries) == 1
    assert audit_chain.entries[0].action == "agent_runner.approval.refused.v1"
    assert audit_chain.entries[0].payload["decision"] == "refused"
    ok, _ = audit_chain.verify()
    assert ok is True


def test_artifact_is_content_addressed_tamper_evident_not_silently_mutable() -> None:
    """ "artifact immutability": a `PatchArtifact` is never itself a
    server-side mutable record this package updates in place — it is
    content-addressed (`artifact_hash` derived from tenant/patch_unit/
    worktree_commit/changed_files). Any post-hoc change to what the
    artifact claims to cover changes the hash — tamper-evident by
    construction, proven directly against the real
    `FakeArtifactRegistryGateway.register` the runner itself calls."""
    gateway = FakeArtifactRegistryGateway()

    genuine = gateway.register(
        tenant_id="acme-co",
        run_id="run-0001",
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit="c" * 40,
        base_commit="a" * 40,
        changed_files=["apps/web/docs/readme.md"],
    )
    tampered_claim = gateway.register(
        tenant_id="acme-co",
        run_id="run-0001",
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit="c" * 40,
        base_commit="a" * 40,
        # attacker claims a DIFFERENT changed-files set under the same
        # worktree_commit — the resulting hash must NOT collide.
        changed_files=["apps/web/docs/readme.md", "packages/contracts/evil.json"],
    )
    assert genuine.artifact_hash != tampered_claim.artifact_hash

    # determinism: registering the SAME facts twice is stable/idempotent —
    # a caller re-verifying an already-registered artifact recomputes the
    # identical hash, never a fresh/different one.
    replay = gateway.register(
        tenant_id="acme-co",
        run_id="run-0001",
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit="c" * 40,
        base_commit="a" * 40,
        changed_files=["apps/web/docs/readme.md"],
    )
    assert replay.artifact_hash == genuine.artifact_hash
