"""Allowlist-first redaction engine (ADR-0016), driven by the W0 registry.

Implements exactly the rules recorded in
`packages/observability/registry/redaction-rules.yaml`:

1. ``export_policy: allowlist`` — an attribute is export-eligible only if
   its name is a registered ``saena.*`` entry in ``attributes.json``.
   Non-``saena.*`` keys are treated as not-allowlisted by this engine (the
   OTel semantic-conventions passthrough decision belongs to the W2C
   exporter, out of this package's scope) — unregistered keys are dropped.
2. Denylist regex patterns (``R-SECRET-*``, ``R-PII-EMAIL``) are applied to
   key and/or value as defense-in-depth, even for allowlisted attributes —
   a match means the *value* is redacted (not the whole attribute dropped),
   since the key stays legitimate but the value content is unsafe.
3. Structural violation rules (``V-AGG-TENANT``): a forbidden attribute for
   the current ``saena.context`` is dropped outright.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from saena_observability.registry import (
    DenylistPattern,
    RedactionRules,
    load_attribute_registry,
    load_redaction_rules,
)

REDACTED_VALUE = "[REDACTED]"


class RedactionAction(Enum):
    """Outcome of applying the redaction engine to one attribute."""

    ALLOW = "allow"
    """Attribute is allowlisted, no denylist/violation match — pass through."""

    REDACT_VALUE = "redact_value"
    """Attribute is allowlisted but its value matched a denylist pattern —
    keep the key, replace the value with `REDACTED_VALUE`."""

    DROP = "drop"
    """Attribute is not allowlisted, or violates a structural rule (e.g.
    V-AGG-TENANT) — must not appear in the emitted record at all."""


@dataclass(frozen=True, slots=True)
class RedactionDecision:
    action: RedactionAction
    reason: str


def _matches_denylist_key(
    name: str, patterns: tuple[DenylistPattern, ...]
) -> DenylistPattern | None:
    for p in patterns:
        if "key" in p.applies_to and p.pattern.search(name):
            return p
    return None


def _matches_denylist_value(
    value: Any, patterns: tuple[DenylistPattern, ...]
) -> DenylistPattern | None:
    if not isinstance(value, str):
        return None
    for p in patterns:
        if "value" in p.applies_to and p.pattern.search(value):
            return p
    return None


def _forbidden_by_violation_rule(
    name: str, context: str | None, rules: RedactionRules
) -> str | None:
    if context is None:
        return None
    for rule in rules.violation_rules:
        if rule.context == context and name in rule.forbidden_attributes:
            return rule.id
    return None


def decide_redaction(
    name: str,
    value: Any,
    *,
    context: str | None = None,
) -> RedactionDecision:
    """Decide how attribute `name`=`value` should be handled for export.

    `context` is the `saena.context` value (`tenant`/`system`/`aggregate`)
    of the record the attribute would be attached to; pass `None` if the
    context is not yet known (structural violation rules are skipped in
    that case — callers emitting bound records should always pass it).
    """
    rules = load_redaction_rules()
    allowlist = load_attribute_registry()

    violation_id = _forbidden_by_violation_rule(name, context, rules)
    if violation_id is not None:
        return RedactionDecision(
            RedactionAction.DROP,
            f"{violation_id}: {name!r} forbidden under context={context!r}",
        )

    if name not in allowlist:
        return RedactionDecision(
            RedactionAction.DROP, f"{name!r} not in attribute registry allowlist"
        )

    key_match = _matches_denylist_key(name, rules.denylist_patterns)
    if key_match is not None:
        return RedactionDecision(
            RedactionAction.REDACT_VALUE, f"{key_match.id}: key matched secret pattern"
        )

    value_match = _matches_denylist_value(value, rules.denylist_patterns)
    if value_match is not None:
        return RedactionDecision(
            RedactionAction.REDACT_VALUE, f"{value_match.id}: value matched secret pattern"
        )

    return RedactionDecision(RedactionAction.ALLOW, "allowlisted, no denylist match")


def redact_attributes(attributes: dict[str, Any], *, context: str | None = None) -> dict[str, Any]:
    """Apply `decide_redaction` to every key in `attributes`.

    Returns a new dict: allowed attributes pass through unchanged,
    redact-value attributes keep their key with `REDACTED_VALUE`, dropped
    attributes are absent from the result entirely.
    """
    result: dict[str, Any] = {}
    for name, value in attributes.items():
        decision = decide_redaction(name, value, context=context)
        if decision.action is RedactionAction.ALLOW:
            result[name] = value
        elif decision.action is RedactionAction.REDACT_VALUE:
            result[name] = REDACTED_VALUE
        # DROP: omit entirely.
    return result
