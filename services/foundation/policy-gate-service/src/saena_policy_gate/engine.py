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
`"git push"` prefix check but MUST still be denied). `classify_command`
parses that argv list structurally, RECURSIVELY unwrapping every layer an
attacker can use to hide the real command from a naive argv[0] check
(critic MUST-FIX 1-4, post-implementation review):

  0. Strip leading `NAME=VALUE` environment-variable-assignment tokens
     (`^[A-Za-z_][A-Za-z0-9_]*=` — POSIX shell's own env-prefix grammar,
     e.g. `GIT_SSH=x git push`, `FOO=bar kubectl patch`) BEFORE basename
     classification (MUST-FIX 3) — these tokens are not argv[0] "options",
     they are how a shell spells "run this command with these env vars
     set", and the real binary is whatever token follows them.
  1. Normalize the (post env-strip) argv[0] to its basename, stripped of a
     trailing `.exe` (case-insensitively, MUST-FIX 4: `kubectl.exe` /
     `KUBECTL.EXE` both classify as `kubectl` — the binary-name comparison
     only is case-folded; subcommand tokens elsewhere in this module are
     NEVER lowercased, since `git -c a=b push` semantics do not extend to
     case-insensitive subcommands).
  2. If that basename is `env` AND carries an `-S`/`-S<glued>`/
     `--split-string=<glued>`/`--split-string <space-separated>` STRING
     argument (w2-24, Wave 2 critic follow-up — `env`'s split-string form
     parses its STRING argument shell-style, functionally identical to
     `sh -c "..."`, e.g. `env -S "kubectl patch ..."`, `env
     --split-string=kubectl patch`, `env --split-string "kubectl patch
     ..."` — GNU getopt_long accepts a long option's value either glued
     with `=` or as the following token, and a critic follow-up found the
     space-separated form was initially missed), `shlex.split` that string
     and RECURSE on the result as a fresh command — checked BEFORE step 2
     below so the generic wrapper-option skip never treats `-S`/
     `--split-string`'s OWN value as a harmless option-then-argv[0].
     `shlex.split` raising (malformed quoting) is FAIL-CLOSED, same
     doctrine as step 3's `-c` handling below.
  3. If that basename is a recognized EXEC WRAPPER (`env`, `sudo`, `xargs`,
     `nohup`, `timeout`, `nice`, `ionice`, `stdbuf`, `time`, `doas`,
     `setsid`, ... — MUST-FIX 1), skip the wrapper's own leading
     option/assignment tokens (`env` additionally consumes `NAME=VALUE`
     tokens and `-i`/`-u` per `env`'s own grammar) and RECURSE on the
     remaining argv as a fresh command — `env sudo kubectl patch` unwraps
     `env` then `sudo` then reaches `kubectl patch`.
  4. If that basename is a recognized SHELL INTERPRETER carrying a `-c`
     STRING argument (`sh -c "kubectl patch ..."`, MUST-FIX 2), `shlex.split`
     the string argument and RECURSE on the result as a fresh command;
     `shlex.split` raising (malformed quoting) is FAIL-CLOSED — treated as
     denied, never silently skipped, since an uninspectable embedded string
     is exactly the failure mode this recursion exists to close.
  5. Walk the (unwrapped) argv[1:], SKIPPING every recognized option token
     (`-x`, `--flag`, `--flag=value`, and known short options' OWN
     following value token, e.g. the `foo=bar` in `git -c foo=bar push` or
     the `dir` in `git -C dir push`) to collect every remaining non-option
     token as a subcommand CANDIDATE (not just the first — see
     `iter_candidate_subcommands`).
  6. A denied (binary, subcommand) pair anywhere this scan finds it is
     denied regardless of how many option tokens precede it, and regardless
     of whitespace form (argv is already a list — a caller that instead
     joins on tabs/multiple spaces before splitting has already lost the
     distinction this module relies on; `split_command_string` below
     defends the CLI/tests boundary that must accept a raw string by
     splitting on ANY whitespace run, so a tab-separated command line
     collapses to the same argv list as a space-separated one).

`curl | sh` (and any `<fetch-tool> | <shell>` pipe) is a distinct shape: two
argv lists joined by a shell pipe. `classify_pipeline` (below) evaluates each
stage independently, but the PAIRING of "a network-fetch tool" feeding
directly into "a shell interpreter" is itself denied even if each stage,
evaluated alone, might otherwise look benign (matches README "network/tool
authorization").
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

RequestKind = Literal["command", "file", "network", "tool"]

# --- argv-level command classification ------------------------------------

# (binary basename, subcommand) pairs that are ALWAYS denied, regardless of
# leading option/flag tokens or their values (W2A exit regression list).
# Binary names here are already lowercased — matched against a lowercased,
# `.exe`-stripped basename (MUST-FIX 4) — subcommand comparisons stay
# case-sensitive (never folded).
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
# an executed pipe target (the `curl | sh` bypass class), AND whose `-c`
# STRING argument this module recursively inspects (MUST-FIX 2).
_SHELL_INTERPRETERS: frozenset[str] = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})
_FETCH_TOOLS: frozenset[str] = frozenset({"curl", "wget", "fetch"})

