"""Span-name and metric-name validators (ADR-0016 naming rules).

- Span naming: `saena.<capability>.<operation>` — low-cardinality segments
  only. Identifiers (`run_id`, `tenant_id`, etc.) must never be embedded in
  a span name; they belong exclusively in attributes.
- Metric naming: `saena.<domain>.<name>` — same low-cardinality-segment
  discipline.

Both patterns share the same segment-shape rule: lowercase
`[a-z][a-z0-9_]*` segments joined by `.`, with a `saena.` prefix and at
least one segment after it (capability/operation, or domain/name). This
module also rejects names that look like they embed a high-cardinality
identifier (UUID-shaped, or a long run of purely hex/digit characters) as
a defense-in-depth check against accidental identifier-in-name mistakes —
the ADR-0016 rule is "identifiers are attributes, never name segments".
This heuristic is NOT exhaustive: it only catches UUID-shaped segments and
segments that are entirely hex/digit characters; it does not catch mixed
alphanumeric identifiers (e.g. a base32/base36-style id segment containing
both letters outside `a`-`f` and digits, or a word-prefixed id like
`run42`) — those pass this validator undetected. Treat this as one
defense-in-depth signal, not a complete identifier-in-name detector.
"""

from __future__ import annotations

import re

_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NAMESPACE_PREFIX = "saena."

# Heuristic identifier-shaped segment detectors (defense-in-depth beyond the
# base lowercase-segment shape check): UUID-like, or a long run of hex/digits
# that looks like an id rather than a capability/operation/domain/name word.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$")
_LONG_HEX_OR_DIGIT_RE = re.compile(r"^[0-9a-f]{8,}$")


def _looks_like_identifier(segment: str) -> bool:
    return bool(_UUID_RE.match(segment)) or bool(_LONG_HEX_OR_DIGIT_RE.match(segment))


def _validate_namespaced_name(value: str, *, min_segments_after_prefix: int) -> tuple[bool, str]:
    if not value.startswith(_NAMESPACE_PREFIX):
        return False, f"must start with {_NAMESPACE_PREFIX!r}"
    remainder = value[len(_NAMESPACE_PREFIX) :]
    if not remainder:
        return False, "must have at least one segment after 'saena.'"
    segments = remainder.split(".")
    if len(segments) < min_segments_after_prefix:
        return False, (
            f"expected at least {min_segments_after_prefix} segment(s) after "
            f"'saena.', got {len(segments)}: {segments!r}"
        )
    for segment in segments:
        if not _SEGMENT_RE.match(segment):
            return False, f"segment {segment!r} is not lowercase [a-z][a-z0-9_]*"
        if _looks_like_identifier(segment):
            return False, (
                f"segment {segment!r} looks like an embedded identifier "
                "(UUID/long hex) — identifiers must be attributes, never name "
                "segments (ADR-0016)"
            )
    return True, "ok"


def is_valid_span_name(name: str) -> bool:
    """True iff `name` matches `saena.<capability>.<operation>` shape."""
    ok, _ = _validate_namespaced_name(name, min_segments_after_prefix=2)
    return ok


def validate_span_name(name: str) -> None:
    """Raise `ValueError` with a specific reason if `name` is not a valid
    `saena.<capability>.<operation>` span name."""
    ok, reason = _validate_namespaced_name(name, min_segments_after_prefix=2)
    if not ok:
        raise ValueError(f"invalid span name {name!r}: {reason}")


def is_valid_metric_name(name: str) -> bool:
    """True iff `name` matches `saena.<domain>.<name>` shape."""
    ok, _ = _validate_namespaced_name(name, min_segments_after_prefix=2)
    return ok


def validate_metric_name(name: str) -> None:
    """Raise `ValueError` with a specific reason if `name` is not a valid
    `saena.<domain>.<name>` metric name."""
    ok, reason = _validate_namespaced_name(name, min_segments_after_prefix=2)
    if not ok:
        raise ValueError(f"invalid metric name {name!r}: {reason}")
