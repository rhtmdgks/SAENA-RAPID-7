"""Shared construction helpers for `tests/unit/hooks_runtime`.

Deliberately NOT named `conftest.py`'s own module surface — pytest's
default `prepend` import mode inserts each directory containing a
`conftest.py` onto `sys.path` and imports it under the bare top-level name
`conftest`; a SECOND directory doing `from conftest import ...` while ALSO
having its own `conftest.py` collides with whichever `conftest` module
Python's import cache already holds when the full `tests/unit` suite is
collected together (`tests/unit/domain_persistence/persistence_factories.py`
documents the exact failure this caused there:
`ImportError: cannot import name '...' from 'conftest'`). This module is
imported by its own unique dotted name (inserted onto `sys.path` by
`conftest.py` in this same directory) to avoid that collision entirely.
"""

from __future__ import annotations

from saena_hooks_runtime.contract import ActionContract, PatchUnit, compute_contract_hash
from saena_hooks_runtime.models import TimeoutBudget, budget_for

RUN_ID = "run-w3-06-0001"
TENANT_ID = "acme-corp"
TRACE_ID = "trace-0001"
REPO_COMMIT = "a" * 40
TS = "2026-07-13T00:00:00Z"


def make_patch_unit(
    *,
    unit_id: str = "pu-1",
    files: tuple[str, ...] = ("src/app/page.tsx", "src/lib/seo.ts"),
    allowed_transformations: tuple[str, ...] = ("metadata-edit",),
    tests: tuple[str, ...] = ("tests/unit/app_page_test.py",),
    rollback_method: str = "git revert <commit>",
) -> PatchUnit:
    return PatchUnit(
        unit_id=unit_id,
        files=files,
        allowed_transformations=allowed_transformations,
        tests=tests,
        rollback_method=rollback_method,
    )


def make_contract(
    *,
    run_id: str = RUN_ID,
    customer_id: str = TENANT_ID,
    repo_commit: str = REPO_COMMIT,
    approved_scope: tuple[str, ...] = ("src/**", "docs/blog/**"),
    engine_scope: tuple[str, ...] = ("chatgpt-search",),
    patch_units: tuple[PatchUnit, ...] | None = None,
    approval_required: bool = True,
    bad_hash: bool = False,
) -> ActionContract:
    units = patch_units if patch_units is not None else (make_patch_unit(),)
    draft = ActionContract(
        run_id=run_id,
        customer_id=customer_id,
        repo_commit=repo_commit,
        approved_scope=approved_scope,
        engine_scope=engine_scope,
        patch_units=units,
        approval_required=approval_required,
        contract_hash="",
    )
    real_hash = compute_contract_hash(draft)
    final_hash = "0" * 64 if bad_hash else real_hash
    return ActionContract(
        run_id=draft.run_id,
        customer_id=draft.customer_id,
        repo_commit=draft.repo_commit,
        approved_scope=draft.approved_scope,
        engine_scope=draft.engine_scope,
        patch_units=draft.patch_units,
        approval_required=draft.approval_required,
        contract_hash=final_hash,
    )


def make_budget(hook: str, *, expired: bool = False) -> TimeoutBudget:
    budget = budget_for(hook, elapsed_seconds=0.0)
    if expired:
        return TimeoutBudget(
            elapsed_seconds=budget.deadline_seconds,
            deadline_seconds=budget.deadline_seconds,
        )
    return budget


__all__ = [
    "REPO_COMMIT",
    "RUN_ID",
    "TENANT_ID",
    "TRACE_ID",
    "TS",
    "make_budget",
    "make_contract",
    "make_patch_unit",
]
