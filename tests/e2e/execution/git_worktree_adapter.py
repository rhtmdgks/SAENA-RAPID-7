"""A REAL, git-backed `WorktreeHandle`/`WorktreeFactory` implementation.

`saena_agent_runner.worktree` (this repo's `services/platform/
agent-runner-service`) ships only `typing.Protocol` definitions plus
`FakeWorktreeHandle`/`FakeWorktreeFactory` — reference adapters backed by a
plain temp directory with NO `git`/`subprocess` involvement at all (see that
module's own docstring: "A real adapter (actual `git worktree add`/
`subprocess.run`) is a LATER, separate concern"). This E2E suite's mission
is specifically to prove the patch-unit execution path against a REAL
synthetic git repository, so this module supplies that real adapter as
test-harness glue (mirrors `tests/integration/approval_flow/
approval_harness.py::PlanContractHttpGateAdapter`'s own precedent: a
Protocol implementation built in `tests/`, never a change to either
service's own exclusive-write path).

`GitWorktreeFactory.create(...)` runs a REAL `git worktree add <path>
<base_commit>` against a REAL on-disk git repository (`GitSyntheticRepo`,
below) — the returned `GitWorktreeHandle` is a genuine, isolated git
worktree, not a bare temp directory. `write_file`/`diff_stat`/`commit`/
`rollback` all shell out to real `git` subprocess calls.

Reported as a gap (not fixed in `services/`, per this unit's task
boundary): agent-runner-service ships no real git adapter of its own today
— any production wiring needs an adapter equivalent to this one, promoted
out of test-only code.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GitCommandError(RuntimeError):
    """A real `git` subprocess invocation exited non-zero."""


def _run_git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitCommandError(
            f"git {' '.join(args)} (cwd={cwd}) failed rc={result.returncode}: {result.stderr}"
        )
    return result.stdout


@dataclass
class GitSyntheticRepo:
    """A REAL, on-disk git repository — the synthetic tenant source repo
    this E2E suite's agent-runner step patches. Created fresh per test via
    the `git_synthetic_repo` fixture (see `conftest.py`), torn down via
    `cleanup()`.
    """

    root: Path

    @classmethod
    def init(cls, root: Path, *, seed_files: dict[str, bytes]) -> GitSyntheticRepo:
        root.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "-q", "-b", "main"], cwd=root)
        _run_git(["config", "user.email", "e2e-synthetic@saena.test"], cwd=root)
        _run_git(["config", "user.name", "SAENA E2E Synthetic Tenant"], cwd=root)
        for relative_path, content in seed_files.items():
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        _run_git(["add", "-A"], cwd=root)
        _run_git(["commit", "-q", "-m", "seed: synthetic tenant repo baseline"], cwd=root)
        return cls(root=root)

    @property
    def base_commit(self) -> str:
        return _run_git(["rev-parse", "HEAD"], cwd=self.root).strip()

    def show_file_at(self, commit: str, relative_path: str) -> bytes:
        """Real `git show <commit>:<path>` — used by tests to independently
        verify a patch actually landed in the real repo history."""
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=str(self.root),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", "replace")
            raise GitCommandError(f"git show {commit}:{relative_path} failed: {stderr_text}")
        return result.stdout

    def unified_diff(self, base_commit: str, target_commit: str) -> bytes:
        """Real `git diff <base>..<target>` unified-diff bytes — the actual
        patch content this suite's artifact-registry step registers."""
        result = subprocess.run(
            ["git", "diff", f"{base_commit}..{target_commit}"],
            cwd=str(self.root),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitCommandError(f"git diff failed: {result.stderr.decode('utf-8', 'replace')}")
        return result.stdout

    def log_commits(self) -> list[str]:
        """Real `git log` short-sha list — used to prove the worktree's
        commit actually merged back into the repo's own history via `git
        worktree add`'s shared object store (worktrees share one `.git`)."""
        raw = _run_git(["log", "--all", "--format=%H"], cwd=self.root)
        return [line for line in raw.splitlines() if line]

    def cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)


