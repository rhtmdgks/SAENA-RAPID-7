"""F-5 skill-bundle integrity enforcement at the agent-runner boundary.

Proves the runner refuses a tampered / missing / unpinned-but-absent bundle
BEFORE any worktree is created or executor invoked, records an audit entry,
and that an ActionContract with an unchanged contract_hash is still refused
when only a bundle file changed.
"""

from __future__ import annotations

import pytest
from runner_factories import (
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    build_approval_decision,
    build_change_plan,
)
from saena_agent_runner.approval import parse_approval_decision
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.runner import FileWrite, PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.skill_bundle import (
    InMemorySkillBundleSource,
    RecordingSkillBundleSource,
)
from saena_domain.execution import compute_skill_bundle_hash
from saena_domain.execution.skill_bundle import (
    SkillBundleHashMismatchError,
    SkillBundleMissingError,
)

_BUNDLE = {
    "claude/skill.md": b"# skill\nrun approved\n",
    "portable/allowlist.txt": b"approved\n",
}
_PIN = compute_skill_bundle_hash(dict(_BUNDLE))


def _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock, source=None):
    return PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
        skill_bundle_source=source,
    )


def _valid_request() -> PatchUnitRequest:
    return PatchUnitRequest(
        patch_unit_id=PATCH_UNIT_ID,
        file_writes=(FileWrite(relative_path="apps/web/docs/readme.md", content=b"x"),),
    )


def _run(runner, job_context, *, bundle_pin):
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())
    return runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[_valid_request()],
        expected_skill_bundle_hash=bundle_pin,
    )


def test_valid_pinned_bundle_allows_execution(
    job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
) -> None:
    source = InMemorySkillBundleSource(bundle=dict(_BUNDLE))
    runner = _runner(
        worktree_factory, command_executor, artifact_gateway, audit_chain, clock, source
    )
    result = _run(runner, job_context, bundle_pin=_PIN)
    assert result.outcomes[0].status.value in {"succeeded", "running"}


def test_tampered_bundle_denies_before_worktree_and_executor(
    job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
) -> None:
    tampered = dict(_BUNDLE)
    tampered["claude/skill.md"] = b"# skill\nrun EVIL\n"
    source = RecordingSkillBundleSource(inner=InMemorySkillBundleSource(bundle=tampered))
    runner = _runner(
        worktree_factory, command_executor, artifact_gateway, audit_chain, clock, source
    )
    with pytest.raises(SkillBundleHashMismatchError):
        _run(runner, job_context, bundle_pin=_PIN)
    assert source.loaded is True  # verification WAS attempted
    assert worktree_factory.created == []  # no worktree created
    assert command_executor.invocations == []  # no command run
    assert artifact_gateway.registrations == []  # no artifact registered


def test_missing_source_with_pin_denies(
    job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
) -> None:
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock, None)
    with pytest.raises(SkillBundleMissingError):
        _run(runner, job_context, bundle_pin=_PIN)
    assert command_executor.invocations == []


def test_missing_bundle_from_source_with_pin_denies(
    job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
) -> None:
    source = InMemorySkillBundleSource(bundle=None)
    runner = _runner(
        worktree_factory, command_executor, artifact_gateway, audit_chain, clock, source
    )
    with pytest.raises(SkillBundleMissingError):
        _run(runner, job_context, bundle_pin=_PIN)
    assert command_executor.invocations == []


def test_same_contract_hash_but_changed_bundle_still_denies(
    job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
) -> None:
    # contract_hash is the fixed CONTRACT_HASH (unchanged); only a bundle file
    # differs from the pin — the dedicated verifier must still block.
    swapped = dict(_BUNDLE)
    swapped["portable/allowlist.txt"] = b"approved\nsneaky-extra\n"
    source = InMemorySkillBundleSource(bundle=swapped)
    runner = _runner(
        worktree_factory, command_executor, artifact_gateway, audit_chain, clock, source
    )
    with pytest.raises(SkillBundleHashMismatchError):
        _run(runner, job_context, bundle_pin=_PIN)
    assert command_executor.invocations == []


def test_denial_records_audit_entry(
    job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
) -> None:
    tampered = dict(_BUNDLE)
    tampered["claude/skill.md"] = b"changed\n"
    source = InMemorySkillBundleSource(bundle=tampered)
    runner = _runner(
        worktree_factory, command_executor, artifact_gateway, audit_chain, clock, source
    )
    with pytest.raises(SkillBundleHashMismatchError):
        _run(runner, job_context, bundle_pin=_PIN)
    entries = audit_chain.entries
    assert any("skill_bundle" in getattr(e, "action", "") for e in entries)


def test_no_pin_means_bundle_gate_is_skipped(
    job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
) -> None:
    # A run that carries NO skill_bundle_hash pin is not gated by F-5 here
    # (nothing to verify against); execution proceeds on approval alone.
    runner = _runner(worktree_factory, command_executor, artifact_gateway, audit_chain, clock, None)
    result = _run(runner, job_context, bundle_pin=None)
    assert result.outcomes[0].status.value in {"succeeded", "running"}


def test_bundle_content_never_echoed_in_denial(
    job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
) -> None:
    secret_bundle = dict(_BUNDLE)
    secret_bundle["claude/skill.md"] = b"API_KEY=AKIALEAKME_NOT_IN_ERROR"
    source = InMemorySkillBundleSource(bundle=secret_bundle)
    runner = _runner(
        worktree_factory, command_executor, artifact_gateway, audit_chain, clock, source
    )
    with pytest.raises(SkillBundleHashMismatchError) as ei:
        _run(runner, job_context, bundle_pin=_PIN)
    assert "AKIALEAKME" not in str(ei.value)
    entries = audit_chain.entries
    for e in entries:
        assert "AKIALEAKME" not in str(getattr(e, "payload", ""))
