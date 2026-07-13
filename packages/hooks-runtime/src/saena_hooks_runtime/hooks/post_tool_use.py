"""`post_tool_use` hook (B-department prompt package v1 §11):

"post_tool_use: record_changed_file_and_patch_unit, append_audit_event,
mark_required_tests_dirty. timeout 10s, fail-closed (audit append failure
⇒ run marked unstable). Blocks: audit append failure, unexplained file
changes."

Unlike the other four hooks, this one runs AFTER a tool call has already
executed — it cannot un-execute it. Its two "Blocks" therefore map to two
DIFFERENT decisions, not one:

- an unexplained file change (a changed file matching none of the
  contract's `patch_units[*].files`) is reported as `Decision.DENY` — the
  runtime adapter is expected to treat this as "the run must stop / be
  escalated", even though the write already happened.
- an audit-append failure is reported as `Decision.UNSTABLE` (task
  instructions' own words: "run marked unstable") — a distinct outcome
  from `DENY`, because the tool call itself was legitimate; what failed is
  the ability to durably RECORD that it happened.

If both conditions are present in the same call, `UNEXPLAINED_FILE_CHANGE`
(a `DENY`) takes precedence — it is checked first (`record_changed_file_and_patch_unit`
before `append_audit_event`, matching §11's listed order), and its
resulting `HookDecision` is returned WITHOUT ever calling
`append_audit_event` (an already-DENY decision does not additionally need
appending in this call — the runtime adapter's own escalation path owns
getting a DENY reliably recorded).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contract import ActionContract
from ..models import Decision, HookDecision, ReasonCode, TimeoutBudget
from ..paths import glob_match, normalize_path
from ..ports import AuditSink
from ..redact import redact_patterns
from ._common import build_decision

HOOK_NAME = "post_tool_use"


@dataclass(frozen=True, slots=True)
class ChangedFile:
    path: str


@dataclass(frozen=True, slots=True)
class PostToolUseInput:
    ts: str
    run_id: str
    tenant_id: str
    trace_id: str
    contract: ActionContract | None
    changed_files: tuple[ChangedFile, ...]
    budget: TimeoutBudget


def _find_owning_patch_unit(path: str, contract: ActionContract) -> str | None:
    normalized = normalize_path(path)
    for unit in contract.patch_units:
        if any(glob_match(pattern, normalized) for pattern in unit.files):
            return unit.unit_id
    return None


def record_changed_file_and_patch_unit(
    input: PostToolUseInput,
) -> tuple[ReasonCode | None, str, tuple[tuple[str, str], ...]]:
    """Returns `(reason, detail, matched_pairs)` — `matched_pairs` is
    `(file_path, patch_unit_id)` for every changed file that DID map to a
    declared patch unit (fed to `mark_required_tests_dirty`). `reason` is
    `ReasonCode.UNEXPLAINED_FILE_CHANGE` (fail-closed DENY, per §11) if
    `input.contract` is absent, or if any changed file matches no patch
    unit's `files` glob list."""
    if input.contract is None:
        return (
            ReasonCode.UNEXPLAINED_FILE_CHANGE,
            "changed files recorded with no Action Contract to attribute them to — fail-closed",
            (),
        )
    matched: list[tuple[str, str]] = []
    unexplained: list[str] = []
    for cf in input.changed_files:
        unit_id = _find_owning_patch_unit(cf.path, input.contract)
        if unit_id is None:
            unexplained.append(cf.path)
        else:
            matched.append((cf.path, unit_id))
    if unexplained:
        detail = redact_patterns(
            "changed file(s) not covered by any patch unit's declared files: "
            + ", ".join(unexplained)
        )
        return ReasonCode.UNEXPLAINED_FILE_CHANGE, detail, tuple(matched)
    return None, "", tuple(matched)


def mark_required_tests_dirty(
    contract: ActionContract | None, matched_pairs: tuple[tuple[str, str], ...]
) -> tuple[str, ...]:
    """Returns the set of test ids to re-run, drawn from every patch unit a
    changed file mapped to — deduplicated, insertion order preserved."""
    if contract is None:
        return ()
    unit_by_id = {unit.unit_id: unit for unit in contract.patch_units}
    seen: set[str] = set()
    dirty: list[str] = []
    for _path, unit_id in matched_pairs:
        unit = unit_by_id.get(unit_id)
        if unit is None:
            continue
        for test in unit.tests:
            if test not in seen:
                seen.add(test)
                dirty.append(test)
    return tuple(dirty)


def append_audit_event(sink: AuditSink, record: HookDecision) -> ReasonCode | None:
    """Appends `record.audit` to `sink`. Returns
    `ReasonCode.AUDIT_APPEND_FAILURE` if `sink.append` raises (ANY
    exception — this is the fail-closed contract every `AuditSink` adapter
    is expected to honor: raise, never swallow, on failure), else `None`.
    """
    try:
        sink.append(record.audit)
    except Exception:
        return ReasonCode.AUDIT_APPEND_FAILURE
    return None


def post_tool_use(input: PostToolUseInput, audit_sink: AuditSink) -> HookDecision:
    if input.budget.expired:
        return build_decision(
            ts=input.ts,
            hook=HOOK_NAME,
            decision=Decision.DENY,
            reason_code=ReasonCode.TIMEOUT_EXCEEDED,
            detail="post_tool_use exceeded its 10s budget — fail-closed deny",
            tenant_id=input.tenant_id,
            run_id=input.run_id,
            trace_id=input.trace_id,
        )

    change_reason, change_detail, matched_pairs = record_changed_file_and_patch_unit(input)
    if change_reason is not None:
        return build_decision(
            ts=input.ts,
            hook=HOOK_NAME,
            decision=Decision.DENY,
            reason_code=change_reason,
            detail=change_detail,
            tenant_id=input.tenant_id,
            run_id=input.run_id,
            trace_id=input.trace_id,
        )

    dirty_tests = mark_required_tests_dirty(input.contract, matched_pairs)
    detail = f"dirty_tests={list(dirty_tests)}" if dirty_tests else ""

    allow_decision = build_decision(
        ts=input.ts,
        hook=HOOK_NAME,
        decision=Decision.ALLOW,
        reason_code=ReasonCode.OK,
        detail=detail,
        tenant_id=input.tenant_id,
        run_id=input.run_id,
        trace_id=input.trace_id,
    )

    append_reason = append_audit_event(audit_sink, allow_decision)
    if append_reason is not None:
        return build_decision(
            ts=input.ts,
            hook=HOOK_NAME,
            decision=Decision.UNSTABLE,
            reason_code=append_reason,
            detail="audit append failed — run marked unstable (fail-closed)",
            tenant_id=input.tenant_id,
            run_id=input.run_id,
            trace_id=input.trace_id,
        )

    return allow_decision


__all__ = [
    "ChangedFile",
    "PostToolUseInput",
    "append_audit_event",
    "mark_required_tests_dirty",
    "post_tool_use",
    "record_changed_file_and_patch_unit",
]
