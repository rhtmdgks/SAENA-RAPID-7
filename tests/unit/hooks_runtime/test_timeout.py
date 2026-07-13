"""Consolidated timeout-overrun coverage (task instructions: "Timeout
semantics: engine receives elapsed/deadline and treats overrun as DENY
(fail-closed) — test it"). Per-hook detail also lives in each hook's own
test module; this file is the single place asserting the rule holds
UNIFORMLY across all 5 hooks with the SAME budget-overrun construction."""

from __future__ import annotations

from hooks_runtime_factories import (
    RUN_ID,
    TENANT_ID,
    TRACE_ID,
    TS,
    make_budget,
    make_contract,
)
from saena_hooks_runtime.fakes import InMemoryAuditSink
from saena_hooks_runtime.hooks.before_handoff import (
    BeforeHandoffInput,
    CriticReview,
    QualityMatrixResult,
    RollbackManifest,
    before_handoff,
)
from saena_hooks_runtime.hooks.post_tool_use import PostToolUseInput, post_tool_use
from saena_hooks_runtime.hooks.pre_tool_use import PreToolUseInput, pre_tool_use
from saena_hooks_runtime.hooks.session_start import SessionStartInput, session_start
from saena_hooks_runtime.hooks.subagent_start import SubagentStartInput, ToolLease, subagent_start
from saena_hooks_runtime.models import Decision, ReasonCode, TimeoutBudget


def test_session_start_overrun_is_deny() -> None:
    result = session_start(
        SessionStartInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=make_contract(),
            worktree_dirty=False,
            policy_signature_valid=True,
            secret_findings=(),
            budget=make_budget("session_start", expired=True),
        )
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED


def test_pre_tool_use_overrun_is_deny() -> None:
    result = pre_tool_use(
        PreToolUseInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=make_contract(),
            tool_name="Bash",
            budget=make_budget("pre_tool_use", expired=True),
            command="git status",
        )
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED


def test_post_tool_use_overrun_is_deny_and_does_not_touch_audit_sink() -> None:
    sink = InMemoryAuditSink()
    result = post_tool_use(
        PostToolUseInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=make_contract(),
            changed_files=(),
            budget=make_budget("post_tool_use", expired=True),
        ),
        sink,
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED
    assert sink.records == []


def test_subagent_start_overrun_is_deny() -> None:
    result = subagent_start(
        SubagentStartInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            role="writer",
            lease=ToolLease(write=True, network=False),
            untrusted_content_present=False,
            budget=make_budget("subagent_start", expired=True),
        )
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED


def test_before_handoff_overrun_is_fail_not_deny() -> None:
    """`before_handoff` uses the PASS/CONDITIONAL_PASS/FAIL vocabulary, not
    ALLOW/DENY — its fail-closed overrun outcome is `Decision.FAIL`."""
    result = before_handoff(
        BeforeHandoffInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            quality_matrix=QualityMatrixResult(gates={}),
            critic_review=CriticReview(reviewer_id="c", independent=True, verdict="approve"),
            rollback_manifest=RollbackManifest(
                patch_unit_id="pu-1", command="revert", verified=True
            ),
            patch_commands=(),
            budget=make_budget("before_handoff", expired=True),
        )
    )
    assert result.decision == Decision.FAIL
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED


def test_overrun_is_exactly_at_deadline_not_only_past_it() -> None:
    # elapsed == deadline must ALSO count as overrun (budget.expired uses
    # >=), not just elapsed > deadline.
    budget = TimeoutBudget(elapsed_seconds=5.0, deadline_seconds=5.0)
    assert budget.expired is True
