"""Planted-violation fixtures (task instructions: "Planted violation
fixtures: for each of the 5 hooks, at least one fixture that MUST fail and
a test asserting it does"). One dedicated, clearly-labeled test per hook
here — additional coverage of the same conditions also lives in each
hook's own `test_<hook>.py` module; this file is the single place a
reviewer can look to confirm every hook has at least one MUST-fail planted
fixture.
"""

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
from saena_hooks_runtime.fakes import FailingAuditSink
from saena_hooks_runtime.hooks.before_handoff import (
    BeforeHandoffInput,
    QualityMatrixResult,
    before_handoff,
)
from saena_hooks_runtime.hooks.post_tool_use import ChangedFile, PostToolUseInput, post_tool_use
from saena_hooks_runtime.hooks.pre_tool_use import PreToolUseInput, pre_tool_use
from saena_hooks_runtime.hooks.session_start import SessionStartInput, session_start
from saena_hooks_runtime.hooks.subagent_start import SubagentStartInput, ToolLease, subagent_start
from saena_hooks_runtime.models import Decision, ReasonCode


def test_planted_violation_session_start_missing_contract_must_deny() -> None:
    """Planted: no Action Contract at session start."""
    result = session_start(
        SessionStartInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=None,
            worktree_dirty=False,
            policy_signature_valid=True,
            secret_findings=(),
            budget=make_budget("session_start"),
            expected_skill_bundle_hash=VALID_SKILL_BUNDLE_HASH,
            skill_bundle_port=make_allowing_skill_bundle_port(),
        )
    )
    assert result.decision == Decision.DENY
    assert result.blocked is True
    assert result.reason_code == ReasonCode.CONTRACT_MISSING


def test_planted_violation_pre_tool_use_deployment_cmd_must_deny() -> None:
    """Planted: a Bash tool call attempting `helm upgrade` — a deployment
    command (§11 pre_tool_use "Blocks: deployment cmd")."""
    result = pre_tool_use(
        PreToolUseInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=make_contract(),
            tool_name="Bash",
            budget=make_budget("pre_tool_use"),
            command="helm upgrade myapp ./chart --install",
        )
    )
    assert result.decision == Decision.DENY
    assert result.blocked is True
    assert result.reason_code == ReasonCode.DEPLOY_PUSH_CMS_DNS


def test_planted_violation_post_tool_use_audit_append_failure_must_be_unstable() -> None:
    """Planted: the audit sink raises on append (§11 post_tool_use "Blocks:
    audit append failure")."""
    result = post_tool_use(
        PostToolUseInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=make_contract(),
            changed_files=(ChangedFile(path="src/app/page.tsx"),),
            budget=make_budget("post_tool_use"),
        ),
        FailingAuditSink(),
    )
    assert result.decision == Decision.UNSTABLE
    assert result.blocked is True
    assert result.reason_code == ReasonCode.AUDIT_APPEND_FAILURE


def test_planted_violation_subagent_start_critic_with_write_lease_must_deny() -> None:
    """Planted (task instructions' own named example): "critic role
    receiving write credentials"."""
    result = subagent_start(
        SubagentStartInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            role="critic",
            lease=ToolLease(write=True, network=False),
            untrusted_content_present=False,
            budget=make_budget("subagent_start"),
        )
    )
    assert result.decision == Decision.DENY
    assert result.blocked is True
    assert result.reason_code == ReasonCode.READ_ONLY_ROLE_WRITE_LEASE


def test_planted_violation_before_handoff_missing_rollback_manifest_must_fail() -> None:
    """Planted: no rollback manifest recorded (§11 before_handoff "Blocks:
    ... missing rollback manifest")."""
    from saena_hooks_runtime.hooks.before_handoff import CriticReview

    result = before_handoff(
        BeforeHandoffInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            quality_matrix=QualityMatrixResult(
                gates={"build": "PASS", "tests": "PASS", "lint": "PASS", "security": "PASS"}
            ),
            critic_review=CriticReview(reviewer_id="critic-1", independent=True, verdict="approve"),
            rollback_manifest=None,
            patch_commands=(),
            budget=make_budget("before_handoff"),
        )
    )
    assert result.decision == Decision.FAIL
    assert result.blocked is True
    assert result.reason_code == ReasonCode.MISSING_ROLLBACK_MANIFEST