class GitWorktreeHandle:
    """REAL `WorktreeHandle` — every operation shells out to actual `git`.

    Satisfies `saena_agent_runner.worktree.WorktreeHandle`'s Protocol shape
    structurally (duck-typed; `runtime_checkable` `isinstance` checks pass).
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        run_id: str,
        patch_unit_id: str,
        base_commit: str,
        root: Path,
        repo: GitSyntheticRepo,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.patch_unit_id = patch_unit_id
        self.base_commit = base_commit
        self.root = root
        self._repo = repo
        self._written: set[str] = set()
        self._last_commit: str | None = None

    def write_file(self, relative_path: str, content: bytes) -> None:
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self._written.add(relative_path)

    def read_file(self, relative_path: str) -> bytes:
        return (self.root / relative_path).read_bytes()

    def diff_stat(self):  # -> DiffStat-shaped object (duck-typed dataclass below)
        _run_git(["add", "-A"], cwd=self.root)
        numstat = _run_git(["diff", "--cached", "--numstat"], cwd=self.root)
        files_changed = 0
        lines_changed = 0
        for line in numstat.splitlines():
            if not line.strip():
                continue
            added, removed, _path = line.split("\t", 2)
            files_changed += 1
            # Binary files report "-" for added/removed — treat as 0 lines
            # changed for the purpose of this budget check (no synthetic
            # binary fixtures are used by this suite).
            lines_changed += (int(added) if added != "-" else 0) + (
                int(removed) if removed != "-" else 0
            )
        return _DiffStat(files_changed=files_changed, lines_changed=lines_changed)

    def changed_files(self) -> list[str]:
        return sorted(self._written)

    def commit(self, message: str) -> str:
        # `diff_stat()` already ran `git add -A` — re-run defensively in
        # case a caller commits without calling diff_stat() first (the
        # Protocol does not guarantee call order beyond what runner.py
        # itself does, which DOES call diff_stat() before commit()).
        _run_git(["add", "-A"], cwd=self.root)
        _run_git(["commit", "-q", "-m", message], cwd=self.root)
        commit_sha = _run_git(["rev-parse", "HEAD"], cwd=self.root).strip()
        self._last_commit = commit_sha
        self._written = set()
        return commit_sha

    def rollback(self) -> None:
        """Real `git reset --hard` + `git clean -fd` — discards ALL
        uncommitted work, leaving no partial commit behind (matches the
        Protocol's documented guarantee)."""
        _run_git(["reset", "-q", "--hard", "HEAD"], cwd=self.root)
        _run_git(["clean", "-q", "-fd"], cwd=self.root)
        self._written = set()

    @property
    def last_commit(self) -> str | None:
        return self._last_commit


@dataclass(frozen=True, slots=True)
class _DiffStat:
    files_changed: int
    lines_changed: int


@dataclass
class GitWorktreeFactory:
    """REAL `WorktreeFactory` — provisions an isolated worktree per patch
    unit via `git worktree add <path> <base_commit>` against a shared
    `GitSyntheticRepo`."""

    repo: GitSyntheticRepo
    _tmp_root: Path
    created: list[GitWorktreeHandle] = field(default_factory=list)
    _worktree_paths: list[Path] = field(default_factory=list)

    def create(
        self, *, tenant_id: str, run_id: str, patch_unit_id: str, base_commit: str
    ) -> GitWorktreeHandle:
        worktree_path = self._tmp_root / tenant_id / run_id / patch_unit_id
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        # Real `git worktree add`, detached at base_commit — each patch
        # unit gets its own real, isolated working directory sharing the
        # SAME underlying .git object store (proving "worktree" is not
        # just a name here).
        _run_git(
            ["worktree", "add", "--detach", str(worktree_path), base_commit],
            cwd=self.repo.root,
        )
        self._worktree_paths.append(worktree_path)
        handle = GitWorktreeHandle(
            tenant_id=tenant_id,
            run_id=run_id,
            patch_unit_id=patch_unit_id,
            base_commit=base_commit,
            root=worktree_path,
            repo=self.repo,
        )
        self.created.append(handle)
        return handle

    def cleanup(self) -> None:
        for path in self._worktree_paths:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=str(self.repo.root),
                capture_output=True,
                check=False,
            )


__all__ = [
    "GitCommandError",
    "GitSyntheticRepo",
    "GitWorktreeFactory",
    "GitWorktreeHandle",
]