# Exec-wrapper binaries: invoking one of these with a command as its own
# trailing argv is functionally identical to running that command directly
# — a deny-bypass class distinct from an option/flag trick (MUST-FIX 1).
# Deliberately broad; an unrecognized wrapper this table misses simply does
# not get unwrapped (falls through to ordinary argv[0] classification,
# never to a false ALLOW of a real wrapper already listed here).
_EXEC_WRAPPERS: frozenset[str] = frozenset(
    {
        "env",
        "sudo",
        "xargs",
        "nohup",
        "timeout",
        "nice",
        "ionice",
        "stdbuf",
        "time",
        "doas",
        "setsid",
        "chroot",
        "unbuffer",
    }
)

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

# Wrapper-specific option tokens that take a following value to skip (kept
# separate from `_VALUE_TAKING_SHORT_OPTIONS`, which is scoped to the
# underlying kubectl/git/helm commands, not the wrappers themselves) —
# `nice -n 10 kubectl patch`, `ionice -c 2 kubectl patch`.
_WRAPPER_VALUE_TAKING_OPTIONS: frozenset[str] = frozenset(
    {"-n", "-c", "-p", "-u", "-g", "--user", "--group"}
)

# Wrappers whose grammar requires a bare (non-flag) POSITIONAL argument
# BEFORE the wrapped command itself — `timeout DURATION cmd...`, `chroot
# NEWROOT cmd...`. Without this table, `_unwrap_exec_wrapper`'s first
# non-option token would be misread as "the wrapped command" (the duration/
# path itself), silently defeating the unwrap entirely (a real gap found in
# post-implementation review: `timeout 30 kubectl patch` was allowed).
_WRAPPERS_WITH_LEADING_POSITIONAL: frozenset[str] = frozenset({"timeout", "chroot"})

# `nice`'s own grammar accepts EITHER `-n ADJUSTMENT` (handled generically
# via `_WRAPPER_VALUE_TAKING_OPTIONS`) OR a bare numeric-looking leading
# positional (`nice 5 kubectl patch`, `nice -5 kubectl patch`, `nice +5
# kubectl patch`) with NO `-n` flag at all — a coordinator-review gap:
# without this, `_unwrap_exec_wrapper` reads `5` itself as "the wrapped
# command" and never reaches `kubectl`. Checked by a dedicated numeric-token
# predicate rather than a generic "consumes N positionals" table, since
# whether the leading token is consumed here depends on ITS OWN shape (only
# a numeric-looking token is nice's adjustment; a non-numeric token is
# already the real command's own argv[0]).
_NICE_NUMERIC_PATTERN = re.compile(r"^[+-]?[0-9]+$")


