"""Reference default-deny allowlist (README "least privilege").

This is a REFERENCE rule set only — a small, explicit, data-driven
allowlist proving the engine's shape end-to-end. A production rule bundle
(signed, versioned, rollback-able per k3s spec §8.4 "policy bundle defect")
is out of scope for this patch unit; `PolicyEngine` accepts any `AllowRule`
list, so a future patch unit can load a signed bundle from storage without
changing `engine.py`'s evaluation contract.

Command allow rules match `resource[0]` ONLY (coordinator SHOULD-FIX,
post-implementation review): `PolicyEngine.evaluate`'s allow-rule matching
compares `rule.resource_prefix` against `request.resource[0]` — for a
`kind="command"` request, `resource` is the argv list and `resource[0]` is
just the BINARY name, never the joined command line. The previous
`"git status"`/`"git diff"` entries were therefore dead code:
`"git".startswith("git status")` is always `False`, so those two rules
could never match anything. Fixed here by scoping command allow entries to
`resource_prefix="git"` (matches argv0 only, same granularity as
`"pytest"`) rather than pretending subcommand-level allow-scoping exists at
this layer — subcommand-level ALLOW granularity (as opposed to the deny
table's `(binary, subcommand)` precision) is explicitly OUT of scope for
this reference rule set; a production rule bundle wanting `git status`-only
(not blanket `git`) allow-scoping needs a richer `AllowRule` shape than
this unit ships (OPEN ITEM, flagged for a future patch unit).
"""

from __future__ import annotations

from saena_policy_gate.engine import AllowRule

DEFAULT_RULES: tuple[AllowRule, ...] = (
    AllowRule(kind="command", action="execute", resource_prefix="pytest"),
    AllowRule(kind="command", action="execute", resource_prefix="git"),
    AllowRule(kind="file", action="read", resource_prefix="/workspace/"),
    AllowRule(kind="network", action="connect", resource_prefix="internal://"),
    AllowRule(kind="tool", action="invoke", resource_prefix="linter"),
)


def default_engine_rules() -> list[AllowRule]:
    """A fresh mutable copy of `DEFAULT_RULES`, for `PolicyEngine(rules=...)`."""
    return list(DEFAULT_RULES)


__all__ = ["DEFAULT_RULES", "default_engine_rules"]
