"""F-5 (k3s §10 "skill compromise") — DEDICATED skill-bundle content-integrity
verifier, distinct from the whole-ActionContract contract_hash pin.

This is the mechanism the earlier F-5 wiring lacked: a gate over the actual
skill bundle's *bytes*. A tampered skill file inside an otherwise-identical
(same contract_hash) ActionContract is caught here where the contract-hash
gate cannot see it. Enforced fail-closed at BOTH the hooks-runtime
session_start boundary and the agent-runner (before any worktree/executor).
"""

from __future__ import annotations

import pytest
from runner_factories import (
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    build_approval_decision,
    build_change_plan,
    build_job_context,
)
from saena_agent_runner.approval import parse_approval_decision
from saena_agent_runner.artifact import FakeArtifactRegistryGateway
from saena_agent_runner.clock import FakeClock
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.runner import FileWrite, PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.skill_bundle import InMemorySkillBundleSource
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory
from saena_domain.audit import InMemoryAuditChain
from saena_domain.execution import compute_skill_bundle_hash
from saena_domain.execution.skill_bundle import (
    SkillBundleHashMismatchError,
    verify_skill_bundle,
)

_BUNDLE = {
    "claude/skill.md": b"# skill\nrun approved-command\n",
    "third-party/ponytail-pinned/tool.py": b"print('pinned')\n",
}
_PIN = compute_skill_bundle_hash(dict(_BUNDLE))


def test_pure_verifier_blocks_tampered_bundle_same_contract_hash() -> None:
    tampered = dict(_BUNDLE)
    tampered["third-party/ponytail-pinned/tool.py"] = b"print('BACKDOOR')\n"
    with pytest.raises(SkillBundleHashMismatchError):
        verify_skill_bundle(expected_hash=_PIN, bundle=tampered)


def test_agent_runner_blocks_tampered_bundle_before_worktree() -> None:
    """PRIMARY: agent-runner refuses a skill-tampered bundle before any
    worktree/executor, even though the ActionContract (contract_hash) is the
    fixed, unchanged CONTRACT_HASH."""
    tampered = dict(_BUNDLE)
    tampered["claude/skill.md"] = b"# skill\nrun EVIL-command\n"
    worktree_factory = FakeWorktreeFactory()
    command_executor = FakeCommandExecutor()
    audit_chain = InMemoryAuditChain()
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=FakeArtifactRegistryGateway(),
        audit_chain=audit_chain,
        clock=FakeClock(),
        skill_bundle_source=InMemorySkillBundleSource(bundle=tampered),
    )
    with pytest.raises(SkillBundleHashMismatchError):
        runner.run(
            job_context=build_job_context(),
            contract=parse_change_plan(build_change_plan()),
            expected_contract_hash=CONTRACT_HASH,
            approval=parse_approval_decision(build_approval_decision()),
            requests=[
                PatchUnitRequest(
                    patch_unit_id=PATCH_UNIT_ID,
                    file_writes=(FileWrite(relative_path="apps/web/docs/readme.md", content=b"x"),),
                )
            ],
            expected_skill_bundle_hash=_PIN,
        )
    assert worktree_factory.created == []
    assert command_executor.invocations == []
    assert any("skill_bundle" in e.action for e in audit_chain.entries)


def test_agent_runner_recovers_to_a_clean_pinned_bundle() -> None:
    """RECOVERY: with the correct, untampered bundle restored, the same run
    executes normally — the gate is not a permanent block, it tracks the pin."""
    worktree_factory = FakeWorktreeFactory()
    command_executor = FakeCommandExecutor()
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=FakeArtifactRegistryGateway(),
        audit_chain=InMemoryAuditChain(),
        clock=FakeClock(),
        skill_bundle_source=InMemorySkillBundleSource(bundle=dict(_BUNDLE)),
    )
    result = runner.run(
        job_context=build_job_context(),
        contract=parse_change_plan(build_change_plan()),
        expected_contract_hash=CONTRACT_HASH,
        approval=parse_approval_decision(build_approval_decision()),
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite(relative_path="apps/web/docs/readme.md", content=b"x"),),
            )
        ],
        expected_skill_bundle_hash=_PIN,
    )
    assert result.outcomes[0].status.value in {"succeeded", "running"}
