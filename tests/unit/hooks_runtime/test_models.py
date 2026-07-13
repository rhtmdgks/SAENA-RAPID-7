from __future__ import annotations

from hooks_runtime_factories import RUN_ID, TENANT_ID, TRACE_ID, TS
from saena_hooks_runtime.models import (
    HOOK_TIMEOUT_SECONDS,
    AuditRecord,
    Decision,
    HookDecision,
    ReasonCode,
    TimeoutBudget,
    budget_for,
)


def test_timeout_budget_not_expired_below_deadline() -> None:
    budget = TimeoutBudget(elapsed_seconds=1.0, deadline_seconds=5.0)
    assert budget.expired is False


def test_timeout_budget_expired_at_exact_deadline() -> None:
    # overrun is >= deadline, not strictly >, per module docstring.
    budget = TimeoutBudget(elapsed_seconds=5.0, deadline_seconds=5.0)
    assert budget.expired is True


def test_timeout_budget_expired_past_deadline() -> None:
    budget = TimeoutBudget(elapsed_seconds=6.0, deadline_seconds=5.0)
    assert budget.expired is True


def test_budget_for_every_hook_name() -> None:
    for hook in (
        "session_start",
        "pre_tool_use",
        "post_tool_use",
        "subagent_start",
        "before_handoff",
    ):
        budget = budget_for(hook, elapsed_seconds=0.0)
        assert budget.deadline_seconds == HOOK_TIMEOUT_SECONDS[hook]
        assert budget.expired is False


def test_budget_for_unknown_hook_raises() -> None:
    import pytest

    with pytest.raises(KeyError):
        budget_for("not_a_real_hook", elapsed_seconds=0.0)


def test_hook_timeout_seconds_match_spec() -> None:
    assert HOOK_TIMEOUT_SECONDS == {
        "session_start": 30.0,
        "pre_tool_use": 5.0,
        "post_tool_use": 10.0,
        "subagent_start": 5.0,
        "before_handoff": 60.0,
    }


def test_hook_decision_blocked_for_deny_fail_unstable() -> None:
    audit = AuditRecord(
        ts=TS,
        hook="x",
        decision=Decision.DENY,
        reason_code=ReasonCode.OK,
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        trace_id=TRACE_ID,
    )
    for decision in (Decision.DENY, Decision.FAIL, Decision.UNSTABLE):
        hd = HookDecision(decision=decision, reason_code=ReasonCode.OK, detail="", audit=audit)
        assert hd.blocked is True


def test_hook_decision_not_blocked_for_allow_pass_conditional_pass() -> None:
    audit = AuditRecord(
        ts=TS,
        hook="x",
        decision=Decision.ALLOW,
        reason_code=ReasonCode.OK,
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        trace_id=TRACE_ID,
    )
    for decision in (Decision.ALLOW, Decision.PASS, Decision.CONDITIONAL_PASS):
        hd = HookDecision(decision=decision, reason_code=ReasonCode.OK, detail="", audit=audit)
        assert hd.blocked is False
