"""`pre_tool_use` hook (B-department prompt package v1 §11):

"pre_tool_use: deny_out_of_scope_file_write, deny_deploy_push_cms_dns,
deny_unapproved_network_egress, deny_unpinned_dependency_install,
require_action_contract_for_write. timeout 5s/call, fail-closed. Blocks:
deployment cmd, push, production write, unpinned install, missing
contract."

Input shape covers both the file-write tool family (`Write`/`Edit`/
`MultiEdit`) and `Bash`:

- `tool_name in {"Write", "Edit", "MultiEdit"}`: `file_path` is the target;
  `resolved_path` is an OPTIONAL adapter-supplied `os.path.realpath`-style
  resolution (defeats the "symlink targets" bypass category — the pure
  engine never calls `realpath` itself, see `paths.py`'s module docstring).
- `tool_name == "Bash"`: `command` is normalized via
  `command_normalize.normalize_command` into segments; every segment is
  checked against `rules.deploy_push`, `rules.unpinned_install`,
  `rules.egress`, and (for indirect writes) `rules.write_scope`.

Check order (first failing check wins, §11 listing order):
timeout budget -> `require_action_contract_for_write` -> raw-text
pipe-to-interpreter check -> `deny_deploy_push_cms_dns` ->
`deny_unpinned_dependency_install` -> `deny_unapproved_network_egress` ->
`deny_out_of_scope_file_write`. `require_action_contract_for_write` is
checked EARLY (ahead of the command-content checks) because every other
check needs a valid `approved_scope` to check against — an invalid/missing
contract makes every other check meaningless, not just moot.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..command_normalize import UNPARSEABLE, has_pipe_to_interpreter, normalize_command
from ..contract import ActionContract, validate_contract
from ..models import Decision, HookDecision, ReasonCode, TimeoutBudget
from ..paths import path_in_scope
from ..redact import redact_patterns
from ..rules.deploy_push import matches_deploy_push_cms_dns
from ..rules.egress import matches_unapproved_egress
from ..rules.unpinned_install import matches_unpinned_install
from ..rules.write_scope import extract_write_targets
from ._common import build_decision

HOOK_NAME = "pre_tool_use"

WRITE_TOOL_NAMES = frozenset({"Write", "Edit", "MultiEdit"})
BASH_TOOL_NAME = "Bash"

#: Tool names this hook treats as write-capable, hence subject to
#: `require_action_contract_for_write`.
WRITE_CAPABLE_TOOL_NAMES = WRITE_TOOL_NAMES | {BASH_TOOL_NAME}


@dataclass(frozen=True, slots=True)
class PreToolUseInput:
    ts: str
    run_id: str
    tenant_id: str
    trace_id: str
    contract: ActionContract | None
    tool_name: str
    budget: TimeoutBudget
    # Write/Edit/MultiEdit
    file_path: str | None = None
    resolved_path: str | None = None
    # Bash
    command: str | None = None
    # Threaded through to `deny_unapproved_network_egress` (not part of the
    # `ActionContract` field set the task instructions specify — see
    # `rules/egress.py`'s docstring).
    approved_egress_domains: tuple[str, ...] = ()


def require_action_contract_for_write(input: PreToolUseInput) -> ReasonCode | None:
    if input.tool_name not in WRITE_CAPABLE_TOOL_NAMES:
        return None
    return validate_contract(input.contract)


def _candidate_write_paths(input: PreToolUseInput, segments: tuple[str, ...]) -> tuple[str, ...]:
    if input.tool_name in WRITE_TOOL_NAMES:
        paths = [p for p in (input.file_path, input.resolved_path) if p]
        return tuple(paths)
    if input.tool_name == BASH_TOOL_NAME:
        targets: list[str] = []
        for seg in segments:
            targets.extend(extract_write_targets(seg))
        return tuple(targets)
    return ()


def deny_out_of_scope_file_write(
    input: PreToolUseInput, segments: tuple[str, ...]
) -> tuple[ReasonCode | None, str]:
    approved_scope = input.contract.approved_scope if input.contract is not None else ()
    for candidate in _candidate_write_paths(input, segments):
        if not path_in_scope(candidate, approved_scope):
            return (
                ReasonCode.OUT_OF_SCOPE_FILE_WRITE,
                redact_patterns(f"write target outside approved_scope: '{candidate}'"),
            )
    return None, ""


def deny_deploy_push_cms_dns(
    segments: tuple[str, ...], raw_command: str | None
) -> tuple[ReasonCode | None, str]:
    if raw_command is not None and has_pipe_to_interpreter(raw_command):
        return (
            ReasonCode.DEPLOY_PUSH_CMS_DNS,
            "command pipes output into a shell/script interpreter",
        )
    for seg in segments:
        match = matches_deploy_push_cms_dns(seg)
        if match is not None:
            return ReasonCode.DEPLOY_PUSH_CMS_DNS, redact_patterns(f"matched deny rule: {match}")
    return None, ""


def deny_unpinned_dependency_install(segments: tuple[str, ...]) -> tuple[ReasonCode | None, str]:
    for seg in segments:
        match = matches_unpinned_install(seg)
        if match is not None:
            return ReasonCode.UNPINNED_DEPENDENCY_INSTALL, redact_patterns(match)
    return None, ""


def deny_unapproved_network_egress(
    segments: tuple[str, ...], approved_domains: tuple[str, ...]
) -> tuple[ReasonCode | None, str]:
    for seg in segments:
        match = matches_unapproved_egress(seg, approved_domains)
        if match is not None:
            return ReasonCode.UNAPPROVED_NETWORK_EGRESS, redact_patterns(match)
    return None, ""


def _deny(input: PreToolUseInput, reason: ReasonCode, detail: str) -> HookDecision:
    return build_decision(
        ts=input.ts,
        hook=HOOK_NAME,
        decision=Decision.DENY,
        reason_code=reason,
        detail=detail,
        tenant_id=input.tenant_id,
        run_id=input.run_id,
        trace_id=input.trace_id,
    )


def pre_tool_use(input: PreToolUseInput) -> HookDecision:
    if input.budget.expired:
        return _deny(
            input,
            ReasonCode.TIMEOUT_EXCEEDED,
            "pre_tool_use exceeded its 5s/call budget — fail-closed deny",
        )

    contract_issue = require_action_contract_for_write(input)
    if contract_issue is not None:
        return _deny(
            input,
            contract_issue,
            "no valid Action Contract for a write-capable tool call "
            f"({input.tool_name}) — fail-closed",
        )

    segments: tuple[str, ...] = ()
    if input.tool_name == BASH_TOOL_NAME:
        if input.command is None:
            return _deny(
                input,
                ReasonCode.COMMAND_NORMALIZE_FAILURE,
                "Bash tool call carried no command — fail-closed",
            )
        segments = normalize_command(input.command)
        if not segments or all(seg == UNPARSEABLE for seg in segments):
            return _deny(
                input,
                ReasonCode.COMMAND_NORMALIZE_FAILURE,
                "command could not be normalized — fail-closed",
            )

    deploy_reason, deploy_detail = deny_deploy_push_cms_dns(segments, input.command)
    if deploy_reason is not None:
        return _deny(input, deploy_reason, deploy_detail)

    unpinned_reason, unpinned_detail = deny_unpinned_dependency_install(segments)
    if unpinned_reason is not None:
        return _deny(input, unpinned_reason, unpinned_detail)

    egress_reason, egress_detail = deny_unapproved_network_egress(
        segments, input.approved_egress_domains
    )
    if egress_reason is not None:
        return _deny(input, egress_reason, egress_detail)

    scope_reason, scope_detail = deny_out_of_scope_file_write(input, segments)
    if scope_reason is not None:
        return _deny(input, scope_reason, scope_detail)

    return build_decision(
        ts=input.ts,
        hook=HOOK_NAME,
        decision=Decision.ALLOW,
        reason_code=ReasonCode.OK,
        detail="",
        tenant_id=input.tenant_id,
        run_id=input.run_id,
        trace_id=input.trace_id,
    )


__all__ = [
    "BASH_TOOL_NAME",
    "WRITE_CAPABLE_TOOL_NAMES",
    "WRITE_TOOL_NAMES",
    "PreToolUseInput",
    "deny_deploy_push_cms_dns",
    "deny_out_of_scope_file_write",
    "deny_unapproved_network_egress",
    "deny_unpinned_dependency_install",
    "pre_tool_use",
    "require_action_contract_for_write",
]
