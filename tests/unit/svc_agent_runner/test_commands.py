"""Command allowlist — default DENY + absolute structural denylist."""

from __future__ import annotations

import pytest
from saena_agent_runner.commands import guard_absolute_deny, guard_command, is_allowlisted
from saena_agent_runner.errors import CommandNotAllowlistedError, ForbiddenCommandError


def test_allowlisted_command_permitted() -> None:
    guard_command(["git", "commit", "-m", "x"], allowed_transformations=["git commit"])


def test_command_not_in_allowlist_denied_by_default() -> None:
    """NEGATIVE: default DENY — an unrecognized command not present in the
    patch unit's own allowed_transformations is refused."""
    with pytest.raises(CommandNotAllowlistedError):
        guard_command(["rm", "-rf", "/"], allowed_transformations=["git commit"])


def test_similar_prefix_substring_not_allowlisted() -> None:
    """`pytest-cov` must NOT be permitted by an `allowed_transformations`
    entry of `pytest` (distinct binary, not a real prefix match)."""
    assert not is_allowlisted(["pytest-cov"], ["pytest"])


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "push", "origin", "main"],
        ["git", "push"],
        ["kubectl", "apply", "-f", "deploy.yaml"],
        ["kubectl", "get", "pods"],
        ["helm", "upgrade", "saena-forge", "."],
        ["helm", "install", "x", "y"],
        ["docker", "push", "registry/image:tag"],
        ["terraform", "apply"],
        ["gh", "pr", "merge", "1"],
        ["git", "remote", "add", "origin", "https://evil"],
    ],
)
def test_absolute_deny_commands_never_allowlistable(argv: list[str]) -> None:
    """NEGATIVE (mission ABSOLUTELY FORBIDDEN list): deploy/push commands
    are refused even if the calling patch unit's own contract names them
    in `allowed_transformations` — the absolute denylist wins."""
    with pytest.raises(ForbiddenCommandError):
        guard_absolute_deny(argv)
    with pytest.raises(ForbiddenCommandError):
        # Even an (erroneous/malicious) contract that names the exact
        # command in its own allowlist cannot make this pass.
        guard_command(argv, allowed_transformations=[" ".join(argv)])


@pytest.mark.parametrize(
    "argv",
    [
        ["cat", "~/.ssh/id_rsa"],
        ["cp", "~/.kube/config", "/tmp/out"],
        ["cat", ".env"],
        ["cat", "credentials.json"],
    ],
)
def test_credential_reading_commands_denied(argv: list[str]) -> None:
    """NEGATIVE (mission ABSOLUTELY FORBIDDEN: 'reading credentials')."""
    with pytest.raises(ForbiddenCommandError):
        guard_command(argv, allowed_transformations=[" ".join(argv)])
