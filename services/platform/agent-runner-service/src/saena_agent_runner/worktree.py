"""`WorktreeHandle`/`CommandExecutor` Protocols + in-memory (real-tempdir) fakes.

Mission constraint: "Pure-domain core + Protocol adapters (worktree ops,
command exec) with in-memory fakes — NO real git/subprocess in unit tests."
`FakeWorktreeHandle` is backed by a REAL temporary directory (plain
`pathlib`/filesystem I/O, no `git` binary, no `subprocess`) so
`resolve_within_worktree`'s symlink-escape guard can be exercised with a
real symlink in tests; `FakeCommandExecutor` never spawns a process at all —
it only records invocations and returns a caller-registered canned result.
A real adapter (actual `git worktree add`/`subprocess.run`) is a LATER,
separate concern (this package's exclusive-write scope covers the pure
domain core + these Protocols + fakes only).

Every `WorktreeHandle` is scoped to exactly one `(tenant_id, run_id,
patch_unit_id)` triple and pinned to one `base_commit` for its whole
lifetime — `runner.py` is the ONLY caller that constructs one (via
`WorktreeFactory.create`), and it re-validates `tenant_id`/`base_commit`
against the executing `JobContext`/`ChangePlan` before doing anything else
with the returned handle (defense-in-depth: this module does not itself
trust that a factory implementation got tenant scoping right).
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from saena_agent_runner.scope import resolve_within_worktree


@dataclass(frozen=True, slots=True)
class DiffStat:
    """Realized diff size for a patch unit's uncommitted writes."""

    files_changed: int
    lines_changed: int


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of one `CommandExecutor.run` call."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@runtime_checkable
class WorktreeHandle(Protocol):
    """Per-patch-unit isolated worktree — file read/write/diff/commit/rollback.

    `tenant_id`/`run_id`/`patch_unit_id`/`base_commit` are fixed at
    construction and never mutated — a handle is a single-use, single-scope
    object for exactly one patch unit's execution attempt.
    """

    tenant_id: str
    run_id: str
    patch_unit_id: str
    base_commit: str
    root: Path

    def write_file(self, relative_path: str, content: bytes) -> None:
        """Write `content` to `relative_path` (resolved within `root`)."""
        ...

    def read_file(self, relative_path: str) -> bytes:
        """Read the current content of `relative_path` (resolved within `root`)."""
        ...

    def diff_stat(self) -> DiffStat:
        """Realized diff size of writes since the last `commit()` (or since
        construction, if never committed)."""
        ...

    def changed_files(self) -> list[str]:
        """Sorted list of relative paths written since the last `commit()`."""
        ...

    def commit(self, message: str) -> str:
        """Commit all pending writes; returns the new worktree commit id.

        Idempotent boundary is NOT implied here — callers must not call this
        twice for the same logical attempt without an intervening
        `rollback()`.
        """
        ...

    def rollback(self) -> None:
        """Discard all pending (uncommitted) writes.

        Guarantees NO partial commit is ever left behind: after this call,
        the worktree's on-disk state is exactly what it was immediately
        after construction (or immediately after the last successful
        `commit()`), and `changed_files()`/`diff_stat()` report empty/zero.
        """
        ...


@runtime_checkable
class WorktreeFactory(Protocol):
    """Provisions one isolated `WorktreeHandle` per patch-unit execution attempt."""

    def create(
        self, *, tenant_id: str, run_id: str, patch_unit_id: str, base_commit: str
    ) -> WorktreeHandle:
        """Provision a fresh, isolated worktree pinned to `base_commit`."""
        ...


@runtime_checkable
class CommandExecutor(Protocol):
    """Runs an allowlisted command against a `WorktreeHandle`'s working directory."""

    def run(self, argv: Sequence[str], *, worktree: WorktreeHandle) -> CommandResult:
        """Execute `argv` with `worktree.root` as the working directory.

        Callers MUST have already passed `argv` through
        `saena_agent_runner.commands.guard_command` — this Protocol itself
        performs no allowlist check (that is a cross-cutting concern
        applied once, in `runner.py`, not duplicated into every adapter).
        """
        ...


def _line_diff_count(old: bytes, new: bytes) -> int:
    """Count changed (added/removed) lines between `old` and `new` content."""
    old_lines = old.decode("utf-8", errors="replace").splitlines()
    new_lines = new.decode("utf-8", errors="replace").splitlines()
    changed = 0
    for line in difflib.unified_diff(old_lines, new_lines, lineterm=""):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            changed += 1
    return changed


