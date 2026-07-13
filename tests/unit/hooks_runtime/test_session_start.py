from __future__ import annotations

from hooks_runtime_factories import (
    RUN_ID,
    TENANT_ID,
    TRACE_ID,
    TS,
    VALID_SKILL_BUNDLE_HASH,
    make_allowing_skill_bundle_port,
    make_budget,
    make_contract,
)
from saena_hooks_runtime.hooks.session_start import SecretFinding, SessionStartInput, session_start
from saena_hooks_runtime.models import Decision, ReasonCode


def _base_input(**overrides: object) -> SessionStartInput:
    # A normal, valid execution session — carries a valid F-5 pin + allowing
    # port so the (mandatory) bundle gate passes; these tests focus on the
    # contract/policy/secret checks, not the bundle gate itself.
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
        expected_skill_bundle_hash=VALID_SKILL_BUNDLE_HASH,
        skill_bundle_port=make_allowing_skill_bundle_port(),
    )
    defaults.update(overrides)
    return SessionStartInput(**defaults)  # type: ignore[arg-type]


def test_allow_when_everything_clean() -> None:
    result = session_start(_base_input())
    assert result.decision == Decision.ALLOW
    assert result.reason_code == ReasonCode.OK


def test_deny_missing_contract() -> None:
    result = session_start(_base_input(contract=None))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.CONTRACT_MISSING


def test_deny_dirty_worktree() -> None:
    result = session_start(_base_input(worktree_dirty=True))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.DIRTY_WORKTREE


def test_deny_invalid_policy_signature() -> None:
    result = session_start(_base_input(policy_signature_valid=False))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.POLICY_SIGNATURE_INVALID


def test_deny_detected_secret() -> None:
    finding = SecretFinding(
        location="src/app/config.ts:12", rule_id="aws-akid", raw_value="AKIAABCDEFGHIJKLMNOP"
    )
    result = session_start(_base_input(secret_findings=(finding,)))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.SECRET_DETECTED
    assert "AKIAABCDEFGHIJKLMNOP" not in result.detail


def test_contract_check_takes_precedence_over_dirty_worktree() -> None:
    result = session_start(_base_input(contract=None, worktree_dirty=True))
    assert result.reason_code == ReasonCode.CONTRACT_MISSING


def test_timeout_overrun_denies_before_any_other_check() -> None:
    result = session_start(
        _base_input(contract=None, budget=make_budget("session_start", expired=True))
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED


def test_audit_record_fields_populated() -> None:
    result = session_start(_base_input())
    audit = result.audit
    assert audit.hook == "session_start"
    assert audit.tenant_id == TENANT_ID
    assert audit.run_id == RUN_ID
    assert audit.trace_id == TRACE_ID
    assert audit.ts == TS
    assert audit.decision == Decision.ALLOW
