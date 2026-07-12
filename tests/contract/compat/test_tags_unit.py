"""Unit tests for harness.tags -- semver parsing/sort and repo-root
resolution. Real git-tag listing/`git show`/`git ls-tree` exercise is
covered indirectly by test_n1_compat.py's bootstrap-skip path (no tags
exist yet in this repo, tests/contract/README.md "Tag scheme" -- W1
bootstrap has zero `contracts/*` tags) and directly here against the
real (tag-less) repo, plus via a synthetic tmp git repo for the
tag-listing/sort/previous_tag/load_at_tag/list_fixture_paths_at_tag
functions that need real tags to exercise meaningfully.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from harness import tags as tags_mod


def test_parse_semver_basic() -> None:
    assert tags_mod.parse_semver("1.2.3").as_tuple() == (1, 2, 3)


def test_parse_semver_str() -> None:
    assert str(tags_mod.parse_semver("1.2.3")) == "1.2.3"


def test_parse_semver_rejects_prerelease() -> None:
    with pytest.raises(ValueError, match="not a valid full semver"):
        tags_mod.parse_semver("1.2.3-rc1")


def test_parse_semver_rejects_partial() -> None:
    with pytest.raises(ValueError, match="not a valid full semver"):
        tags_mod.parse_semver("1.2")


def test_repo_root_resolves_to_a_git_repo() -> None:
    root = tags_mod.repo_root()
    assert (root / ".git").exists()


def test_list_tags_for_contract_empty_in_real_repo() -> None:
    """W1 bootstrap: this repo currently has zero `contracts/*` tags."""
    tags = tags_mod.list_tags_for_contract("nonexistent-contract-xyz")
    assert tags == []


def test_previous_tag_none_when_no_tags_exist() -> None:
    result = tags_mod.previous_tag("nonexistent-contract-xyz", "1.0.0")
    assert result is None


# --------------------------------------------------------------------------
# Synthetic tmp git repo -- exercises tag listing/sort/previous_tag/
# load_at_tag/list_fixture_paths_at_tag against real tags without
# depending on this repo ever having any.
# --------------------------------------------------------------------------


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "synthetic-repo"
    repo.mkdir()

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "Test")

    schema_dir = repo / "packages" / "contracts" / "json-schema" / "domain" / "widget" / "v1"
    schema_dir.mkdir(parents=True)
    schema_path = schema_dir / "widget.schema.json"
    schema_path.write_text('{"type": "object", "required": ["a"]}', encoding="utf-8")

    fixtures_dir = repo / "tests" / "contract" / "fixtures" / "widget" / "valid"
    fixtures_dir.mkdir(parents=True)
    (fixtures_dir / "example-1.json").write_text('{"a": "x"}', encoding="utf-8")

    run("add", "-A")
    run("commit", "-q", "-m", "v1.0.0")
    run("tag", "contracts/widget/v1.0.0")

    schema_path.write_text('{"type": "object", "required": ["a", "b"]}', encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "v1.1.0")
    run("tag", "contracts/widget/v1.1.0")

    return repo


def test_list_tags_for_contract_sorted_semver(synthetic_repo: Path) -> None:
    tags = tags_mod.list_tags_for_contract("widget", repo=synthetic_repo)
    assert tags == ["contracts/widget/v1.0.0", "contracts/widget/v1.1.0"]


def test_previous_tag_resolves_immediately_prior(synthetic_repo: Path) -> None:
    result = tags_mod.previous_tag("widget", "1.1.0", repo=synthetic_repo)
    assert result == "contracts/widget/v1.0.0"


def test_previous_tag_none_for_first_version(synthetic_repo: Path) -> None:
    result = tags_mod.previous_tag("widget", "1.0.0", repo=synthetic_repo)
    assert result is None


def test_load_at_tag_reads_historical_content(synthetic_repo: Path) -> None:
    relpath = "packages/contracts/json-schema/domain/widget/v1/widget.schema.json"
    content = tags_mod.load_at_tag("contracts/widget/v1.0.0", relpath, repo=synthetic_repo)
    assert b'"required": ["a"]' in content


def test_load_at_tag_missing_path_raises(synthetic_repo: Path) -> None:
    with pytest.raises(RuntimeError, match="git show"):
        tags_mod.load_at_tag("contracts/widget/v1.0.0", "no/such/path.json", repo=synthetic_repo)


def test_list_fixture_paths_at_tag(synthetic_repo: Path) -> None:
    paths = tags_mod.list_fixture_paths_at_tag(
        "contracts/widget/v1.0.0", "widget", repo=synthetic_repo
    )
    assert paths == ["tests/contract/fixtures/widget/valid/example-1.json"]


def test_list_fixture_paths_at_tag_missing_dir_returns_empty(synthetic_repo: Path) -> None:
    paths = tags_mod.list_fixture_paths_at_tag(
        "contracts/widget/v1.0.0", "nonexistent-name", repo=synthetic_repo
    )
    assert paths == []


# --------------------------------------------------------------------------
# Git-failure error paths (non-git directory -> every git subcommand
# exits non-zero, exercising each function's RuntimeError branch).
# --------------------------------------------------------------------------


def test_repo_root_raises_when_not_a_git_repo(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not-a-git-repo"
    not_a_repo.mkdir()
    with pytest.raises(RuntimeError, match="git rev-parse"):
        tags_mod.repo_root(start=not_a_repo)


def test_list_tags_for_contract_raises_when_not_a_git_repo(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not-a-git-repo"
    not_a_repo.mkdir()
    with pytest.raises(RuntimeError, match="git tag -l"):
        tags_mod.list_tags_for_contract("widget", repo=not_a_repo)


def test_list_fixture_paths_at_tag_raises_when_not_a_git_repo(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not-a-git-repo"
    not_a_repo.mkdir()
    with pytest.raises(RuntimeError, match="git ls-tree"):
        tags_mod.list_fixture_paths_at_tag("contracts/widget/v1.0.0", "widget", repo=not_a_repo)


def test_list_tags_for_contract_raises_on_malformed_tag(tmp_path: Path) -> None:
    """A tag matching the git glob `contracts/{name}/v*` but NOT the strict
    `vX.Y.Z` semver pattern (e.g. a prerelease suffix) must raise a clear
    ValueError from the internal sort_key rather than sorting incorrectly.
    """
    repo = tmp_path / "malformed-tag-repo"
    repo.mkdir()

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "Test")
    (repo / "file.txt").write_text("x", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "init")
    run("tag", "contracts/widget/v1.0.0-rc1")

    with pytest.raises(ValueError, match="does not match contracts"):
        tags_mod.list_tags_for_contract("widget", repo=repo)