def _is_nice_numeric_positional(token: str) -> bool:
    return bool(_NICE_NUMERIC_PATTERN.match(token))


# `su` is not a generic exec-wrapper (it changes user identity, and its own
# `-c` grammar carries an embedded command STRING like a shell, not a
# trailing argv like `env`/`sudo`/`timeout`) — `su root -c "kubectl patch
# ..."` / `su -c "kubectl patch ..." root` are both denied via the SAME
# shell `-c`-string recursion `_unwrap_shell_dash_c` already applies to
# sh/bash/zsh/..., by including `su` in this set (checked ONLY by that
# function, never by `_unwrap_exec_wrapper`'s trailing-argv model).
_SU_LIKE: frozenset[str] = frozenset({"su"})

_ENV_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _is_env_assignment(token: str) -> bool:
    """`NAME=VALUE` shell-prefix token (MUST-FIX 3), e.g. `GIT_SSH=x` in
    `GIT_SSH=x git push` — POSIX identifier on the left of `=`, distinct
    from an option token (never starts with `-`)."""
    return bool(_ENV_ASSIGNMENT_PATTERN.match(token))


# w2-24 (Wave 2 critic follow-up — "env -S / --split-string default-deny"
# residual gap): GNU coreutils `env`'s `-S`/`--split-string` option takes a
# single STRING argument that `env` itself parses shell-style (quote-aware
# word splitting — functionally identical to `sh -c "..."`'s own embedded
# command string, MUST-FIX 2's shape, not a plain wrapper trailing-argv).
# `_unwrap_exec_wrapper`'s generic option-skip loop would otherwise treat
# `-S`/`--split-string` as an ordinary (non-value-taking) option and skip
# past it, leaving the STRING argument to be misread as the wrapped
# command's own argv[0] (one opaque token, e.g. `"kubectl patch pod x"` as a
# literal binary name) — never unwrapped, never classified against the deny
# table. This function recognizes all FOUR of `env`'s accepted spellings —
# `-S STRING` (separate token), `-SSTRING` (glued short form),
# `--split-string=STRING` (glued long form), and `--split-string STRING`
# (space-separated long form — GNU getopt_long accepts a long option's value
# either glued with `=` or as the following token; a critic follow-up found
# this fourth spelling was NOT recognized in the original patch, falling
# through to `_unwrap_exec_wrapper`'s generic skip-and-misread-argv[0] path,
# a live bypass for e.g. `env --split-string "kubectl patch pod x"`) — and
# returns the STRING argument for `shlex.split`-based recursive
# classification, exactly like `_unwrap_shell_dash_c` already does for `sh
# -c`.
_ENV_SPLIT_STRING_LONG_PREFIX = "--split-string="
_ENV_SPLIT_STRING_LONG_FLAG = "--split-string"


def _find_env_split_string_arg(argv: list[str]) -> str | None:
    """Return `env -S`/`-S<glued>`/`--split-string=<glued>`/
    `--split-string <space-separated>`'s STRING argument from `argv[1:]`
    (the tokens after `env` itself), or `None` if no such option is present
    (including a bare `-S`/`--split-string` with no following token at all
    — nothing to unwrap, falls through to ordinary classification, same as
    `env -S` alone documented in `_classify_argv`). Scans the ENTIRE tail
    (not just the first token) — same defense-in-depth rationale as
    `iter_candidate_subcommands` (an unrelated leading option before `-S`/
    `--split-string` must not hide it)."""
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "-S" or token == _ENV_SPLIT_STRING_LONG_FLAG:
            if i + 1 < len(argv):
                return argv[i + 1]
            return None
        if token.startswith("-S") and token != "-S":
            # Glued short form: `-Skubectl patch` -> `kubectl patch`.
            return token[len("-S") :]
        if token.startswith(_ENV_SPLIT_STRING_LONG_PREFIX):
            return token[len(_ENV_SPLIT_STRING_LONG_PREFIX) :]
        i += 1
    return None


