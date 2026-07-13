"""File/glob scope, protected-path, and filesystem-boundary guards."""

from __future__ import annotations

import pytest
from saena_agent_runner.errors import (
    OutOfScopeWriteError,
    PathTraversalError,
    ProtectedPathWriteError,
)
from saena_agent_runner.scope import (
    guard_protected_path,
    guard_scope,
    is_in_approved_scope,
    resolve_within_worktree,
)


def test_is_in_approved_scope_matches_glob() -> None:
    assert is_in_approved_scope("apps/web/docs/readme.md", ["apps/web/docs/*"])
    assert not is_in_approved_scope("apps/api/main.py", ["apps/web/docs/*"])


def test_guard_scope_passes_when_declared_and_in_scope() -> None:
    guard_scope(
        "apps/web/docs/readme.md",
        patch_unit_files=["apps/web/docs/readme.md"],
        approved_scope=["apps/web/docs/*"],
    )


def test_guard_scope_denies_write_outside_approved_scope() -> None:
    """NEGATIVE: a write outside `approved_scope` must DENY, even if the
    patch unit itself declares the file in its own `files` list (a
    ChangePlan whose per-unit `files` disagrees with its own
    `approved_scope` is itself suspect — scope wins)."""
    with pytest.raises(OutOfScopeWriteError):
        guard_scope(
            "apps/api/main.py",
            patch_unit_files=["apps/api/main.py"],
            approved_scope=["apps/web/docs/*"],
        )


def test_guard_scope_denies_write_not_declared_in_patch_unit_files() -> None:
    with pytest.raises(OutOfScopeWriteError):
        guard_scope(
            "apps/web/docs/other.md",
            patch_unit_files=["apps/web/docs/readme.md"],
            approved_scope=["apps/web/docs/*"],
        )


@pytest.mark.parametrize(
    "protected_path",
    [
        "docs/specs/algorithm.md",
        "packages/contracts/json-schema/domain/change-plan/v1/change-plan.schema.json",
        "packages/schemas/saena_schemas/__init__.py",
        "deploy/charts/saena-forge/values.yaml",
        ".github/workflows/ci.yaml",
        ".git/config",
        ".cursor/rules/security.md",
        ".claude/settings.json",
    ],
)
def test_guard_protected_path_denies_structurally(protected_path: str) -> None:
    """NEGATIVE: protected-path write must DENY regardless of scope/contract."""
    with pytest.raises(ProtectedPathWriteError):
        guard_protected_path(protected_path)


def test_guard_protected_path_allows_ordinary_path() -> None:
    guard_protected_path("apps/web/docs/readme.md")


def test_resolve_within_worktree_allows_ordinary_path(tmp_path) -> None:
    (tmp_path / "apps" / "web").mkdir(parents=True)
    resolved = resolve_within_worktree(tmp_path, "apps/web/readme.md")
    assert resolved == (tmp_path / "apps" / "web" / "readme.md").resolve()


@pytest.mark.parametrize(
    "traversal_path",
    ["../outside.txt", "apps/../../outside.txt", "/etc/passwd", "../../../../etc/passwd"],
)
def test_resolve_within_worktree_denies_dotdot_and_absolute_traversal(
    tmp_path, traversal_path: str
) -> None:
    """NEGATIVE: `..`-traversal and absolute paths must be rejected."""
    with pytest.raises(PathTraversalError):
        resolve_within_worktree(tmp_path, traversal_path)


def test_resolve_within_worktree_denies_symlink_escape(tmp_path) -> None:
    """NEGATIVE: a symlink target resolving outside the worktree root must
    be rejected — the requested relative path itself contains no `..`
    segment, only the symlink's TARGET escapes."""
    outside_dir = tmp_path.parent / "outside-target"
    outside_dir.mkdir(exist_ok=True)
    worktree_root = tmp_path / "worktree"
    worktree_root.mkdir()
    escape_link = worktree_root / "escape"
    escape_link.symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(PathTraversalError):
        resolve_within_worktree(worktree_root, "escape/payload.txt")


def test_resolve_within_worktree_denies_empty_path(tmp_path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_within_worktree(tmp_path, "")
