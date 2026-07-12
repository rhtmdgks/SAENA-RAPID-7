"""Git-tag discovery, semver sort, and tag-scoped file reads.

Tag scheme: `contracts/{name}/vX.Y.Z` (ADR-0011 registry section,
tests/contract/README.md "Tag scheme" :145-152). The harness resolves
"the previous version" for a given contract by listing tags matching
`contracts/{name}/v*`, sorting by semver, and picking the tag immediately
prior to the version currently under test -- not wall-clock recency, not
`git log` traversal on main.

All git invocations here are `subprocess.run(["git", ...], cwd=repo_root)`
-- plain positional subcommands, no global flags (`-C`, `-c`, `--no-pager`)
-- consistent with the w1-00 hook's normalize-command precision fix, and
they run inside pytest subprocess contexts, which are not hook-gated.
`repo_root` is resolved once via `git rev-parse --show-toplevel` from this
file's own location rather than assumed, so the module works correctly
whether invoked from the worktree root or a subdirectory.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_SEMVER_TAG_RE = re.compile(
    r"^contracts/(?P<name>[a-z0-9-]+)/v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$"
)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def repo_root(start: Path | None = None) -> Path:
    """Resolve the repo root via `git rev-parse --show-toplevel`.

    `start` defaults to this file's own directory so the result is stable
    regardless of the caller's current working directory.
    """
    cwd = start if start is not None else Path(__file__).resolve().parent
    result = _run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    if result.returncode != 0:
        msg = f"git rev-parse --show-toplevel failed: {result.stderr}"
        raise RuntimeError(msg)
    return Path(result.stdout.strip())


@dataclass(frozen=True)
class SemverTuple:
    major: int
    minor: int
    patch: int

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_semver(version: str) -> SemverTuple:
    """Parse an "X.Y.Z" string (stdlib re, no external semver dependency)."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        msg = f"not a valid full semver X.Y.Z: {version!r}"
        raise ValueError(msg)
    major, minor, patch = (int(part) for part in match.groups())
    return SemverTuple(major=major, minor=minor, patch=patch)


def list_tags_for_contract(name: str, repo: Path | None = None) -> list[str]:
    """List all git tags matching `contracts/{name}/v*`, semver-sorted ascending."""
    root = repo if repo is not None else repo_root()
    result = _run_git(["tag", "-l", f"contracts/{name}/v*"], cwd=root)
    if result.returncode != 0:
        msg = f"git tag -l failed: {result.stderr}"
        raise RuntimeError(msg)
    tags = [line for line in result.stdout.splitlines() if line.strip()]

    def sort_key(tag: str) -> tuple[int, int, int]:
        match = _SEMVER_TAG_RE.match(tag)
        if match is None:
            msg = f"tag does not match contracts/{{name}}/vX.Y.Z scheme: {tag!r}"
            raise ValueError(msg)
        return parse_semver(match.group("version")).as_tuple()

    return sorted(tags, key=sort_key)


def previous_tag(name: str, current_full_version: str, repo: Path | None = None) -> str | None:
    """Return the tag immediately prior to `current_full_version` for `name`,
    or None if there is no earlier tag (first release -- N-1 leg is
    vacuously green, tests/contract/README.md "Compatibility harness").
    """
    root = repo if repo is not None else repo_root()
    tags = list_tags_for_contract(name, repo=root)
    current = parse_semver(current_full_version).as_tuple()

    older = [
        tag
        for tag in tags
        if parse_semver(_SEMVER_TAG_RE.match(tag).group("version")).as_tuple() < current  # type: ignore[union-attr]
    ]
    if not older:
        return None
    return older[-1]


def load_at_tag(tag: str, relpath: str, repo: Path | None = None) -> bytes:
    """Return the bytes of `relpath` (repo-root-relative) as it existed at `tag`.

    Uses `git show <tag>:<relpath>` -- read-only plumbing, safe under the
    w1-00 hook allowlist and not itself subject to hook gating since it
    runs inside a pytest subprocess.
    """
    root = repo if repo is not None else repo_root()
    result = _run_git(["show", f"{tag}:{relpath}"], cwd=root)
    if result.returncode != 0:
        msg = f"git show {tag}:{relpath} failed: {result.stderr}"
        raise RuntimeError(msg)
    return result.stdout.encode("utf-8")


def list_fixture_paths_at_tag(tag: str, name: str, repo: Path | None = None) -> list[str]:
    """List repo-root-relative paths of valid fixtures for `name` at `tag`.

    Uses `git ls-tree -r --name-only <tag> -- tests/contract/fixtures/<name>/valid`.
    Returns an empty list if the path did not exist at that tag (e.g. the
    contract had no fixtures directory yet) rather than raising, since an
    empty valid-fixture set at a historical tag is a legitimate (if
    unusual) state, not a harness error.
    """
    root = repo if repo is not None else repo_root()
    fixtures_relpath = f"tests/contract/fixtures/{name}/valid"
    result = _run_git(
        ["ls-tree", "-r", "--name-only", tag, "--", fixtures_relpath],
        cwd=root,
    )
    if result.returncode != 0:
        msg = f"git ls-tree failed: {result.stderr}"
        raise RuntimeError(msg)
    return [line for line in result.stdout.splitlines() if line.strip()]
