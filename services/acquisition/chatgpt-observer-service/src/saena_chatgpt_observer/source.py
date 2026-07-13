"""`ObservationSourcePort` — read-only observation-capture adapter Protocol.

Structurally READ-ONLY: exactly one method (`capture_observation`), which
returns a new capture result — there is NO write/mutate/publish method on
this Protocol (deliverable 9's "NO browser pool" + the shared "no
write/mutate method absent by construction" negative test applies here
too, mirroring `saena_site_discovery.crawler.SiteCrawlerPort`).

`FakeObservationSource` is a deterministic, in-memory reference
implementation — the ONLY observation source this patch unit ships. The
REAL ChatGPT Search browser-pool session (Playwright fleet, rate-limited
ToS-compliant automation) is explicitly W4, out of scope (mission item 9):
this Protocol only fixes the call shape a later unit's real adapter must
satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from saena_chatgpt_observer.errors import ChatgptObserverError


class UnknownQueryError(ChatgptObserverError):
    """`FakeObservationSource` was asked about a query it has no canned
    response for — a test-harness misconfiguration, not a production
    concern."""

    error_code = "saena.not_found.observation_fixture_query"


class TransientCaptureError(ChatgptObserverError):
    """A query's capture failed in a way `capture.run_chatgpt_observation`
    treats as retryable up to `ObservationBudget.max_retries` (simulates a
    real session's transient failure — rate limit backoff, page load
    timeout, ...)."""

    error_code = "saena.upstream_engine.transient_capture_failure"
    retryable = True


@dataclass(frozen=True, slots=True)
class CapturedObservation:
    """Result of one successful `capture_observation` call — the
    engine-neutral facts an observation source reports back, BEFORE this
    package wraps them into a tenant/run-scoped `PlatformObservation`
    (`capture.py` adds `engine_id`/`tenant_id`/`run_id`/`observed_at`)."""

    citation_refs: tuple[str, ...]
    raw_object_ref: str


@runtime_checkable
class ObservationSourcePort(Protocol):
    """READ-ONLY observation-capture adapter Protocol.

    A single method, a pure capture-and-return read — no publish/write/
    mutate verb exists on this Protocol at all (contrast a hypothetical
    "post a message" capability, which this job kind is never granted per
    ADR-0004: "No Git credential issued at all (observation only)").
    """

    def capture_observation(self, *, query_text: str) -> CapturedObservation:
        """Run one ChatGPT Search observation session for `query_text` and
        return its captured facts. Raises `TransientCaptureError` for a
        simulated transient failure (retryable up to
        `ObservationBudget.max_retries`)."""
        ...


@dataclass
class FakeObservationSource:
    """Deterministic in-memory `ObservationSourcePort` (no real
    network/browser I/O, mission constraint). Configure canned
    `CapturedObservation` responses per query via `register_query`, and
    optionally schedule N transient failures before success via
    `fail_next`. Records every call it receives (`capture_calls`)."""

    _captured: dict[str, CapturedObservation] = field(default_factory=dict)
    _remaining_failures: dict[str, int] = field(default_factory=dict)
    capture_calls: list[str] = field(default_factory=list)

    def register_query(self, query_text: str, captured: CapturedObservation) -> None:
        self._captured[query_text] = captured

    def fail_next(self, query_text: str, *, times: int) -> None:
        """Make the next `times` `capture_observation(query_text=...)`
        calls raise `TransientCaptureError` before finally returning the
        registered `CapturedObservation` (query must already be
        `register_query`d)."""
        self._remaining_failures[query_text] = times

    def capture_observation(self, *, query_text: str) -> CapturedObservation:
        self.capture_calls.append(query_text)
        remaining = self._remaining_failures.get(query_text, 0)
        if remaining > 0:
            self._remaining_failures[query_text] = remaining - 1
            raise TransientCaptureError(
                f"simulated transient capture failure for {query_text!r}",
                context={"query_text": query_text},
            )
        captured = self._captured.get(query_text)
        if captured is None:
            raise UnknownQueryError(
                f"no fixture registered for query {query_text!r}",
                context={"query_text": query_text},
            )
        return captured


__all__ = [
    "CapturedObservation",
    "FakeObservationSource",
    "ObservationSourcePort",
    "TransientCaptureError",
    "UnknownQueryError",
]
