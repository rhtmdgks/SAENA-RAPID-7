from __future__ import annotations

from hooks_runtime_factories import (
    RUN_ID,
    TENANT_ID,
    TRACE_ID,
    TS,
    make_budget,
    make_contract,
    make_patch_unit,
)
from saena_hooks_runtime.fakes import FailingAuditSink, InMemoryAuditSink
from saena_hooks_runtime.hooks.post_tool_use import ChangedFile, PostToolUseInput, post_tool_use
from saena_hooks_runtime.models import Decision, ReasonCode


def _input(changed_files: tuple[ChangedFile, ...], **overrides: object) -> PostToolUseInput:
    defaults: dict[str, object] = dict(
        ts=TS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        trace_id=TRACE_ID,
        contract=make_contract(),
        changed_files=changed_files,
        budget=make_budget("post_tool_use"),
    )
    defaults.update(overrides)
    return PostToolUseInput(**defaults)  # type: ignore[arg-type]


def test_changed_file_matching_patch_unit_allowed_and_audited() -> None:
    sink = InMemoryAuditSink()
    result = post_tool_use(_input((ChangedFile(path="src/app/page.tsx"),)), sink)
    assert result.decision == Decision.ALLOW
    assert len(sink.records) == 1
    assert sink.records[0].decision == Decision.ALLOW


def test_unexplained_file_change_denied() -> None:
    sink = InMemoryAuditSink()
    result = post_tool_use(_input((ChangedFile(path="deploy/helm/values.yaml"),)), sink)
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.UNEXPLAINED_FILE_CHANGE
    # An unexplained-change DENY does not itself append (see hook docstring).
    assert len(sink.records) == 0


def test_changed_file_with_no_contract_denied() -> None:
    sink = InMemoryAuditSink()
    result = post_tool_use(_input((ChangedFile(path="src/app/page.tsx"),), contract=None), sink)
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.UNEXPLAINED_FILE_CHANGE


def test_audit_append_failure_marks_unstable() -> None:
    sink = FailingAuditSink()
    result = post_tool_use(_input((ChangedFile(path="src/app/page.tsx"),)), sink)
    assert result.decision == Decision.UNSTABLE
    assert result.reason_code == ReasonCode.AUDIT_APPEND_FAILURE


def test_mark_required_tests_dirty_collects_matched_units_tests() -> None:
    contract = make_contract(
        patch_units=(
            make_patch_unit(unit_id="pu-a", files=("src/a/**",), tests=("t_a",)),
            make_patch_unit(unit_id="pu-b", files=("src/b/**",), tests=("t_b", "t_shared")),
        )
    )
    sink = InMemoryAuditSink()
    result = post_tool_use(
        _input(
            (ChangedFile(path="src/a/x.py"), ChangedFile(path="src/b/y.py")),
            contract=contract,
        ),
        sink,
    )
    assert result.decision == Decision.ALLOW
    assert "t_a" in result.detail
    assert "t_b" in result.detail
    assert "t_shared" in result.detail


def test_timeout_overrun_denies() -> None:
    sink = InMemoryAuditSink()
    result = post_tool_use(
        _input(
            (ChangedFile(path="src/app/page.tsx"),),
            budget=make_budget("post_tool_use", expired=True),
        ),
        sink,
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED
    assert len(sink.records) == 0
