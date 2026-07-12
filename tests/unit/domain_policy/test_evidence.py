"""H-3: missing evidence, scope glob escape, diff budget exceeded (task TESTS)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from saena_domain.policy.evidence import DiffStats, evaluate_h3_evidence_policy


@dataclass
class _ScopeLimits:
    max_globs: int


@dataclass
class _DiffBudget:
    max_files: int
    max_lines: int


@dataclass
class _Plan:
    evidence_ledger_hash: object
    approved_scope: list[str]
    scope_limits: _ScopeLimits
    diff_budget: _DiffBudget


VALID_HASH = "sha256:" + "a" * 64


def _plan(**overrides: object) -> _Plan:
    defaults: dict[str, object] = {
        "evidence_ledger_hash": VALID_HASH,
        "approved_scope": ["apps/web/docs/*"],
        "scope_limits": _ScopeLimits(max_globs=5),
        "diff_budget": _DiffBudget(max_files=10, max_lines=500),
    }
    defaults.update(overrides)
    return _Plan(**defaults)  # type: ignore[arg-type]


def test_valid_plan_passes_h3() -> None:
    result = evaluate_h3_evidence_policy(_plan())
    assert result.ok
    assert result.violations == ()


def test_missing_evidence_ledger_hash_rejected() -> None:
    result = evaluate_h3_evidence_policy(_plan(evidence_ledger_hash=""))
    assert not result.ok
    assert any("evidence_ledger_hash" in v for v in result.violations)


def test_none_evidence_ledger_hash_rejected() -> None:
    result = evaluate_h3_evidence_policy(_plan(evidence_ledger_hash=None))
    assert not result.ok
    assert any("evidence_ledger_hash" in v for v in result.violations)


@pytest.mark.parametrize(
    "glob",
    [
        "../etc/passwd",
        "apps/../../../etc/passwd",
        "/etc/passwd",
        "file:///etc/passwd",
        " apps/web/docs/*",
    ],
)
def test_scope_glob_escape_rejected(glob: str) -> None:
    result = evaluate_h3_evidence_policy(_plan(approved_scope=[glob]))
    assert not result.ok
    assert any("scope glob escapes" in v for v in result.violations)


def test_scope_glob_relative_within_root_accepted() -> None:
    result = evaluate_h3_evidence_policy(
        _plan(approved_scope=["apps/web/docs/*", "apps/web/components/*"])
    )
    assert result.ok


def test_scope_glob_count_exceeds_max_globs_rejected() -> None:
    result = evaluate_h3_evidence_policy(
        _plan(
            approved_scope=["a/*", "b/*", "c/*"],
            scope_limits=_ScopeLimits(max_globs=2),
        )
    )
    assert not result.ok
    assert any("max_globs" in v for v in result.violations)


def test_diff_budget_files_exceeded_rejected() -> None:
    result = evaluate_h3_evidence_policy(
        _plan(diff_budget=_DiffBudget(max_files=1, max_lines=100)),
        diff_stats=DiffStats(files_changed=2, lines_changed=10),
    )
    assert not result.ok
    assert any("max_files" in v for v in result.violations)


def test_diff_budget_lines_exceeded_rejected() -> None:
    result = evaluate_h3_evidence_policy(
        _plan(diff_budget=_DiffBudget(max_files=10, max_lines=100)),
        diff_stats=DiffStats(files_changed=1, lines_changed=200),
    )
    assert not result.ok
    assert any("max_lines" in v for v in result.violations)


def test_diff_budget_within_limits_accepted() -> None:
    result = evaluate_h3_evidence_policy(
        _plan(diff_budget=_DiffBudget(max_files=10, max_lines=500)),
        diff_stats=DiffStats(files_changed=5, lines_changed=200),
    )
    assert result.ok


def test_diff_stats_omitted_skips_budget_check() -> None:
    result = evaluate_h3_evidence_policy(_plan())
    assert result.ok


def test_multiple_violations_all_reported() -> None:
    result = evaluate_h3_evidence_policy(
        _plan(
            evidence_ledger_hash="",
            approved_scope=["../escape"],
            scope_limits=_ScopeLimits(max_globs=5),
        ),
    )
    assert not result.ok
    assert len(result.violations) == 2
