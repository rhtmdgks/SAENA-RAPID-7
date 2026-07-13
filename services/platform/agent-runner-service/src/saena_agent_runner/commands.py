"""Command allowlist — DEFAULT DENY, with an absolute structural denylist.

Two independent layers, checked in this order for every command a patch
unit wants to run (`runner.py` calls `guard_command` before ever invoking
`CommandExecutor.run`):

1. `guard_absolute_deny` — an ABSOLUTE, unconditional denylist. Matches here
   raise `ForbiddenCommandError` regardless of what the contract's own
   `allowed_transformations` says — a (buggy or malicious) `ChangePlan`
   naming `git push`/`kubectl apply`/`helm upgrade`/a credential-file read
   in its own `allowed_transformations` still cannot make this layer pass.
   This is the CLAUDE.md operating principle 10 ("배포·push·merge 금지")
   and the mission's "ABSOLUTELY FORBIDDEN" list, enforced structurally.
2. `guard_allowlisted` — DEFAULT DENY against the executing patch unit's own
   `allowed_transformations` (Algorithm §5.2 "Execution Gate allowlisted
   operation set for this patch unit"). A command is permitted only if it
   equals, or is a whitespace-delimited PREFIX of, one of the patch unit's
   own `allowed_transformations` entries — anything else (including an
   entirely unrecognized command) is refused, never silently run.
"""

from __future__ import annotations

from collections.abc import Sequence

from saena_agent_runner.errors import CommandNotAllowlistedError, ForbiddenCommandError

# Absolute, structural denylist — matched as a whitespace-tokenized PREFIX
# of the requested command (e.g. `("git", "push")` matches
# `git push origin main`, not just the bare 2-token command). Never
# allowlistable by any contract; see module docstring.
_ABSOLUTE_DENY_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("git", "push"),
    ("kubectl",),
    ("helm",),
    ("docker", "push"),
    ("terraform", "apply"),
    ("terraform", "destroy"),
    ("aws",),
    ("gcloud",),
    ("az",),
    ("gh", "pr", "merge"),
    ("git", "remote"),
)

# Substrings matched case-insensitively against every argv TOKEN (not the
# whole command line) — catches credential-file reads regardless of which
# command is used to read them (`cat ~/.ssh/id_rsa`, `cp ~/.kube/config .`,
# `python -c "open('.env').read()"`, ...). Deliberately broad/over-blocking
# per this package's fail-closed posture (mission: "reading credentials"
# is an ABSOLUTELY FORBIDDEN case with a required negative test).
_ABSOLUTE_DENY_TOKEN_SUBSTRINGS: tuple[str, ...] = (
    ".ssh",
    "id_rsa",
    "id_ed25519",
    ".kube/config",
    "kubeconfig",
    ".env",
    "credentials",
    ".aws/credentials",
    ".netrc",
)


def guard_absolute_deny(argv: Sequence[str]) -> None:
    """Raise `ForbiddenCommandError` iff `argv` matches the absolute denylist."""
    tokens = tuple(argv)
    for deny_prefix in _ABSOLUTE_DENY_PREFIXES:
        if tokens[: len(deny_prefix)] == deny_prefix:
            raise ForbiddenCommandError(
                f"command {list(argv)!r} matches the absolute structural denylist "
                f"prefix {list(deny_prefix)!r} — never permitted regardless of any "
                "contract allowlist",
                context={"argv": list(argv), "denied_prefix": list(deny_prefix)},
            )
    for token in tokens:
        lowered = token.lower()
        for marker in _ABSOLUTE_DENY_TOKEN_SUBSTRINGS:
            if marker in lowered:
                raise ForbiddenCommandError(
                    f"command {list(argv)!r} references a credential-shaped path "
                    f"({marker!r}) — never permitted",
                    context={"argv": list(argv), "denied_marker": marker},
                )


def is_allowlisted(argv: Sequence[str], allowed_transformations: Sequence[str]) -> bool:
    """`True` iff `argv` equals, or extends, one of `allowed_transformations`.

    Each `allowed_transformations` entry is itself a whitespace-delimited
    command-prefix string (e.g. `"pytest -q"`, `"git commit"`) — `argv`
    passes if its own whitespace-joined form equals that string, or starts
    with that string followed by a space (so `allowed_transformations =
    ["pytest"]` permits `["pytest", "-q", "tests/"]`, but NOT
    `["pytest-cov"]`, a different binary that merely shares a prefix
    substring).
    """
    command_str = " ".join(argv)
    for allowed in allowed_transformations:
        if command_str == allowed or command_str.startswith(allowed + " "):
            return True
    return False


def guard_command(argv: Sequence[str], *, allowed_transformations: Sequence[str]) -> None:
    """Full command guard: absolute denylist first, then default-deny allowlist.

    Raises `ForbiddenCommandError` or `CommandNotAllowlistedError` (never
    returns anything — a caller only proceeds to actually run `argv` if this
    raises nothing).
    """
    guard_absolute_deny(argv)
    if not is_allowlisted(argv, allowed_transformations):
        raise CommandNotAllowlistedError(
            f"command {list(argv)!r} is not present in this patch unit's own "
            "allowed_transformations — default DENY",
            context={"argv": list(argv), "allowed_transformations": list(allowed_transformations)},
        )


__all__ = ["guard_absolute_deny", "guard_command", "is_allowlisted"]
