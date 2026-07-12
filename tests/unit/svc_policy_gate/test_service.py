"""`saena_policy_gate.service` — fail-closed orchestration, H-3 plan-check,
idempotent decision recording (W2A exit "policy-gate fail-closed 데모: gate
다운 시 승인 불가")."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from saena_domain.identity import TenantId
from saena_domain.persistence.memory import InMemoryDecisionRecordStore
from saena_domain.policy.evidence import DiffStats
from saena_policy_gate.engine import AuthorizationRequest, PolicyEngine
from saena_policy_gate.errors import DecisionConflictError, GateUnavailableError
from saena_policy_gate.rules import default_engine_rules
from saena_policy_gate.service import PlanCheckInput, authorize_command, check_plan

TENANT = TenantId("acme-co")


class _BrokenEngine:
    """Test double: `.evaluate` always raises — proves fail-closed on an
    unavailable/broken policy engine (task instruction: "test: broken rule
    store -> deny")."""

    def evaluate(self, request: AuthorizationRequest) -> Any:
        raise RuntimeError("rule store connection lost")


def make_auth_request(**overrides: Any) -> AuthorizationRequest:
    base: dict[str, Any] = {
        "kind": "command",
        "action": "execute",
        "resource": ["pytest"],
        "tenant_id": TENANT.value,
    }
    base.update(overrides)
    return AuthorizationRequest(**base)


def make_plan_input(**overrides: Any) -> PlanCheckInput:
    base: dict[str, Any] = {
        "contract_hash": "sha256:" + "a" * 64,
        "proposer_actor_id": "proposer-1",
        "evidence_ledger_hash": "sha256:" + "b" * 64,
        "approved_scope": ["services/foundation/policy-gate-service/**"],
        "scope_max_globs": 5,
        "diff_max_files": 10,
        "diff_max_lines": 500,
        "hypothesis_risks": ("low",),
        "diff_stats": None,
    }
    base.update(overrides)
    return PlanCheckInput(**base)


# --- authorize_command --------------------------------------------------------


def test_authorize_command_allow_records_decision() -> None:
    store = InMemoryDecisionRecordStore()
    engine = PolicyEngine(rules=default_engine_rules())
    result = authorize_command(
        engine=engine,
        store=store,
        tenant_id=TENANT,
        request=make_auth_request(resource=["pytest", "-x"]),
        approver_actor_id="alice",
    )
    assert result.decision == "allow"
    assert result.error_code is None
    stored = store.get(TENANT, result.decision_key)
    assert stored.decision == "approved"


def test_authorize_command_default_deny_records_decision() -> None:
    store = InMemoryDecisionRecordStore()
    engine = PolicyEngine(rules=[])
    result = authorize_command(
        engine=engine,
        store=store,
        tenant_id=TENANT,
        request=make_auth_request(resource=["ls"]),
        approver_actor_id="alice",
    )
    assert result.decision == "deny"
    assert result.error_code is None
    stored = store.get(TENANT, result.decision_key)
    assert stored.decision == "rejected"


def test_authorize_command_fail_closed_on_broken_engine() -> None:
    store = InMemoryDecisionRecordStore()
    result = authorize_command(
        engine=_BrokenEngine(),  # type: ignore[arg-type]
        store=store,
        tenant_id=TENANT,
        request=make_auth_request(),
        approver_actor_id="alice",
    )
    assert result.decision == "deny"
    assert result.error_code == GateUnavailableError.error_code
    stored = store.get(TENANT, result.decision_key)
    assert stored.decision == "rejected"


def test_authorize_command_idempotent_replay_same_decision() -> None:
    store = InMemoryDecisionRecordStore()
    engine = PolicyEngine(rules=default_engine_rules())
    request = make_auth_request(resource=["pytest"])
    first = authorize_command(
        engine=engine, store=store, tenant_id=TENANT, request=request, approver_actor_id="alice"
    )
    second = authorize_command(
        engine=engine, store=store, tenant_id=TENANT, request=request, approver_actor_id="alice"
    )
    assert first.decision_key == second.decision_key
    assert first.decision == second.decision == "allow"
    # No duplicate insert — get() still resolves to a single stored record.
    assert store.get(TENANT, first.decision_key).decision == "approved"


# --- check_plan (H-3) ---------------------------------------------------------


def test_check_plan_missing_evidence_hash_denies() -> None:
    store = InMemoryDecisionRecordStore()
    plan = make_plan_input(evidence_ledger_hash="   ")
    result = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    assert result.decision == "deny"
    assert any("evidence_ledger_hash" in reason for reason in result.reasons)


def test_check_plan_scope_escape_denies() -> None:
    store = InMemoryDecisionRecordStore()
    plan = make_plan_input(approved_scope=["../../etc/passwd"])
    result = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    assert result.decision == "deny"
    assert any("escapes declared roots" in reason for reason in result.reasons)


def test_check_plan_diff_budget_exceeded_denies() -> None:
    store = InMemoryDecisionRecordStore()
    plan = make_plan_input(
        diff_max_files=1, diff_stats=DiffStats(files_changed=5, lines_changed=10)
    )
    result = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    assert result.decision == "deny"
    assert any("max_files" in reason for reason in result.reasons)


def test_check_plan_ok_allows() -> None:
    store = InMemoryDecisionRecordStore()
    plan = make_plan_input()
    result = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    assert result.decision == "allow"
    assert result.require_two_person is False


def test_check_plan_high_risk_requires_two_person() -> None:
    store = InMemoryDecisionRecordStore()
    plan = make_plan_input(hypothesis_risks=("low", "high"))
    result = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    assert result.require_two_person is True


def test_check_plan_low_risk_does_not_require_two_person() -> None:
    store = InMemoryDecisionRecordStore()
    plan = make_plan_input(hypothesis_risks=("low", "medium"))
    result = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    assert result.require_two_person is False


def test_check_plan_records_decision() -> None:
    store = InMemoryDecisionRecordStore()
    plan = make_plan_input()
    result = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    stored = store.get(TENANT, result.decision_key)
    assert stored.decision == "approved"
    assert stored.contract_hash == plan.contract_hash


def test_check_plan_idempotent_replay() -> None:
    store = InMemoryDecisionRecordStore()
    plan = make_plan_input()
    first = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    second = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    assert first.decision_key == second.decision_key
    assert first.decision == second.decision


def test_check_plan_conflicting_decision_raises() -> None:
    store = InMemoryDecisionRecordStore()
    good_plan = make_plan_input()
    # Same contract_hash + approver (decision_key), but this time the H-3
    # evaluation denies -> conflicting stored decision value.
    bad_plan = dataclasses.replace(good_plan, evidence_ledger_hash="")
    check_plan(store=store, tenant_id=TENANT, plan=good_plan, approver_actor_id="approver-1")
    with pytest.raises(DecisionConflictError):
        check_plan(store=store, tenant_id=TENANT, plan=bad_plan, approver_actor_id="approver-1")


def test_check_plan_fail_closed_on_evaluation_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """`evaluate_h3_evidence_policy` is documented as never raising, but
    `check_plan`'s fail-closed choke point must still hold if it (or a
    future revision of it) ever does — proven here by forcing an exception
    at the call site (task instruction: "fail-closed on engine failure")."""
    import saena_policy_gate.service as service_module

    def _broken_evaluate(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("H-3 evaluator crashed")

    monkeypatch.setattr(service_module, "evaluate_h3_evidence_policy", _broken_evaluate)

    store = InMemoryDecisionRecordStore()
    plan = make_plan_input()
    result = check_plan(store=store, tenant_id=TENANT, plan=plan, approver_actor_id="approver-1")
    assert result.decision == "deny"
    assert result.error_code == GateUnavailableError.error_code
    stored = store.get(TENANT, result.decision_key)
    assert stored.decision == "rejected"
