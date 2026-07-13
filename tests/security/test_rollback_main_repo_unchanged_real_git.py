"""Rollback verification gate (testing-strategy.md sec F-7): "after a
rollback: main/source repo unchanged" — proven against a REAL `git` repo
in a temp directory (not a mock), per this patch unit's own instructions.

`saena_agent_runner`'s own structural guarantee (ADR-0004, `worktree.py`
module docstring) is that a patch unit's `WorktreeHandle` is a fully
isolated root — `FakeWorktreeHandle` never touches any path outside its own
temp subdirectory, and the runner never receives a handle rooted at (or
descended from) the real source repository at all. This test makes that
guarantee observable: it runs a REAL git repository alongside a
`PatchUnitRunner` attempt (using the isolated `FakeWorktreeFactory`, same as
every other test in this suite) and proves the git repo's HEAD commit and
full working-tree content hash are BYTE-IDENTICAL before and after a denied
-and-rolled-back attempt — regardless of what the (isolated, never-connected
-to-this-repo) worktree attempt did.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from runner_factories import (
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    build_approval_decision,
    build_change_plan,
)
from saena_agent_runner.approval import parse_approval_decision
from saena_agent_runner.artifact import FakeArtifactRegistryGateway
from saena_agent_runner.clock import FakeClock
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.runner import FileWrite, PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory
from saena_domain.audit import InMemoryAuditChain
from saena_domain.execution import JobContext, JobStatus


def _run_git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "saena-test",
            "GIT_AUTHOR_EMAIL": "saena-test@example.invalid",
            "GIT_COMMITTER_NAME": "saena-test",
            "GIT_COMMITTER_EMAIL": "saena-test@example.invalid",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )
    return result.stdout.strip()


def _tree_content_hash(repo_root: Path) -> str:
    """A deterministic hash of every tracked file's path + content — proves
    not just that HEAD's sha is unchanged (which alone would not catch an
    uncommitted working-tree mutation) but that the actual bytes on disk are
    unchanged too."""
    digest = hashlib.sha256()
    tracked = _run_git(["ls-files"], cwd=repo_root).splitlines()
    for relative_path in sorted(tracked):
        digest.update(relative_path.encode("utf-8"))
        digest.update((repo_root / relative_path).read_bytes())
    return digest.hexdigest()


def test_main_source_repo_is_byte_identical_after_a_denied_and_rolled_back_attempt(
    tmp_path: Path,
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    # --- arrange: a REAL git repo standing in for "the main/source repo". ---
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _run_git(["init", "-q"], cwd=main_repo)
    (main_repo / "apps").mkdir()
    (main_repo / "apps" / "web").mkdir()
    (main_repo / "apps" / "web" / "readme.md").write_text("original content\n")
    _run_git(["add", "."], cwd=main_repo)
    _run_git(["commit", "-q", "-m", "initial commit"], cwd=main_repo)

    head_before = _run_git(["rev-parse", "HEAD"], cwd=main_repo)
    tree_hash_before = _tree_content_hash(main_repo)
    status_before = _run_git(["status", "--porcelain"], cwd=main_repo)
    assert status_before == ""

    # --- act: a patch-unit attempt that is denied and rolled back — using
    # the SAME isolated worktree factory every other test in this suite
    # uses, never `main_repo` itself (the structural guarantee under test:
    # this package cannot reach `main_repo` even if it wanted to). ---
    contract = parse_change_plan(
        build_change_plan(
            approved_scope=["apps/web/docs/*"],
            patch_units=[
                {
                    "id": PATCH_UNIT_ID,
                    "files": ["apps/web/docs/big.md"],
                    "allowed_transformations": ["git commit"],
                    "tests": ["t"],
                    "rollback": f"git-revert:{PATCH_UNIT_ID}",
                }
            ],
            max_files=1,
            max_lines=1,
        )
    )
    approval = parse_approval_decision(build_approval_decision())
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )
    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/big.md", b"line one\nline two\n"),),
            )
        ],
    )
    assert result.outcomes[0].status == JobStatus.FAILED
    assert result.outcomes[0].decision == "denied_diff_budget_exceeded"

    # --- assert: main repo is byte-identical — HEAD, working tree content,
    # and clean status all unchanged. ---
    head_after = _run_git(["rev-parse", "HEAD"], cwd=main_repo)
    tree_hash_after = _tree_content_hash(main_repo)
    status_after = _run_git(["status", "--porcelain"], cwd=main_repo)

    assert head_after == head_before
    assert tree_hash_after == tree_hash_before
    assert status_after == ""
    assert (main_repo / "apps" / "web" / "readme.md").read_text() == "original content\n"
    # the isolated worktree's own denied write never crossed over either.
    assert not (main_repo / "apps" / "web" / "docs").exists()