def _basename(argv0: str) -> str:
    """Normalize argv[0] to its final path component, `.exe`-suffix
    stripped case-insensitively (MUST-FIX 4: `kubectl.exe`/`KUBECTL.EXE`
    both normalize to `kubectl`) — an absolute-path invocation
    (`/usr/bin/kubectl`) classifies identically to a bare one. Windows-style
    backslash path separators (`C:\\tools\\kubectl.exe`) are normalized to
    `/` BEFORE taking the final path component — `PurePosixPath` alone does
    not treat `\\` as a separator, so a bare backslash-path argv[0] would
    otherwise classify as one opaque token (a real gap found in
    coordinator-review regression testing) rather than being reduced to
    `kubectl`. The RETURNED value is lowercased for binary-name comparison
    purposes only; callers must never use this function's output as a
    subcommand or display value where case matters."""
    normalized = argv0.replace("\\", "/")
    name = PurePosixPath(normalized).name
    lowered = name.lower()
    if lowered.endswith(".exe"):
        lowered = lowered[: -len(".exe")]
    return lowered


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


# Recursion depth cap for unwrap chains (env sudo timeout ... kubectl patch)
# — generous enough for any realistic wrapper stack, but bounded so a
# maliciously/accidentally self-referential argv (e.g. `env env env env
# ...`) cannot recurse unboundedly. Exhausting the budget is FAIL-CLOSED
# (denied), never fail-open (MUST-FIX 5 doctrine extended to this internal
# recursion, not just the service-layer choke point).
_MAX_UNWRAP_DEPTH = 12


def _strip_env_assignments(argv: list[str]) -> list[str]:
    """Strip leading `NAME=VALUE` tokens from `argv` (MUST-FIX 3) — the
    POSIX-shell env-prefix form `GIT_SSH=x git push` is, semantically, "run
    `git push` with `GIT_SSH=x` set"; this function returns `argv` with
    every such LEADING assignment token removed so the real command
    (`["git", "push"]`) is what basename/wrapper/shell classification sees.
    Stops at the first non-assignment token — an assignment appearing AFTER
    the real command starts is just a plain argument to that command, not a
    prefix (e.g. `git commit -m "FOO=bar"` must not strip anything)."""
    i = 0
    while i < len(argv) and _is_env_assignment(argv[i]):
        i += 1
    return argv[i:]


def _unwrap_exec_wrapper(argv: list[str], binary: str) -> list[str] | None:
    """If `binary` (the already-normalized basename of `argv[0]`) is a
    recognized exec wrapper (MUST-FIX 1), return the wrapped command's own
    argv (skipping the wrapper's leading option/assignment tokens) — or
    `None` if `binary` is not a wrapper, or the wrapper carries no
    trailing command at all (e.g. bare `sudo` with no argument).

    `env`'s own grammar additionally accepts `NAME=VALUE` assignment
    tokens and `-i`/`-u USER` before the wrapped command (`env FOO=bar
    kubectl patch`, `env -i kubectl patch`, `env -u PATH kubectl patch`) —
    handled via `_strip_env_assignments` plus this function's own
    wrapper-option skip loop. `timeout`/`chroot`
    (`_WRAPPERS_WITH_LEADING_POSITIONAL`) additionally require skipping ONE
    bare positional argument (duration/newroot) BEFORE the wrapped command
    begins — `timeout 30 kubectl patch` must unwrap to `["kubectl",
    "patch", ...]`, not misread `30` itself as the wrapped command. `nice`
    additionally accepts a BARE NUMERIC leading positional in place of `-n
    ADJUSTMENT` (`nice 5 kubectl patch`, `nice -5 kubectl patch`) — consumed
    via `_is_nice_numeric_positional` rather than the generic
    `_WRAPPERS_WITH_LEADING_POSITIONAL` table, since whether it is consumed
    depends on the token's OWN numeric shape, not merely on `binary`.
    """
    if binary not in _EXEC_WRAPPERS:
        return None
    i = 1
    pending_positional = binary in _WRAPPERS_WITH_LEADING_POSITIONAL
    while i < len(argv):
        token = argv[i]
        if binary == "env" and _is_env_assignment(token):
            i += 1
            continue
        if binary == "nice" and _is_nice_numeric_positional(token):
            # `nice`'s bare-numeric adjustment form — NOT the wrapped
            # command, regardless of position (nice accepts at most one).
            i += 1
            continue
        if _is_option_token(token):
            if token in _WRAPPER_VALUE_TAKING_OPTIONS and i + 1 < len(argv):
                i += 2
                continue
            i += 1
            continue
        if pending_positional:
            # Consume the wrapper's own required bare positional argument
            # (e.g. timeout's DURATION) — it is NOT the wrapped command.
            pending_positional = False
            i += 1
            continue
        # First non-option, non-assignment, non-required-positional token:
        # the wrapped command itself begins here.
        return argv[i:]
    return None


