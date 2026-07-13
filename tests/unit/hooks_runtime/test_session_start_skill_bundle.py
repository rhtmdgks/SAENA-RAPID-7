"""session_start F-5 skill-bundle integrity gate (injected Port)."""

from __future__ import annotations

from hooks_runtime_factories import (
    RUN_ID,
    TENANT_ID,
    TRACE_ID,
    TS,
    make_budget,
    make_contract,
)
from saena_hooks_runtime.hooks.session_start import (
    AllowingSkillBundlePort,
    SessionStartInput,
    SkillBundleIntegrityResult,
    StubSkillBundlePort,
    session_start,
)
from saena_hooks_runtime.models import Decision, ReasonCode

_PIN = "sha256:" + "a" * 64


def _input(**overrides: object) -> SessionStartInput:
    defaults: dict[str, object] = dict(
        ts=TS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        trace_id=TRACE_ID,
        contract=make_contract(),
        worktree_dirty=False,
        policy_signature_valid=True,
        secret_findings=(),
        budget=make_budget("session_start"),
    )
    defaults.update(overrides)
    return SessionStartInput(**defaults)  # type: ignore[arg-type]


def test_no_pin_allows_without_a_port() -> None:
    d = session_start(_input(expected_skill_bundle_hash=None, skill_bundle_port=None))
    assert d.decision == Decision.ALLOW


def test_pin_with_ok_port_allows_and_consults_port() -> None:
    port = StubSkillBundlePort(result=SkillBundleIntegrityResult(ok=True))
    d = session_start(_input(expected_skill_bundle_hash=_PIN, skill_bundle_port=port))
    assert d.decision == Decision.ALLOW
    assert port.consulted is True


def test_pin_with_failing_port_denies() -> None:
    port = StubSkillBundlePort(
        result=SkillBundleIntegrityResult(ok=False, redacted_detail="hash mismatch")
    )
    d = session_start(_input(expected_skill_bundle_hash=_PIN, skill_bundle_port=port))
    assert d.decision == Decision.DENY
    assert d.reason_code == ReasonCode.SKILL_BUNDLE_INTEGRITY


def test_pin_with_no_port_is_fail_closed_deny() -> None:
    d = session_start(_input(expected_skill_bundle_hash=_PIN, skill_bundle_port=None))
    assert d.decision == Decision.DENY
    assert d.reason_code == ReasonCode.SKILL_BUNDLE_INTEGRITY


def test_raising_port_is_fail_closed_and_does_not_leak_message() -> None:
    class _Boom:
        def verify(self, *, expected_skill_bundle_hash):  # noqa: ANN001, ANN202
            raise RuntimeError("SECRET_BUNDLE_BYTES_AKIALEAK")

    d = session_start(_input(expected_skill_bundle_hash=_PIN, skill_bundle_port=_Boom()))
    assert d.decision == Decision.DENY
    assert d.reason_code == ReasonCode.SKILL_BUNDLE_INTEGRITY
    assert "AKIALEAK" not in d.detail


def test_allowing_port_reference_fake_allows() -> None:
    d = session_start(
        _input(expected_skill_bundle_hash=_PIN, skill_bundle_port=AllowingSkillBundlePort())
    )
    assert d.decision == Decision.ALLOW


def test_contract_problem_still_wins_over_bundle_gate() -> None:
    # An invalid contract is reported before the bundle gate (ordering: run
    # context first), even with a failing bundle port.
    port = StubSkillBundlePort(result=SkillBundleIntegrityResult(ok=False))
    d = session_start(
        _input(contract=None, expected_skill_bundle_hash=_PIN, skill_bundle_port=port)
    )
    assert d.decision == Decision.DENY
    assert d.reason_code != ReasonCode.SKILL_BUNDLE_INTEGRITY  # contract issue reported first
