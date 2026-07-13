"""`Clock` Protocol — injectable monotonic time source for deadline checks.

Not part of `saena_domain.execution.protocols` (that module fixes
heartbeat/cancellation/progress call shapes only, no time source) — this
package needs its own minimal seam so `runner.py`'s
`active_deadline_seconds` check is deterministic and instant in unit tests
(no real `time.sleep`), via `FakeClock`.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def monotonic(self) -> float:
        """Return a monotonically increasing time value, in seconds — used
        for `active_deadline_seconds` elapsed-time checks only."""
        ...

    def now_iso(self) -> str:
        """Return the current wall-clock time as a `timestamp_utc`-shaped
        string (`AuditEvent.recorded_at`/`PatchArtifact.created_at` shape:
        `YYYY-MM-DDTHH:MM:SS(.ffffff)?Z`) — used for audit/artifact
        timestamps only, never for deadline arithmetic (monotonic() owns
        that)."""
        ...


class SystemClock:
    """Real `Clock` — `time.monotonic()` + real UTC wall-clock time."""

    def monotonic(self) -> float:
        return time.monotonic()

    def now_iso(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeClock:
    """Deterministic, manually-advanced `Clock` for unit tests.

    `now_iso()` returns a fixed, valid `timestamp_utc` string derived from
    the current monotonic value so successive calls after `advance()` are
    still deterministic and schema-valid, without depending on wall-clock
    time at all.
    """

    def __init__(self, *, start: float = 0.0) -> None:
        self._now = start

    def monotonic(self) -> float:
        return self._now

    def now_iso(self) -> str:
        return f"2026-01-01T00:00:{int(self._now) % 60:02d}Z"

    def advance(self, seconds: float) -> None:
        self._now += seconds


__all__ = ["Clock", "FakeClock", "SystemClock"]