def _unwrap_shell_dash_c(argv: list[str], binary: str) -> list[str] | None:
    """If `binary` is a recognized shell interpreter (MUST-FIX 2) OR `su`
    (coordinator-review addendum: `su`'s own `-c` grammar carries an
    embedded command STRING exactly like a shell's `-c`, not a trailing
    argv like `env`/`sudo`/`timeout`) invoked with a `-c` STRING argument
    (`sh -c "kubectl patch ..."`, `su root -c "kubectl patch ..."`, `su -c
    "kubectl patch ..." root`), `shlex.split` that string and return the
    resulting argv for recursive classification. The `-c` scan below finds
    `-c` at ANY position in `argv[1:]` (not just immediately after argv[0])
    so `su`'s `-c` before-or-after-the-username flexibility is covered
    without a separate code path.

    Returns `None` when `binary` is neither a shell nor `su`, or carries no
    `-c` string at all (nothing to unwrap — fall through to ordinary
    classification). A `shlex.split` failure is signaled by propagating
    `ValueError` (shlex's own exception for malformed quoting) to the
    caller, `_classify_argv`, which treats it as DENIED — an uninspectable
    embedded string must never be treated as benign (fail-closed, not
    fail-open).
    """
    if binary not in _SHELL_INTERPRETERS and binary not in _SU_LIKE:
        return None
    for i in range(1, len(argv) - 1):
        if argv[i] == "-c":
            return shlex.split(argv[i + 1])
    return None


