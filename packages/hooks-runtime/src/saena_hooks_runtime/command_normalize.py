"""Command normalization layer for `pre_tool_use` (task instructions:

"Command normalization layer for pre_tool_use, defeating ALL these wrapper
forms (each gets corpus fixtures): shell wrapper `sh -c`/`bash -c`, env
prefix (incl. `env -S`), `git -c ...`, `git -C ...`, symlink targets, path
normalization (../ traversal, //, ./), encoded/quoted commands, pipelines,
subshells `$(...)` and `(...)`, multiline commands, indirect protected-path
write (tee/dd/redirect into protected path)."

`normalize_command(raw)` returns a tuple of normalized, whitespace-joined
command segments — one per top-level `&&`/`||`/`;`/`|`/newline-separated
piece of `raw`, with `sh -c`/`bash -c`/`env`/`$(...)`/`(...)` wrappers
unwrapped (recursively, depth-bounded) and `git` global options collapsed
so the policy layer (`rules.deploy_push`, `rules.unpinned_install`) always
sees the real subcommand token in position 1.

This is intentionally NOT a full POSIX shell parser — it is exactly enough
to defeat the documented bypass corpus (`tests/unit/hooks_runtime/corpus/`)
without unbounded complexity or unbounded recursion (`_MAX_RECURSE_DEPTH`
bounds `sh -c`/`env -S`/subshell unwrapping, matching the dev-repo hook
precedent's own "bound execution time... avoid unbounded recursion on
adversarial input" note, `.claude/hooks/scripts/lib/normalize-command.sh`).
Any segment shlex cannot tokenize (unbalanced quotes) normalizes to the
sentinel `"__UNPARSEABLE__"` rather than being silently dropped — callers
(`rules.deploy_push.matches_deploy_push_cms_dns` et al. treat an unknown
head token as non-matching, so a bare unparseable segment on its own is not
enough to deny; `pre_tool_use` itself is what fail-closes on an empty/
all-sentinel normalization result, see that module's docstring).

`has_pipe_to_interpreter(raw)` is a separate, RAW-TEXT-level check (not
segment-based) for the "curl|sh"/"encoded ... | sh" bypass family: `|`
already splits `raw` into segments during normalization, which destroys the
adjacency between "the thing producing bytes" and "the interpreter
consuming them" that this specific pattern depends on — same reasoning as
`.claude/hooks/scripts/deny-deploy-push.sh`'s own raw-text curl/wget check.
"""

from __future__ import annotations

import re
import shlex

UNPARSEABLE = "__UNPARSEABLE__"

_MAX_RECURSE_DEPTH = 3

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_SHELL_INTERPRETERS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})

# Leading git global options that take a following argument.
_GIT_OPTS_WITH_ARG = frozenset(
    {
        "-C",
        "-c",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--super-prefix",
        "--config-env",
        "--exec-path",
    }
)
_GIT_OPTS_WITH_ARG_PREFIX = tuple(f"{opt}=" for opt in _GIT_OPTS_WITH_ARG)
_GIT_BARE_OPTS = frozenset(
    {
        "--no-pager",
        "-p",
        "-P",
        "--paginate",
        "--bare",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
        "--no-replace-objects",
        "--no-optional-locks",
        "--no-lazy-fetch",
        "--no-advice",
    }
)

_PIPE_TO_INTERPRETER_RE = re.compile(
    r"\|\s*(?:sudo\s+)?(?:command\s+)?(sh|bash|zsh|dash|ksh|python3?|perl|ruby|node)\b"
)


def has_pipe_to_interpreter(raw: str) -> bool:
    """`True` if `raw` pipes its (or an intermediate stage's) output into a
    shell/scripting interpreter — `curl ... | sh`, `wget ... | bash`,
    `... | base64 -d | sh`, `... | python3`, etc. Raw-text check, run
    BEFORE segment splitting (see module docstring)."""
    return _PIPE_TO_INTERPRETER_RE.search(raw) is not None


def _extract_dollar_paren(text: str) -> tuple[str, list[str]]:
    """Peel every top-level `$(...)` out of `text`, respecting quotes and
    nested parens. Returns `(text_with_them_removed, [inner_texts])`."""
    inners: list[str] = []
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "$" and i + 1 < n and text[i + 1] == "(":
            j = i + 2
            depth = 1
            start = j
            in_quote: str | None = None
            while j < n and depth > 0:
                c = text[j]
                if in_quote:
                    if c == "\\" and in_quote == '"' and j + 1 < n:
                        j += 2
                        continue
                    if c == in_quote:
                        in_quote = None
                elif c in ("'", '"'):
                    in_quote = c
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                j += 1
            inners.append(text[start : j - 1] if depth == 0 else text[start:j])
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out), inners


