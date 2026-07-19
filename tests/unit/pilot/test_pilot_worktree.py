"""Customer worktree isolation — implement-only writes, collision refusal."""

from __future__ import annotations

from pathlib import Path

import pytest
from _pilot_fixtures import run_git
from saena_pilot.errors import BoundaryViolationError, WorktreeCollisionError
from saena_pilot.models import Mode
from saena_pilot.worktree import (
    branch_name,
    create_customer_worktree,
    worktree_container,
    worktree_path,
)

RUN_ID = "12345678-1234-1234-1234-123456789abc"


class TestCreation:
    def test_implement_creates_worktree_and_branch(self, customer_repo: Path) -> None:
        target = create_customer_worktree(customer_repo, RUN_ID, mode=Mode.IMPLEMENT)
        assert target == worktree_path(customer_repo, RUN_ID)
        assert target.is_dir()
        # location: sibling container next to the customer repo, run-id leaf
        assert target.parent == customer_repo.parent / f"{customer_repo.name}.saena-worktrees"
        result = run_git(target, "rev-parse", "--abbrev-ref", "HEAD")
        assert result.stdout.strip() == branch_name(RUN_ID) == f"saena-pilot/{RUN_ID}"
        # the worktree is registered against the CUSTOMER repo
        listed = run_git(customer_repo, "worktree", "list")
        assert str(target) in listed.stdout

    def test_worktree_never_inside_customer_root(self, customer_repo: Path) -> None:
        container = worktree_container(customer_repo)
        assert customer_repo not in container.parents
        assert container.parent == customer_repo.parent


class TestModeCapability:
    @pytest.mark.parametrize(
        "mode",
        [Mode.PREFLIGHT, Mode.AUDIT, Mode.PLAN, Mode.VERIFY, Mode.RESUME, Mode.STATUS],
    )
    def test_read_modes_carry_no_write_capability(self, customer_repo: Path, mode: Mode) -> None:
        assert not mode.writes_customer
        with pytest.raises(BoundaryViolationError, match="no customer write capability"):
            create_customer_worktree(customer_repo, RUN_ID, mode=mode)
        assert not worktree_container(customer_repo).exists()

    def test_only_implement_writes(self) -> None:
        assert [m for m in Mode if m.writes_customer] == [Mode.IMPLEMENT]


class TestCollisions:
    def test_existing_directory_is_distinct_error(self, customer_repo: Path) -> None:
        target = worktree_path(customer_repo, RUN_ID)
        target.mkdir(parents=True)
        with pytest.raises(WorktreeCollisionError, match="directory already exists"):
            create_customer_worktree(customer_repo, RUN_ID, mode=Mode.IMPLEMENT)

    def test_existing_branch_is_distinct_error(self, customer_repo: Path) -> None:
        assert run_git(customer_repo, "branch", branch_name(RUN_ID)).returncode == 0
        with pytest.raises(WorktreeCollisionError, match="branch"):
            create_customer_worktree(customer_repo, RUN_ID, mode=Mode.IMPLEMENT)
        assert not worktree_path(customer_repo, RUN_ID).exists()

    def test_second_create_for_same_run_refused(self, customer_repo: Path) -> None:
        create_customer_worktree(customer_repo, RUN_ID, mode=Mode.IMPLEMENT)
        with pytest.raises(WorktreeCollisionError):
            create_customer_worktree(customer_repo, RUN_ID, mode=Mode.IMPLEMENT)
