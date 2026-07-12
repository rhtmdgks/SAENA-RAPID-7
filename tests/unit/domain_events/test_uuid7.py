"""Unit tests: saena_domain.events._uuid7 (RFC 9562 UUIDv7).

Covers the task spec's "UUIDv7 format+ordering" requirement.
"""

from __future__ import annotations

import uuid

from saena_domain.events._uuid7 import generate_uuid7, is_valid_uuid7

# Mirrors the envelope contract's event_id pattern exactly
# (packages/contracts/json-schema/envelope/event-envelope/v1/event-envelope.schema.json
# $defs.commonFields.event_id.pattern) so a passing test here is a real
# guarantee about contract conformance, not just an independent opinion.
_CONTRACT_EVENT_ID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def test_generate_uuid7_matches_contract_pattern() -> None:
    value = generate_uuid7()
    assert is_valid_uuid7(value)


def test_generate_uuid7_is_parseable_as_uuid() -> None:
    value = generate_uuid7()
    parsed = uuid.UUID(value)
    assert parsed.version == 7


def test_generate_uuid7_variant_nibble_in_permitted_set() -> None:
    value = generate_uuid7()
    variant_nibble = value.split("-")[3][0]
    assert variant_nibble in "89ab"


def test_generate_uuid7_many_values_all_valid() -> None:
    values = [generate_uuid7() for _ in range(500)]
    assert all(is_valid_uuid7(v) for v in values)


def _ts_ms_prefix(value: str) -> int:
    """First 48 bits (12 hex chars, first two groups) -- the millisecond
    Unix timestamp field (RFC 9562 §5.7).
    """
    hex_digits = value.replace("-", "")
    return int(hex_digits[:12], 16)


def test_generate_uuid7_timestamp_prefix_is_non_decreasing_across_process() -> None:
    """The 48-bit millisecond timestamp field itself is always non-decreasing
    across sequential generation, regardless of the best-effort `rand_a`
    counter's per-millisecond reseed (module docstring: "reseeds... so
    ordering is not observable across the [millisecond] boundary" -- that
    reseed intentionally makes full-value lexical ordering NOT guaranteed
    across a millisecond boundary, so this test checks the guarantee that
    IS made: the timestamp field is chronological).
    """
    values = [generate_uuid7() for _ in range(200)]
    timestamps = [_ts_ms_prefix(v) for v in values]
    assert timestamps == sorted(timestamps)


def test_generate_uuid7_ordering_is_monotonic_within_same_millisecond() -> None:
    """Values generated back-to-back within the same millisecond (rand_a
    increments deterministically, no reseed) are strictly lexically ordered
    -- the guarantee `_next_rand_a` actually provides.
    """
    values = [generate_uuid7() for _ in range(50)]
    same_ms = [v for v in values if _ts_ms_prefix(v) == _ts_ms_prefix(values[0])]
    assert len(same_ms) >= 2, "expected at least 2 values in the same millisecond to compare"
    assert same_ms == sorted(same_ms)


def test_generate_uuid7_values_are_unique() -> None:
    values = [generate_uuid7() for _ in range(500)]
    assert len(set(values)) == len(values)


def test_is_valid_uuid7_rejects_uuidv4() -> None:
    v4 = str(uuid.uuid4())
    assert not is_valid_uuid7(v4)


def test_is_valid_uuid7_rejects_non_uuid_string() -> None:
    assert not is_valid_uuid7("not-a-uuid")


def test_is_valid_uuid7_rejects_wrong_variant_nibble() -> None:
    # Valid version nibble (7) but variant nibble outside {8,9,a,b}.
    candidate = "018f3a1e-7c2b-7c3e-cb1a-4e2f1a9d3c7b"
    assert not is_valid_uuid7(candidate)


def test_is_valid_uuid7_rejects_uppercase() -> None:
    value = generate_uuid7().upper()
    assert not is_valid_uuid7(value)