def _split_top_level(text: str) -> list[str]:
    """Split on `&&`, `||`, `;`, `|`, newline at paren-depth 0, outside
    quotes. Parenthesized groups (subshells) are kept intact as one
    segment so they can be unwrapped and recursed into separately."""
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    depth = 0
    in_quote: str | None = None
    while i < n:
        c = text[i]
        if in_quote:
            buf.append(c)
            if c == "\\" and in_quote == '"' and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if c == in_quote:
                in_quote = None
            i += 1
            continue
        if c in ("'", '"'):
            in_quote = c
            buf.append(c)
            i += 1
            continue
        if c == "(":
            depth += 1
            buf.append(c)
            i += 1
            continue
        if c == ")":
            depth = max(0, depth - 1)
            buf.append(c)
            i += 1
            continue
        if depth == 0:
            two = text[i : i + 2]
            if two in ("&&", "||"):
                segments.append("".join(buf))
                buf = []
                i += 2
                continue
            if c in (";", "|", "\n"):
                segments.append("".join(buf))
                buf = []
                i += 1
                continue
        buf.append(c)
        i += 1
    segments.append("".join(buf))
    return segments


def _balanced(text: str) -> bool:
    depth = 0
    in_quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_quote:
            if c == "\\" and in_quote == '"' and i + 1 < n:
                i += 2
                continue
            if c == in_quote:
                in_quote = None
        elif c in ("'", '"'):
            in_quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0 and in_quote is None


def _strip_leading_env_assignments(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens) and _ENV_ASSIGN_RE.match(tokens[i]):
        i += 1
    return tokens[i:]


def _unwrap_env(tokens: list[str]) -> tuple[list[str], str | None]:
    """`tokens[0] == "env"`. Returns `(remaining_tokens, recurse_string)` —
    `recurse_string` is set (and `remaining_tokens` empty) for `env -S
    "..."`, which takes ONE argument that is itself a full command string
    to be (re-)split and normalized."""
    j = 1
    n = len(tokens)
    while j < n:
        t = tokens[j]
        if t == "-S":
            return [], (tokens[j + 1] if j + 1 < n else "")
        if t == "-i":
            j += 1
            continue
        if t == "-u":
            j += 2
            continue
        if _ENV_ASSIGN_RE.match(t):
            j += 1
            continue
        break
    return tokens[j:], None


def _strip_git_global_opts(tokens: list[str]) -> list[str]:
    out = [tokens[0]]
    i = 1
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t in _GIT_OPTS_WITH_ARG and i + 1 < n:
            i += 2
            continue
        if t.startswith(_GIT_OPTS_WITH_ARG_PREFIX):
            i += 1
            continue
        if t in _GIT_BARE_OPTS:
            i += 1
            continue
        break
    out.extend(tokens[i:])
    return out


def _normalize_one_segment(seg: str, depth: int) -> list[str]:
    stripped = seg.strip()
    if not stripped:
        return []

    # Standalone subshell wrapper: "(...)" spanning the whole segment.
    if stripped.startswith("(") and stripped.endswith(")") and _balanced(stripped[1:-1]):
        if depth >= _MAX_RECURSE_DEPTH:
            return [UNPARSEABLE]
        return list(normalize_command(stripped[1:-1], depth + 1))

    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        return [UNPARSEABLE]
    if not tokens:
        return []

    tokens = _strip_leading_env_assignments(tokens)
    if not tokens:
        return []

    if tokens[0] == "env":
        tokens, recurse_cmd = _unwrap_env(tokens)
        if recurse_cmd is not None:
            if depth >= _MAX_RECURSE_DEPTH:
                return [UNPARSEABLE]
            return list(normalize_command(recurse_cmd, depth + 1))
        if not tokens:
            return []

    if tokens[0] in _SHELL_INTERPRETERS and len(tokens) >= 3 and tokens[1] == "-c":
        if depth >= _MAX_RECURSE_DEPTH:
            return [UNPARSEABLE]
        inner_cmd = " ".join(tokens[2:]) if len(tokens) > 3 else tokens[2]
        return list(normalize_command(inner_cmd, depth + 1))

    if tokens[0] == "git":
        tokens = _strip_git_global_opts(tokens)

    return [" ".join(tokens)]


def normalize_command(raw: str, _depth: int = 0) -> tuple[str, ...]:
    """Normalize `raw` into a tuple of policy-matchable command segments."""
    if _depth > _MAX_RECURSE_DEPTH:
        return (UNPARSEABLE,)

    text, dollar_inners = _extract_dollar_paren(raw)

    segments_out: list[str] = []
    for inner in dollar_inners:
        segments_out.extend(normalize_command(inner, _depth + 1))

    for raw_seg in _split_top_level(text):
        segments_out.extend(_normalize_one_segment(raw_seg, _depth))

    return tuple(segments_out)


__all__ = ["UNPARSEABLE", "has_pipe_to_interpreter", "normalize_command"]