def _classify_argv(argv: list[str], *, depth: int = 0) -> CommandClassification:
    """Recursively classify `argv`, unwrapping env-prefixes, exec wrappers,
    and `shell -c "..."` embedded strings before applying the
    (binary, subcommand) deny table — the actual implementation behind
    `classify_command`.

    Fail-closed on: `_MAX_UNWRAP_DEPTH` exhaustion, and a `shlex.split`
    failure while unwrapping a shell `-c` string (malformed/uninspectable
    embedded command).
    """
    if not argv:
        return CommandClassification(binary="", subcommand=None, denied=False)

    if depth >= _MAX_UNWRAP_DEPTH:
        return CommandClassification(
            binary=_basename(argv[0]) if argv else "",
            subcommand=None,
            denied=True,
            reason="denied: exec-wrapper/unwrap recursion depth exceeded (fail-closed)",
        )

    unwrapped = _strip_env_assignments(argv)
    if not unwrapped:
        # Argv was ENTIRELY env assignments with no command at all — not a
        # runnable command shape; nothing to deny here (the deny table is
        # about denying real commands, not malformed/empty ones).
        return CommandClassification(binary="", subcommand=None, denied=False)

    binary = _basename(unwrapped[0])

    if binary == "env":
        split_string = _find_env_split_string_arg(unwrapped)
        if split_string is not None:
            # w2-24: `env -S`/`-S<glued>`/`--split-string=<glued>`/
            # `--split-string <space-separated>` parses its STRING argument
            # shell-style, exactly like `sh -c "..."` — must be unwrapped and
            # recursively classified BEFORE the generic exec-wrapper
            # option-skip loop below ever sees `-S`/`--split-string` (which
            # it would otherwise treat as a harmless, skippable option token
            # and misread the STRING itself as the wrapped command's argv[0]
            # — the exact space-separated-long-form bypass a critic
            # follow-up found in the original patch).
            try:
                split_argv = shlex.split(split_string)
            except ValueError:
                # Uninspectable embedded string — fail-closed, same doctrine
                # as _unwrap_shell_dash_c's own shlex.split failure below.
                return CommandClassification(
                    binary=binary,
                    subcommand="-S",
                    denied=True,
                    reason="denied: unparseable env -S/--split-string argument (fail-closed)",
                )
            return _classify_argv(split_argv, depth=depth + 1)

    wrapped_argv = _unwrap_exec_wrapper(unwrapped, binary)
    if wrapped_argv is not None:
        return _classify_argv(wrapped_argv, depth=depth + 1)

    try:
        shell_argv = _unwrap_shell_dash_c(unwrapped, binary)
    except ValueError:
        # shlex.split failed on the -c string — uninspectable, fail-closed.
        return CommandClassification(
            binary=binary,
            subcommand="-c",
            denied=True,
            reason=f"denied: unparseable {binary} -c argument (fail-closed)",
        )
    if shell_argv is not None:
        return _classify_argv(shell_argv, depth=depth + 1)

    candidates = iter_candidate_subcommands(unwrapped)
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


def classify_command(argv: list[str]) -> CommandClassification:
    """Classify a single argv command list against the deny-bypass table.

    Recursively unwraps (in order, at every nesting level): leading
    `NAME=VALUE` env-prefix tokens (MUST-FIX 3), `env -S`/`--split-string`
    embedded command strings (w2-24), exec wrappers like `env`/`sudo`/
    `xargs`/... (MUST-FIX 1), and `shell -c "..."` embedded command strings
    (MUST-FIX 2) — so `env sudo kubectl patch`, `GIT_SSH=x git push`,
    `sh -c "kubectl patch pod x"`, and `env -S "kubectl patch pod x"` are all
    classified against the exact same `(binary, subcommand)` deny table as a
    bare `kubectl patch` invocation. `argv[0]`'s basename is additionally
    normalized case-insensitively with a trailing `.exe` stripped
    (MUST-FIX 4) — `kubectl.exe`/`KUBECTL.EXE` both classify as `kubectl`;
    subcommand tokens themselves are never case-folded.

    Checks EVERY candidate `iter_candidate_subcommands` produces at the
    FINAL unwrapped level (not just the first) against `_DENIED_SUBCOMMANDS`
    — a value-taking flag this module's table does not yet recognize must
    never cause the real subcommand later in argv to go unchecked (e.g.
    `kubectl -n default patch pod x`: `default` is one candidate, `patch`
    is another; both are checked). `subcommand` on the returned
    `CommandClassification` reports the FIRST candidate for display/audit
    purposes only — the denial itself does not depend on which candidate
    matched being first.

    Never raises: an empty argv, an argv with no candidate subcommand, or a
    `shlex.split` failure while unwrapping a shell `-c` string OR an
    `env -S`/`--split-string` argument is classified here (the last two
    cases as `denied=True`, fail-closed — see `_classify_argv`) —
    engine.py's default-deny ALLOWLIST evaluation (a rule must explicitly
    match to allow) is the actual fail-closed backstop for any OTHER
    unrecognized shape, not this classifier, which only encodes the
    SPECIFIC named regression cases plus their wrapper/shell/env-prefix/
    exe-suffix/split-string variants.
    """
    return _classify_argv(argv)


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
