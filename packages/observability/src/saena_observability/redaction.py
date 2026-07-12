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
   since the key stays legitimate but the value content is unsafe. The same
   VALUE-applicable patterns are also usable against free-text strings (log
   message bodies) via `redact_text` — the registry's `applies_to: [value]`
   patterns do not distinguish "value" of an attribute from "value" of a
   log body; both are unstructured string content the denylist must scan.
3. Structural violation rules (``V-AGG-TENANT``): a forbidden attribute for
   the current ``saena.context`` is dropped outright.
4. Fail-closed on non-scalar attribute values: the registry's attribute
   `type` enum is `string|int|double|boolean` only (`attributes.schema.json`)
   — there is no contract for dict/list/nested-structure attribute values.
   Any value that is not `str`/`int`/`float`/`bool` (and not `None`) is
   REDACT_VALUE'd rather than passed through or matched against regexes
   (regexes only run on `str`), since serializing an arbitrary object could
   leak nested secret fields the denylist never gets a chance to inspect.
"""

from __future__ import annotations

import re
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

# Scalar types the registry's attribute `type` enum actually contracts for
# (attributes.schema.json: string|int|double|boolean). `None` is accepted
# too (absence-of-value case for text formatting call sites) but is not
# itself a registry `type`.
_ALLOWED_SCALAR_TYPES = (str, int, float, bool)


class RedactionAction(Enum):
    """Outcome of applying the redaction engine to one attribute."""

    ALLOW = "allow"
    """Attribute is allowlisted, no denylist/violation match — pass through."""

    REDACT_VALUE = "redact_value"
    """Attribute is allowlisted but its value matched a denylist pattern, or
    is not a registry-contracted scalar type — keep the key, replace the
    value with `REDACTED_VALUE`."""

    DROP = "drop"
    """Attribute is not allowlisted, or violates a structural rule (e.g.
    V-AGG-TENANT) — must not appear in the emitted record at all."""


@dataclass(frozen=True, slots=True)
class RedactionDecision:
    action: RedactionAction
    reason: str


def _is_non_scalar(value: Any) -> bool:
    """True if `value` is not a registry-contracted scalar type and not
    `None`. dict/list/set/tuple/bytes/custom objects all fail closed."""
    if value is None:
        return False
    return not isinstance(value, _ALLOWED_SCALAR_TYPES)


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

    if _is_non_scalar(value):
        return RedactionDecision(
            RedactionAction.REDACT_VALUE,
            "R-NON-SCALAR-VALUE: value is not a registry-contracted scalar type "
            f"(str/int/float/bool) — got {type(value).__name__}; fail-closed, "
            "never serialized",
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


def _keyword_assignment_span_re(pattern: re.Pattern[str]) -> re.Pattern[str]:
    """Build an expanded regex for a bare-keyword denylist pattern (e.g.
    `R-SECRET-TOKEN`'s `(?i)token`) that also consumes a trailing
    `key=value` / `key:value` assignment-shaped span, so redacting a
    free-text match covers the leaked secret VALUE next to the keyword —
    not just the keyword itself.

    Only the unambiguous `=`/`:` assignment-operator shape is expanded
    (e.g. ``token=abc123``, ``password: hunter2``). A bare whitespace
    separator (``token was abc123``, ``token is abc123``) is deliberately
    NOT treated as an assignment — there is no reliable way to distinguish
    "the next word is the secret value" from "the next word is filler
    English text" (`"token was granted"` vs `"token was abc123secret"`)
    without a value-shaped grammar this module does not have. Free-text
    messages that interpolate a secret via a filler-word phrase rather
    than an explicit `key=value`/`key: value` assignment are OUT OF SCOPE
    for this redaction layer — callers should prefer `key=value`-style
    log messages precisely so this scrubbing is effective (documented
    caveat, not a silent gap).

    `R-PII-EMAIL`'s pattern already matches the secret content directly
    (an email address IS the leak), so it needs no expansion; this
    expansion only applies to bare-keyword patterns whose match, by
    itself, is just an English word/keyword and not the secret content.
    """
    return re.compile(pattern.pattern + r"[=:]\s*(?P<secret_value>\S+)", pattern.flags)


def redact_text(text: str) -> str:
    """Scrub `text` (e.g. a formatted log message body) against every
    VALUE-applicable denylist pattern (`redaction-rules.yaml`
    `applies_to: [value, ...]` patterns).

    This is distinct from `decide_redaction`'s value-matching, which
    decides a whole-attribute-value fate (allow/redact/drop). Log bodies
    are free text that may interpolate a secret alongside safe words (e.g.
    ``"token=%s" % token`` -> ``"token=abc123secret"``). Two match shapes
    are handled:

    - Content-shaped patterns (e.g. `R-PII-EMAIL`, whose regex matches the
      leaked value itself) — the matched span is replaced directly.
    - Bare-keyword patterns (e.g. `R-SECRET-TOKEN`'s `(?i)token`,
      `R-SECRET-PASSWORD`'s `(?i)password`) — matching only the keyword
      and replacing just that word would leave an interpolated secret
      value sitting right next to it fully exposed (e.g.
      ``"token=%s" % token`` -> naive replace gives
      ``"[REDACTED]=abc123secret"``, which still leaks the value). For
      these, the keyword match is first expanded to also consume a
      trailing `key=value` / `key:value` assignment-shaped span
      (`_keyword_assignment_span_re`) so the actual secret is covered by
      the same redaction; the bare keyword pattern is then also applied so
      a keyword with no trailing assignment (e.g. mid-sentence mention) is
      still redacted on its own. See `_keyword_assignment_span_re` for the
      documented scope boundary (assignment-operator shapes only, not
      arbitrary filler-word phrases).
    """
    rules = load_redaction_rules()
    redacted = text
    for pattern in rules.denylist_patterns:
        if "value" not in pattern.applies_to:
            continue
        expanded = _keyword_assignment_span_re(pattern.pattern)
        redacted = expanded.sub(REDACTED_VALUE, redacted)
        redacted = pattern.pattern.sub(REDACTED_VALUE, redacted)
    return redacted


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
