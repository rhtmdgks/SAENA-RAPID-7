"""H-3 evidence anchoring / scope-glob / diff-budget enforcement.

security-model.md H-3: "근거 고정 (H-3): Action Contract에 evidence_ledger_hash
+ scope glob 상한 + diff 예산. 실험 등록 hash는 audit-ledger 앵커링."

Field names below are taken verbatim from change-plan.schema.json (the
contract's field names and enums are authoritative over doc prose per this
unit's spec basis):
    - evidence_ledger_hash: sha256_ref (required, non-null by schema — this
      module additionally rejects empty/whitespace-only strings defensively)
    - approved_scope: list[str], glob-like scope strings
    - scope_limits.max_globs: int >= 1 — caps COUNT of approved_scope entries
      (schema $comment: glob-breadth, e.g. '**/*', is explicitly NOT
      schema-expressible and is a policy-gate concern — enforced here)
    - diff_budget.max_files / max_lines: int >= 1

Scope glob escape rule (relative, no `..`, within declared roots) is this
module's own H-3 interpretation of "declared roots" as the schema's
approved_scope entries themselves: every glob must be a relative path (no
leading '/'), must not contain a '..' path segment, and must not escape via
absolute/URI form. There is no separate "declared roots" field in
change-plan.schema.json — approved_scope IS the declared root set. Flagged as
an OPEN ITEM: the spec text says "within declared roots" without naming a
distinct roots field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _ScopeLimits(Protocol):
    max_globs: int


class _DiffBudget(Protocol):
    max_files: int
    max_lines: int


class _ChangePlanLike(Protocol):
    evidence_ledger_hash: object
    approved_scope: list[str]
    scope_limits: _ScopeLimits
    diff_budget: _DiffBudget


@dataclass(frozen=True, slots=True)
class DiffStats:
    """Observed diff size for a proposed change, evaluated against diff_budget."""

    files_changed: int
    lines_changed: int


@dataclass(frozen=True, slots=True)
class H3PolicyResult:
    """Outcome of evaluate_h3_evidence_policy — never raises; caller decides."""

    ok: bool
    violations: tuple[str, ...]


def _is_glob_escape(glob: str) -> bool:
    if not glob or glob.strip() != glob:
        return True
    if glob.startswith("/"):
        return True
    if "://" in glob:
        return True
    segments = glob.split("/")
    return any(segment == ".." for segment in segments)


def evaluate_h3_evidence_policy(
    plan: _ChangePlanLike,
    *,
    diff_stats: DiffStats | None = None,
) -> H3PolicyResult:
    """Evaluate H-3 gates for a ChangePlan. Pure function, no exceptions raised.

    Checks:
    1. evidence_ledger_hash present and non-blank (schema already requires the
       field to exist and match sha256_ref pattern; this is a defensive
       non-blank check for callers constructing plans outside schema
       validation, e.g. in-process before serialization).
    2. len(approved_scope) <= scope_limits.max_globs.
    3. every approved_scope entry is a relative, non-escaping glob (no `..`,
       no leading '/', no URI scheme).
    4. if diff_stats provided: files_changed <= diff_budget.max_files and
       lines_changed <= diff_budget.max_lines.
    """
    violations: list[str] = []

    evidence_hash = getattr(plan, "evidence_ledger_hash", None)
    evidence_hash_str = str(evidence_hash) if evidence_hash is not None else ""
    if not evidence_hash_str.strip():
        violations.append("missing evidence_ledger_hash")

    if len(plan.approved_scope) > plan.scope_limits.max_globs:
        violations.append(
            f"approved_scope has {len(plan.approved_scope)} entries, "
            f"exceeds scope_limits.max_globs={plan.scope_limits.max_globs}"
        )

    for glob in plan.approved_scope:
        if _is_glob_escape(glob):
            violations.append(f"scope glob escapes declared roots: {glob!r}")

    if diff_stats is not None:
        if diff_stats.files_changed > plan.diff_budget.max_files:
            violations.append(
                f"diff files_changed={diff_stats.files_changed} exceeds "
                f"diff_budget.max_files={plan.diff_budget.max_files}"
            )
        if diff_stats.lines_changed > plan.diff_budget.max_lines:
            violations.append(
                f"diff lines_changed={diff_stats.lines_changed} exceeds "
                f"diff_budget.max_lines={plan.diff_budget.max_lines}"
            )

    return H3PolicyResult(ok=not violations, violations=tuple(violations))
