"""Default-deny rule engine — OPA-style command/file/network/tool
authorization (README.md "OPA-style policy; command/file/network/tool
authorization; default-deny", `implementation-waves.md` W2A exit "policy-gate
fail-closed 데모" + "deny 우회 회귀(kubectl patch·git -c push 등) 통과").

Design: explicit, data-driven ALLOWLIST rules keyed by `(kind, action)`.
Anything that does not match a rule is DENY — there is no implicit-allow
fallthrough anywhere in `PolicyEngine.evaluate` (mirrors
`saena_domain.authz.rbac.authorize`'s default-deny shape, one layer up the
stack: command/file/network/tool authorization rather than role/permission).

Command deny-bypass regression (README + W2A exit, the security-critical
half of this module): a `kind="command"` request's `resource` is the raw
argv list (never a pre-joined string — a naive `str.startswith`/substring
check over a joined command line is exactly the bypass class this module
exists to close, e.g. `git -c foo=bar push` would not literal-match a
`"git push"` prefix check but MUST still be denied). `_classify_command`
parses that argv list structurally:

  1. Normalize argv[0] to its basename (`/usr/bin/kubectl` -> `kubectl`,
     absolute-path argv[0] tricks do not evade classification).
  2. Walk argv[1:], SKIPPING every recognized option token (`-x`, `--flag`,
     `--flag=value`, and `-c`/`-C`'s OWN following value token, e.g. the
     `foo=bar` in `git -c foo=bar push` or the `dir` in `git -C dir push`)
     to find the first non-option token — that token is the subcommand.
  3. A denied (binary, subcommand) pair anywhere this scan finds it is
     denied regardless of how many option tokens precede it, and regardless
     of whitespace form (argv is already a list — a caller that instead
     joins on tabs/multiple spaces before splitting has already lost the
     distinction this module relies on; `_split_command_string` below
     defends the CLI/tests boundary that must accept a raw string by
     splitting on ANY whitespace run, so a tab-separated command line
     collapses to the same argv list as a space-separated one).

`curl | sh` (and any `<fetch-tool> | <shell>` pipe) is a distinct shape: two
argv lists joined by a shell pipe. `evaluate_pipeline` (below) evaluates each
stage independently, but the PAIRING of "a network-fetch tool" feeding
directly into "a shell interpreter" is itself denied even if each stage,
evaluated alone, might otherwise look benign (matches README "network/tool
authorization").
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

RequestKind = Literal["command", "file", "network", "tool"]

# --- argv-level command classification ------------------------------------

# (binary basename, subcommand) pairs that are ALWAYS denied, regardless of
# leading option/flag tokens or their values (W2A exit regression list).
_DENIED_SUBCOMMANDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("kubectl", "patch"),
        ("kubectl", "edit"),
        ("kubectl", "delete"),
        ("kubectl", "replace"),
        ("git", "push"),
        ("helm", "upgrade"),
        ("helm", "install"),
        ("helm", "uninstall"),
        ("helm", "delete"),
    }
)

# Shell interpreters that make a preceding network-fetch tool's output into
# an executed pipe target (the `curl | sh` bypass class).
_SHELL_INTERPRETERS: frozenset[str] = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})
_FETCH_TOOLS: frozenset[str] = frozenset({"curl", "wget", "fetch"})

# Options that take a following value token which must be skipped, not
# mistaken for the subcommand — `git -c a=b push`, `git -C dir push`,
# `kubectl -n default patch`. Deliberately over-inclusive across the
# binaries this module cares about (kubectl/git/helm): a security deny-list
# must never let an unrecognized value-taking flag cause its OWN value to
# be misread as a benign "subcommand", masking the real subcommand that
# follows — `find_subcommand` below additionally scans the ENTIRE argv
# tail (not just the first non-option token) for this reason, so an
# incomplete entry in this table degrades to "scan a bit further", never to
# a missed detection the way a single-token lookahead would.
_VALUE_TAKING_SHORT_OPTIONS: frozenset[str] = frozenset(
    {"-c", "-C", "-n", "-namespace", "-f", "-o", "-l", "-context"}
)


def _basename(argv0: str) -> str:
    """Normalize argv[0] to its final path component — an absolute-path
    invocation (`/usr/bin/kubectl`) classifies identically to a bare one."""
    return PurePosixPath(argv0).name


def _is_option_token(token: str) -> bool:
    return token.startswith("-") and token != "-"


def find_subcommand(argv: list[str]) -> str | None:
    """Return the first non-option token after argv[0] under a
    best-effort option/value skip, or `None` if no such token exists.

    Deny-bypass safety note: this function is used by BOTH
    `classify_command`'s primary lookup key (first candidate) AND, via
    `iter_candidate_subcommands` below, as a fallback scan — a caller doing
    security classification should prefer `classify_command`, which checks
    every candidate this function's own scan produces, not just the first.
    """
    for candidate in iter_candidate_subcommands(argv):
        return candidate
    return None


def iter_candidate_subcommands(argv: list[str]) -> list[str]:
    """Every non-option token in `argv[1:]`, in order, treating a known
    value-taking short option's immediately-following token as consumed
    (not itself a candidate) — but WITHOUT stopping at the first candidate.

    Rationale (fixes a real gap: `kubectl -n default patch pod x` — a
    single "first non-option token" lookahead that does not recognize `-n`
    as value-taking would misread `default` as the subcommand and never see
    `patch` at all). Returning every remaining non-option token as a
    candidate — not just the first — means an unrecognized value-taking
    flag this module's table does not yet know about degrades to "one
    extra false candidate token", never to "the real subcommand is skipped
    entirely": `classify_command` checks every candidate against the deny
    table, so `patch` is still caught even if `default` is ALSO
    (harmlessly) offered as a candidate.
    """
    candidates: list[str] = []
    i = 1
    while i < len(argv):
        token = argv[i]
        if _is_option_token(token):
            if token in _VALUE_TAKING_SHORT_OPTIONS and i + 1 < len(argv):
                i += 2
                continue
            i += 1
            continue
        candidates.append(token)
        i += 1
    return candidates


@dataclass(frozen=True, slots=True)
class CommandClassification:
    binary: str
    subcommand: str | None
    denied: bool
    reason: str | None = None


def classify_command(argv: list[str]) -> CommandClassification:
    """Classify a single argv command list against the deny-bypass table.

    Checks EVERY candidate `iter_candidate_subcommands` produces (not just
    the first) against `_DENIED_SUBCOMMANDS` — a value-taking flag this
    module's table does not yet recognize must never cause the real
    subcommand later in argv to go unchecked (e.g. `kubectl -n default
    patch pod x`: `default` is one candidate, `patch` is another; both are
    checked, so `patch` is still caught even before `-n` was added to
    `_VALUE_TAKING_SHORT_OPTIONS`). `subcommand` on the returned
    `CommandClassification` reports the FIRST candidate for display/audit
    purposes only — the denial itself does not depend on which candidate
    matched being first.

    Never raises: an empty argv, or an argv with no candidate subcommand at
    all, is classified `denied=False` here — engine.py's default-deny
    ALLOWLIST evaluation (a rule must explicitly match to allow) is the
    actual fail-closed backstop for "unrecognized shape", not this
    classifier, which only encodes the SPECIFIC named regression cases.
    """
    if not argv:
        return CommandClassification(binary="", subcommand=None, denied=False)
    binary = _basename(argv[0])
    candidates = iter_candidate_subcommands(argv)
    for candidate in candidates:
        if (binary, candidate) in _DENIED_SUBCOMMANDS:
            return CommandClassification(
                binary=binary,
                subcommand=candidate,
                denied=True,
                reason=f"denied subcommand: {binary} {candidate}",
            )
    return CommandClassification(
        binary=binary, subcommand=candidates[0] if candidates else None, denied=False
    )


def split_command_string(command: str) -> list[str]:
    """Split a raw command-line string into argv, tolerant of tab- or
    multi-space-separated tokens (encoded/whitespace-trick regression case).

    `shlex.split` already splits on ANY run of POSIX whitespace (space, tab,
    newline) between tokens — a tab-separated `kubectl\\tpatch\\tpod` string
    yields the identical `["kubectl", "patch", "pod"]` argv as the
    space-separated form, so no separate normalization step is needed here;
    this wrapper exists to name that guarantee explicitly for callers/tests
    building a request from a raw string rather than a pre-split argv list.
    """
    return shlex.split(command)


def classify_pipeline(stages: list[list[str]]) -> CommandClassification:
    """Classify a shell pipeline (`stage_1 | stage_2 | ...`), each stage its
    own argv list, catching the `curl ... | sh` bypass shape in addition to
    each stage's own `classify_command` verdict.

    A pipeline is denied if ANY stage is denied on its own, OR if any
    adjacent (fetch-tool stage) -> (shell-interpreter stage) pairing exists
    — piping a network fetch straight into a shell interpreter is itself the
    denied shape (README "network/tool authorization"), independent of
    either stage's own binary/subcommand table membership.
    """
    for stage in stages:
        verdict = classify_command(stage)
        if verdict.denied:
            return verdict
    for earlier, later in zip(stages, stages[1:], strict=False):
        if not earlier or not later:
            continue
        earlier_bin = _basename(earlier[0])
        later_bin = _basename(later[0])
        if earlier_bin in _FETCH_TOOLS and later_bin in _SHELL_INTERPRETERS:
            return CommandClassification(
                binary=earlier_bin,
                subcommand=later_bin,
                denied=True,
                reason=f"denied pipeline shape: {earlier_bin} | {later_bin}",
            )
    return CommandClassification(binary="", subcommand=None, denied=False)


# --- request / decision shapes ---------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """A single command/file/network/tool authorization request.

    `resource` shape depends on `kind`:
      - command: `list[str]` argv (single stage) — a caller with a pipeline
        instead passes `pipeline: list[list[str]]` (see below), leaving
        `resource` as an empty list.
      - file/network/tool: an opaque resource identifier string wrapped in a
        single-element list (`[path]` / `[host]` / `[tool_name]`) — kept as
        `list[str]` uniformly so this dataclass has one field shape rather
        than a union per kind.
    """

    kind: RequestKind
    action: str
    resource: list[str]
    tenant_id: str
    pipeline: list[list[str]] | None = None


@dataclass(frozen=True, slots=True)
class AllowRule:
    """One explicit allowlist entry. `resource_prefix=None` matches any
    resource for this (kind, action); a non-None prefix requires the
    request's single-resource-string (resource[0]) to start with it —
    e.g. an allowed file-read rule scoped to a workspace root."""

    kind: RequestKind
    action: str
    resource_prefix: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    allow: bool
    reasons: tuple[str, ...]


class PolicyEngine:
    """Default-deny evaluator over a fixed, data-driven `AllowRule` set.

    Construction takes an explicit `rules` sequence — there is no global
    mutable rule registry, so two `PolicyEngine` instances never share
    state, and a test can trivially construct a broken-rule-store double
    (e.g. a rules accessor that raises) to exercise the fail-closed path at
    the service layer (`saena_policy_gate.service.authorize`, which wraps
    every `evaluate` call and converts ANY exception, including a broken
    rule store, into `GateUnavailableError`).
    """

    def __init__(self, rules: list[AllowRule]) -> None:
        self._rules = list(rules)

    @property
    def rules(self) -> tuple[AllowRule, ...]:
        return tuple(self._rules)

    def evaluate(self, request: AuthorizationRequest) -> Decision:
        """Evaluate `request` against the allowlist. Never raises for a
        well-formed `AuthorizationRequest` — callers that want fail-closed
        behavior on an UNEXPECTED exception (e.g. a corrupted rule store)
        wrap this call themselves (`saena_policy_gate.service`).
        """
        reasons: list[str] = []

        if request.kind == "command":
            if request.pipeline is not None:
                verdict = classify_pipeline(request.pipeline)
            else:
                verdict = classify_command(request.resource)
            if verdict.denied:
                reasons.append(verdict.reason or "denied command shape")
                return Decision(allow=False, reasons=tuple(reasons))

        resource_value = request.resource[0] if request.resource else None
        for rule in self._rules:
            if rule.kind != request.kind or rule.action != request.action:
                continue
            if rule.resource_prefix is None:
                return Decision(allow=True, reasons=("matched allow rule",))
            if resource_value is not None and resource_value.startswith(rule.resource_prefix):
                return Decision(allow=True, reasons=("matched allow rule",))

        reasons.append(
            f"no allow rule matched kind={request.kind!r} action={request.action!r} (default-deny)"
        )
        return Decision(allow=False, reasons=tuple(reasons))


__all__ = [
    "AllowRule",
    "AuthorizationRequest",
    "CommandClassification",
    "Decision",
    "PolicyEngine",
    "RequestKind",
    "classify_command",
    "classify_pipeline",
    "find_subcommand",
    "iter_candidate_subcommands",
    "split_command_string",
]
