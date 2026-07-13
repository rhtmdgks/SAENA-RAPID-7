"""End-to-end wiring proof: the pure `saena_domain.execution.skill_bundle`
verifier, wrapped as the hooks-runtime `SkillBundleIntegrityPort`, genuinely
denies session start on a tampered bundle — i.e. the two boundaries are
CONNECTED, not merely declared.

hooks-runtime (a stdlib-only leaf) never imports saena_domain; the concrete
adapter below IS the runtime-host wiring seam, and it can only live outside
both linted packages — here, in the test that demonstrates it. This test runs
in the blocking unit lane (pure Python, no container)."""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.execution import compute_skill_bundle_hash
from saena_domain.execution.skill_bundle import SkillBundle, verify_skill_bundle
from saena_hooks_runtime.contract import ActionContract, PatchUnit, compute_contract_hash
from saena_hooks_runtime.hooks.session_start import (
    SessionStartInput,
    SkillBundleIntegrityResult,
    session_start,
)
from saena_hooks_runtime.models import Decision, ReasonCode, TimeoutBudget


@dataclass(slots=True)
class DomainBackedSkillBundlePort:
    """The real wiring: adapts `saena_domain.execution.skill_bundle.verify_
    skill_bundle` to the hooks-runtime Port. Redaction is inherent — the
    domain verifier only ever surfaces digests, and this adapter returns a
    fixed, content-free detail."""

    bundle: SkillBundle | None

    def verify(self, *, expected_skill_bundle_hash: str | None) -> SkillBundleIntegrityResult:
        try:
            verify_skill_bundle(expected_hash=expected_skill_bundle_hash, bundle=self.bundle)
        except Exception:
            return SkillBundleIntegrityResult(
                ok=False, redacted_detail="skill bundle hash mismatch"
            )
        return SkillBundleIntegrityResult(ok=True)


_BUNDLE = {"claude/skill.md": b"run approved\n", "portable/x.txt": b"ok\n"}
_PIN = compute_skill_bundle_hash(dict(_BUNDLE))


def _contract() -> ActionContract:
    pu = PatchUnit(
        unit_id="u1",
        files=("src/a.py",),
        allowed_transformations=("edit",),
        tests=("t",),
        rollback_method="git revert",
    )
    base = ActionContract(
        run_id="r",
        customer_id="tn",
        repo_commit="a" * 40,
        approved_scope=("src/**",),
        engine_scope=("chatgpt-search",),
        patch_units=(pu,),
        approval_required=True,
        contract_hash="",
    )
    import dataclasses

    return dataclasses.replace(base, contract_hash=compute_contract_hash(base))


def _input(bundle: SkillBundle | None, pin: str | None) -> SessionStartInput:
    return SessionStartInput(
        ts="2026-07-13T00:00:00Z",
        run_id="r",
        tenant_id="tn",
        trace_id="tr",
        contract=_contract(),
        worktree_dirty=False,
        policy_signature_valid=True,
        secret_findings=(),
        budget=TimeoutBudget(elapsed_seconds=0.0, deadline_seconds=30.0),
        expected_skill_bundle_hash=pin,
        skill_bundle_port=DomainBackedSkillBundlePort(bundle=bundle),
    )


def test_real_verifier_allows_a_matching_bundle_through_session_start() -> None:
    d = session_start(_input(dict(_BUNDLE), _PIN))
    assert d.decision == Decision.ALLOW


def test_real_verifier_denies_a_tampered_bundle_through_session_start() -> None:
    tampered = dict(_BUNDLE)
    tampered["claude/skill.md"] = b"run EVIL\n"
    d = session_start(_input(tampered, _PIN))
    assert d.decision == Decision.DENY
    assert d.reason_code == ReasonCode.SKILL_BUNDLE_INTEGRITY


def test_real_verifier_denies_added_and_removed_files() -> None:
    added = dict(_BUNDLE)
    added["claude/extra.md"] = b"new\n"
    assert session_start(_input(added, _PIN)).decision == Decision.DENY
    removed = {"claude/skill.md": _BUNDLE["claude/skill.md"]}
    assert session_start(_input(removed, _PIN)).decision == Decision.DENY


def test_contract_hash_identical_but_bundle_tampered_still_denies() -> None:
    # Same ActionContract (identical contract_hash) — only the bundle changed.
    tampered = dict(_BUNDLE)
    tampered["portable/x.txt"] = b"ok\nBACKDOOR\n"
    d = session_start(_input(tampered, _PIN))
    assert d.decision == Decision.DENY
    assert d.reason_code == ReasonCode.SKILL_BUNDLE_INTEGRITY
