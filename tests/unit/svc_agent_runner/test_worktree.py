"""`WorktreeHandle`/`CommandExecutor` Protocol fakes — no real git/subprocess."""

from __future__ import annotations

from saena_agent_runner.worktree import (
    CommandExecutor,
    CommandResult,
    FakeCommandExecutor,
    FakeWorktreeFactory,
    WorktreeFactory,
    WorktreeHandle,
)


def test_fake_worktree_handle_satisfies_protocol() -> None:
    factory = FakeWorktreeFactory()
    handle = factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    assert isinstance(handle, WorktreeHandle)
    assert isinstance(factory, WorktreeFactory)
    factory.cleanup()


def test_write_read_roundtrip(worktree_factory: FakeWorktreeFactory) -> None:
    handle = worktree_factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    handle.write_file("a.txt", b"hello\nworld\n")
    assert handle.read_file("a.txt") == b"hello\nworld\n"
    assert handle.changed_files() == ["a.txt"]


def test_diff_stat_counts_files_and_lines(worktree_factory: FakeWorktreeFactory) -> None:
    handle = worktree_factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    handle.write_file("a.txt", b"line1\nline2\nline3\n")
    handle.write_file("b.txt", b"only line\n")
    stat = handle.diff_stat()
    assert stat.files_changed == 2
    assert stat.lines_changed == 4  # 3 new lines in a.txt + 1 new line in b.txt


def test_commit_is_deterministic_and_clears_pending_writes(
    worktree_factory: FakeWorktreeFactory,
) -> None:
    handle = worktree_factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    handle.write_file("a.txt", b"content")
    sha = handle.commit("test commit")
    assert isinstance(sha, str) and len(sha) == 40
    assert handle.changed_files() == []
    assert handle.diff_stat().files_changed == 0


def test_rollback_leaves_no_partial_commit(worktree_factory: FakeWorktreeFactory) -> None:
    """Failure cleanup: rollback() discards pending writes entirely — the
    written file no longer exists on disk, and no commit was ever made."""
    handle = worktree_factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    handle.write_file("new_file.txt", b"partial work")
    assert (handle.root / "new_file.txt").exists()

    handle.rollback()

    assert not (handle.root / "new_file.txt").exists()
    assert handle.changed_files() == []
    assert handle.last_commit is None


def test_rollback_restores_original_content_for_seeded_files() -> None:
    factory = FakeWorktreeFactory(seed_files_by_tenant={"acme-co": {"a.txt": b"original"}})
    handle = factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    handle.write_file("a.txt", b"tampered")
    handle.rollback()
    assert handle.read_file("a.txt") == b"original"
    factory.cleanup()


def test_worktrees_are_isolated_per_patch_unit(worktree_factory: FakeWorktreeFactory) -> None:
    handle_1 = worktree_factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    handle_2 = worktree_factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-02", base_commit="a" * 40
    )
    handle_1.write_file("shared_name.txt", b"unit one content")
    assert not (handle_2.root / "shared_name.txt").exists()
    assert handle_1.root != handle_2.root


def test_fake_command_executor_never_spawns_real_process(
    command_executor: FakeCommandExecutor, worktree_factory: FakeWorktreeFactory
) -> None:
    handle = worktree_factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    command_executor.register_result(["pytest", "-q"], CommandResult(returncode=0, stdout="ok"))
    result = command_executor.run(["pytest", "-q"], worktree=handle)
    assert result.ok
    assert command_executor.invocations == [("pytest", "-q")]
    assert isinstance(command_executor, CommandExecutor)


def test_fake_command_executor_returns_registered_failure(
    command_executor: FakeCommandExecutor, worktree_factory: FakeWorktreeFactory
) -> None:
    handle = worktree_factory.create(
        tenant_id="acme-co", run_id="run-1", patch_unit_id="PU-01", base_commit="a" * 40
    )
    command_executor.register_result(["pytest"], CommandResult(returncode=1, stderr="boom"))
    result = command_executor.run(["pytest"], worktree=handle)
    assert not result.ok