class FakeWorktreeHandle:
    """Reference `WorktreeHandle` backed by a real temp directory.

    No `git`/`subprocess` involvement at all — `commit()` returns a
    deterministic fake sha derived from content hashes, purely for test
    determinism and to give `runner.py`/events something sha-shaped to
    carry as `worktree_commit`.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        run_id: str,
        patch_unit_id: str,
        base_commit: str,
        root: Path,
        seed_files: Mapping[str, bytes] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.patch_unit_id = patch_unit_id
        self.base_commit = base_commit
        self.root = root
        self._baseline: dict[str, bytes] = {}
        self._writes: dict[str, bytes] = {}
        self._last_commit: str | None = None
        for relative_path, content in (seed_files or {}).items():
            self._write_to_disk(relative_path, content)
            self._baseline[relative_path] = content

    def _write_to_disk(self, relative_path: str, content: bytes) -> None:
        resolved = resolve_within_worktree(self.root, relative_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(content)

    def write_file(self, relative_path: str, content: bytes) -> None:
        self._write_to_disk(relative_path, content)
        self._writes[relative_path] = content

    def read_file(self, relative_path: str) -> bytes:
        resolved = resolve_within_worktree(self.root, relative_path)
        return resolved.read_bytes()

    def diff_stat(self) -> DiffStat:
        lines_changed = sum(
            _line_diff_count(self._baseline.get(relative_path, b""), content)
            for relative_path, content in self._writes.items()
        )
        return DiffStat(files_changed=len(self._writes), lines_changed=lines_changed)

    def changed_files(self) -> list[str]:
        return sorted(self._writes)

    def commit(self, message: str) -> str:
        digest_source = "|".join(
            [
                self.base_commit,
                message,
                *(
                    f"{relative_path}:{hashlib.sha256(content).hexdigest()}"
                    for relative_path, content in sorted(self._writes.items())
                ),
            ]
        )
        # `PatchArtifact.worktree_commit` (patch_artifact_v1 schema) requires
        # a 7-40 lowercase-hex string (a real git-sha shape, short or full) —
        # truncated to 40 chars here (a full-length git sha's own length) so
        # this fake sha, though content-derived rather than git-produced,
        # satisfies that shape.
        commit_sha = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]
        self._baseline.update(self._writes)
        self._writes = {}
        self._last_commit = commit_sha
        return commit_sha

    def rollback(self) -> None:
        """Discard pending writes — leaves NO partial commit behind."""
        for relative_path in list(self._writes):
            resolved = resolve_within_worktree(self.root, relative_path)
            if relative_path in self._baseline:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_bytes(self._baseline[relative_path])
            elif resolved.exists():
                resolved.unlink()
        self._writes = {}

    @property
    def last_commit(self) -> str | None:
        return self._last_commit


@dataclass
class FakeWorktreeFactory:
    """Reference `WorktreeFactory` — one real temp subdirectory per
    `(tenant_id, run_id, patch_unit_id)`, no git/subprocess involvement."""

    seed_files_by_tenant: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict)
    _tmp_root: Path = field(
        default_factory=lambda: Path(tempfile.mkdtemp(prefix="saena-agent-runner-fake-"))
    )
    created: list[FakeWorktreeHandle] = field(default_factory=list)

    def create(
        self, *, tenant_id: str, run_id: str, patch_unit_id: str, base_commit: str
    ) -> FakeWorktreeHandle:
        root = self._tmp_root / tenant_id / run_id / patch_unit_id
        root.mkdir(parents=True, exist_ok=True)
        handle = FakeWorktreeHandle(
            tenant_id=tenant_id,
            run_id=run_id,
            patch_unit_id=patch_unit_id,
            base_commit=base_commit,
            root=root,
            seed_files=self.seed_files_by_tenant.get(tenant_id),
        )
        self.created.append(handle)
        return handle

    def cleanup(self) -> None:
        shutil.rmtree(self._tmp_root, ignore_errors=True)


class FakeCommandExecutor:
    """Reference `CommandExecutor` — records invocations, spawns nothing.

    Returns a caller-registered `CommandResult` for a given `argv` (exact
    tuple match), or a canned `returncode=0` success otherwise.
    """

    def __init__(self) -> None:
        self.invocations: list[tuple[str, ...]] = []
        self._results: dict[tuple[str, ...], CommandResult] = {}

    def register_result(self, argv: Sequence[str], result: CommandResult) -> None:
        self._results[tuple(argv)] = result

    def run(self, argv: Sequence[str], *, worktree: WorktreeHandle) -> CommandResult:
        self.invocations.append(tuple(argv))
        return self._results.get(tuple(argv), CommandResult(returncode=0))


__all__ = [
    "CommandExecutor",
    "CommandResult",
    "DiffStat",
    "FakeCommandExecutor",
    "FakeWorktreeFactory",
    "FakeWorktreeHandle",
    "WorktreeFactory",
    "WorktreeHandle",
]
