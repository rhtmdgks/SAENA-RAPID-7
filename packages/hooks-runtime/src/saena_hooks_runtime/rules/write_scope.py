"""Indirect file-write target extraction — defeats the "indirect
protected-path write (tee/dd/redirect into protected path)" bypass
category (task instructions): a `Write`/`Edit` tool call is not the only
way an agent-runtime tool invocation can put bytes on disk. A `Bash` call
can too, via shell redirection (`>`, `>>`), `tee`, or `dd of=`.

`extract_write_targets` runs on ONE already-normalized command segment
(`command_normalize.normalize_command` output) and returns every path it
looks like that segment writes to — `pre_tool_use.deny_out_of_scope_file_write`
then scope-checks each one exactly like it would a `Write` tool's
`file_path`.
"""

from __future__ import annotations

_REDIRECT_TOKENS = frozenset({">", ">>"})


def extract_write_targets(segment: str) -> tuple[str, ...]:
    tokens = segment.split()
    targets: list[str] = []

    for i, tok in enumerate(tokens):
        if tok in _REDIRECT_TOKENS and i + 1 < len(tokens):
            targets.append(tokens[i + 1])
            continue
        if tok.startswith(">") and tok not in _REDIRECT_TOKENS and not tok.startswith((">&",)):
            candidate = tok.lstrip(">")
            if candidate:
                targets.append(candidate)

    if tokens and tokens[0] == "tee":
        targets.extend(t for t in tokens[1:] if not t.startswith("-"))

    if tokens and tokens[0] == "dd":
        targets.extend(t[len("of=") :] for t in tokens[1:] if t.startswith("of="))

    return tuple(targets)


__all__ = ["extract_write_targets"]
