"""UUIDv7 generation and validation (RFC 9562).

Python 3.12's stdlib `uuid` module has no `uuid7()` (added upstream only in
3.14) — `uv run python3 -c "import uuid; hasattr(uuid, 'uuid7')"` returns
False on the 3.12.12 interpreter pinned by this project (pyproject.toml
`requires-python = ">=3.12,<3.13"`). This module implements RFC 9562 §5.7
UUIDv7 directly rather than depending on a third-party backport (ADR
constraint: no new dependencies for this patch unit).

Layout (RFC 9562 §5.2 field/bit layout, §5.7 UUIDv7 field values):
    unix_ts_ms   48 bits  — big-endian millisecond Unix timestamp
    ver           4 bits  — fixed 0b0111 (7)
    rand_a       12 bits  — best-effort monotonic counter (see below)
    var           2 bits  — fixed 0b10
    rand_b       62 bits  — random

This matches the pattern the envelope contract enforces on `event_id`
(`packages/contracts/json-schema/envelope/event-envelope/v1/event-envelope.schema.json`
`$defs.commonFields.event_id.pattern`):
    ^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$
i.e. version nibble fixed to `7`, variant nibble in `{8,9,a,b}`.

Monotonicity: RFC 9562 §6.2 method 1 ("Fixed-Length Dedicated Counter Bits")
is approximated here using the 12-bit `rand_a` field as a per-millisecond,
per-process monotonic counter seeded from a random value, incrementing on
each call that lands in the same millisecond as the previous call. This is
"best effort within-process" only (task spec): no cross-process/cross-host
coordination, and the counter still resets (reseeds) whenever the millisecond
timestamp advances, per RFC 9562 §6.2 guidance for the fixed-counter method.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
import uuid

_EVENT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

_RAND_A_BITS = 12
_RAND_A_MAX = (1 << _RAND_A_BITS) - 1  # 0xFFF

_lock = threading.Lock()
_last_ts_ms: int = -1
_last_rand_a: int = 0


def _next_rand_a(ts_ms: int) -> int:
    """Best-effort monotonic counter for `rand_a`, guarded by `_lock`.

    Same millisecond as the previous call -> increment (wrapping is
    accepted; RFC 9562 does not mandate overflow handling for this method
    and losing strict ordering after 4096 events/ms is out of scope for a
    "best effort within-process" generator). New millisecond -> reseed with
    a fresh random value so ordering is not observable across the boundary.
    """
    global _last_ts_ms, _last_rand_a
    with _lock:
        if ts_ms == _last_ts_ms:
            _last_rand_a = (_last_rand_a + 1) & _RAND_A_MAX
        else:
            _last_ts_ms = ts_ms
            _last_rand_a = secrets.randbelow(_RAND_A_MAX + 1)
        return _last_rand_a


def generate_uuid7() -> str:
    """Generate a lowercase-hex, hyphenated UUIDv7 string (RFC 9562 §5.7).

    Sortable by generation order within the timestamp's millisecond
    resolution (monotonic best-effort, see module docstring); random after
    that. Matches the envelope contract's `event_id` pattern by construction.
    """
    ts_ms = time.time_ns() // 1_000_000
    rand_a = _next_rand_a(ts_ms)

    rand_b = secrets.randbits(62)
    variant_and_rand_b = (0b10 << 62) | rand_b  # 2-bit variant + 62 random bits

    value = (ts_ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76  # version nibble
    value |= (rand_a & 0xFFF) << 64
    value |= variant_and_rand_b

    return str(uuid.UUID(int=value))


def is_valid_uuid7(candidate: str) -> bool:
    """True iff `candidate` matches the envelope contract's UUIDv7 pattern."""
    return bool(_EVENT_ID_PATTERN.match(candidate))
