"""Segment-level policy matchers used by `pre_tool_use` (and, for the
deployment-command matcher, `before_handoff`'s patch scan).

Every matcher here operates on ONE already-`command_normalize.normalize_command`-
normalized segment string (space-joined tokens) and returns either `None`
(no match) or a short human-readable match description (never a secret, a
matcher only ever quotes command verbs/flags it already knows are
policy-relevant, never full argument values that might carry a token/URL a
caller cares about redacting — see `redact.py` for the belt-and-braces
pattern-based pass callers still apply to any detail string built from a
match description).
"""

from __future__ import annotations
