"""`deny_unpinned_dependency_install` matcher.

Heuristic, package-manager-specific "does this install command name a
package without an exact version pin" check. A bare install-from-lockfile
invocation (`npm install` / `npm ci` / `pip install -r requirements.txt`)
is allowed — pinning lives in the lockfile/requirements file in that case,
not on the command line.

Not exhaustive (documented here rather than silently — extending the
package-manager table is expected future work, see this package's README
"Known limitations"): covers pip/pip3, `uv add`/`uv pip install`, npm,
yarn, pnpm, gem, and `go install ...@latest`.
"""

from __future__ import annotations

_PIP_LIKE = frozenset({"pip", "pip3"})
_NPM_LIKE_ADD_SUBCOMMAND = {"npm": "install", "yarn": "add", "pnpm": "add"}


def _has_pep440_pin(pkg: str) -> bool:
    if pkg.startswith(("git+", "hg+", "svn+", "bzr+")):
        return "@" in pkg
    if pkg.startswith(("http://", "https://", "./", "/", "-")):
        return True  # direct URL/local path/flag — not a bare unpinned package name
    return "==" in pkg


def _has_npm_pin(pkg: str) -> bool:
    if pkg.startswith("-"):
        return True
    # scoped packages ("@scope/name") carry a leading "@" that is not a
    # version marker — only an "@" AFTER the first character counts.
    body = pkg[1:] if pkg.startswith("@") else pkg
    return "@" in body


def _pip_family_match(head: str, tokens: list[str]) -> str | None:
    if head == "uv" and len(tokens) >= 2 and tokens[1] == "add":
        pkgs = [t for t in tokens[2:] if not t.startswith("-")]
        if pkgs and any(not _has_pep440_pin(p) for p in pkgs):
            return "uv add without version pin"
        return None
    if head == "uv" and len(tokens) >= 3 and tokens[1] == "pip" and tokens[2] == "install":
        rest = tokens[3:]
        if "-r" in rest or "--requirement" in rest:
            return None
        pkgs = [t for t in rest if not t.startswith("-")]
        if pkgs and any(not _has_pep440_pin(p) for p in pkgs):
            return "uv pip install without version pin"
        return None
    if head in _PIP_LIKE and len(tokens) >= 2 and tokens[1] == "install":
        rest = tokens[2:]
        if "-r" in rest or "--requirement" in rest:
            return None
        pkgs = [t for t in rest if not t.startswith("-")]
        if pkgs and any(not _has_pep440_pin(p) for p in pkgs):
            return f"{head} install without version pin"
        return None
    return None


def _npm_family_match(head: str, tokens: list[str]) -> str | None:
    add_subcommand = _NPM_LIKE_ADD_SUBCOMMAND.get(head)
    if add_subcommand is None or len(tokens) < 2 or tokens[1] != add_subcommand:
        return None
    pkgs = [t for t in tokens[2:] if not t.startswith("-")]
    if not pkgs:
        return None  # bare `npm install` / lockfile-driven — allowed
    if any(not _has_npm_pin(p) for p in pkgs):
        return f"{head} {add_subcommand} without version pin"
    return None


def _gem_match(head: str, tokens: list[str]) -> str | None:
    if head != "gem" or len(tokens) < 2 or tokens[1] != "install":
        return None
    pkgs = [t for t in tokens[2:] if not t.startswith("-")]
    has_version_flag = "-v" in tokens or "--version" in tokens
    if pkgs and not has_version_flag:
        return "gem install without version pin"
    return None


def _go_match(head: str, tokens: list[str]) -> str | None:
    if head != "go" or len(tokens) < 2 or tokens[1] != "install":
        return None
    for t in tokens[2:]:
        if t.endswith("@latest") or ("@" not in t and not t.startswith("-")):
            return "go install without a pinned @version"
    return None


def matches_unpinned_install(segment: str) -> str | None:
    """Return a short match description, or `None` if `segment` is not an
    unpinned dependency install."""
    tokens = segment.split()
    if not tokens:
        return None
    head = tokens[0]
    for matcher in (_pip_family_match, _npm_family_match, _gem_match, _go_match):
        result = matcher(head, tokens)
        if result is not None:
            return result
    return None


__all__ = ["matches_unpinned_install"]
