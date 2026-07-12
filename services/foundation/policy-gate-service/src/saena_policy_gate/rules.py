"""Reference default-deny allowlist (README "least privilege").

This is a REFERENCE rule set only — a small, explicit, data-driven
allowlist proving the engine's shape end-to-end. A production rule bundle
(signed, versioned, rollback-able per k3s spec §8.4 "policy bundle defect")
is out of scope for this patch unit; `PolicyEngine` accepts any `AllowRule`
list, so a future patch unit can load a signed bundle from storage without
changing `engine.py`'s evaluation contract.
"""

from __future__ import annotations

from saena_policy_gate.engine import AllowRule

DEFAULT_RULES: tuple[AllowRule, ...] = (
    AllowRule(kind="command", action="execute", resource_prefix="pytest"),
    AllowRule(kind="command", action="execute", resource_prefix="git status"),
    AllowRule(kind="command", action="execute", resource_prefix="git diff"),
    AllowRule(kind="file", action="read", resource_prefix="/workspace/"),
    AllowRule(kind="network", action="connect", resource_prefix="internal://"),
    AllowRule(kind="tool", action="invoke", resource_prefix="linter"),
)


def default_engine_rules() -> list[AllowRule]:
    """A fresh mutable copy of `DEFAULT_RULES`, for `PolicyEngine(rules=...)`."""
    return list(DEFAULT_RULES)


__all__ = ["DEFAULT_RULES", "default_engine_rules"]
