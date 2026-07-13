"""`BrowserPool` — bounded pool of read-only ChatGPT Search browser sessions.

W4 (w4-08) extends this package's W3-minimal (`source.py`, fake-only)
observer with the browser-pool adapter `README.md`/execution-runtime.md
named as W3's own explicit non-goal (`ObservationSourcePort`'s docstring:
"The REAL ChatGPT Search browser-pool session ... is explicitly W4"). This
module fixes the POOL lifecycle shape (`BrowserSessionPort` Protocol +
bounded acquire/release/recycle) behind which BOTH a deterministic unit-lane
FIXTURE driver (`FixtureBrowserSessionFactory`, this module's only unit-test
adapter) and a real Playwright/Chromium driver
(`playwright_driver.PlaywrightBrowserSessionFactory`, integration-lane only,
`# pragma: no cover` in the unit lane) can sit, unchanged by the caller.

Structurally READ-ONLY, same discipline as `source.ObservationSourcePort`:
`BrowserSessionPort` has exactly one capability method
(`render_search_result`), a pure read that returns the rendered page's raw
bytes — there is no navigate-and-submit-a-form/login/click-through/write
method anywhere on this Protocol or on `BrowserPool` itself. ADR-0004 "No
Git credential issued at all (observation only)" and this unit's own W4
instruction ("never logs into / writes to a ChatGPT account, never carries
Git credentials in its service account, never mutates any external state")
apply structurally here: nothing in this module's public surface accepts a
credential, a cookie jar to persist, or a write/submit verb.

Pool lifecycle (deliverable: "acquire/release, bounded size, health/
recycle"):

- `acquire()` blocks (never over-provisions past `max_size`) until an idle
  session is available or a new one can be created; raises
  `BrowserPoolExhaustedError` if `acquire_timeout_seconds` elapses first
  (never hangs forever — mirrors `ObservationBudget`'s own deadline
  discipline).
- `release(session)` returns a session to the idle set. A session whose
  `is_healthy()` now reports `False`, or that has served
  `max_uses_per_session` renders, is recycled (closed + replaced by a fresh
  one) rather than returned to service — this is the "health/recycle" half
  of the deliverable.
- `close()` tears down every pooled session (idempotent).
- A context-manager helper (`leased_session`) is provided so callers never
  have to remember the acquire/release pair by hand (same ergonomic
  precedent as `saena_domain.persistence`'s connection-lease helpers).

Every session is a plain Python object built by an injected
`BrowserSessionFactory` callable — the pool itself never imports
`playwright` (that import lives ONLY in `playwright_driver.py`, guarded so
its absence never breaks the unit lane — see that module's own docstring).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from saena_chatgpt_observer.errors import (
    BrowserPoolClosedError,
    BrowserPoolExhaustedError,
    BrowserSessionRenderError,
)

_DEFAULT_ACQUIRE_TIMEOUT_SECONDS = 5.0
_DEFAULT_MAX_USES_PER_SESSION = 50


@runtime_checkable
class BrowserSessionPort(Protocol):
    """READ-ONLY rendered-page session Protocol.

    A single capability method — no navigate-and-submit/login/write verb
    exists on this Protocol at all (mirrors `source.ObservationSourcePort`'s
    same structural-read-only discipline, one layer lower: this Protocol is
    what a real/fixture BROWSER SESSION looks like; `ObservationSourcePort`
    is what the higher-level OBSERVATION CAPTURE call looks like — `bridge.
    PooledObservationSource` adapts one onto the other).
    """

    def render_search_result(self, *, query_text: str) -> bytes:
        """Render one ChatGPT Search result page for `query_text` and
        return its raw response bytes (HTML/screenshot — this Protocol does
        not distinguish the two; the caller decides what `bytes` means for
        its own driver). Never returns a reference, never persists
        anything — the raw bytes are the pool's entire contract; routing
        them through the artifact single gateway is the CALLER's job
        (`artifact_gateway.py`), never this module's."""
        ...

    def is_healthy(self) -> bool:
        """Return whether this session is still usable. A session that
        starts reporting `False` is recycled by `BrowserPool.release`,
        never handed out again by `acquire`."""
        ...

    def close(self) -> None:
        """Release this session's own underlying resources (idempotent)."""
        ...


BrowserSessionFactory = Callable[[], BrowserSessionPort]


@dataclass(slots=True)
class FixtureBrowserSession:
    """Deterministic, in-memory `BrowserSessionPort` — the ONLY session
    this patch unit's unit lane ever constructs. No real network/browser
    I/O. Configure canned response bytes per query via `register_query`;
    `render_calls` records every call for test assertions. `poison()` flips
    `is_healthy()` to `False` so a test can force the pool's recycle path
    deterministically."""

    session_id: str
    _responses: dict[str, bytes] = field(default_factory=dict)
    render_calls: list[str] = field(default_factory=list)
    _healthy: bool = True
    _closed: bool = False

    def register_query(self, query_text: str, response: bytes) -> None:
        self._responses[query_text] = response

    def poison(self) -> None:
        """Test-only: make this session report unhealthy from now on."""
        self._healthy = False

    def render_search_result(self, *, query_text: str) -> bytes:
        if self._closed:
            raise BrowserSessionRenderError(
                f"session {self.session_id!r} is closed",
                context={"session_id": self.session_id},
            )
        self.render_calls.append(query_text)
        response = self._responses.get(query_text)
        if response is None:
            raise BrowserSessionRenderError(
                f"no fixture response registered for query {query_text!r}",
                context={"session_id": self.session_id, "query_text": query_text},
            )
        return response

    def is_healthy(self) -> bool:
        return self._healthy and not self._closed

    def close(self) -> None:
        self._closed = True


class FixtureBrowserSessionFactory:
    """Deterministic `BrowserSessionFactory` — builds sequentially-numbered
    `FixtureBrowserSession`s (`fixture-session-0`, `fixture-session-1`, ...)
    so pool-lifecycle unit tests can assert exactly which session instance
    was (re)used across acquire/release/recycle cycles. Every session built
    shares the same `shared_responses` mapping unless a test registers a
    per-session response after construction (`sessions_built` records every
    instance in construction order)."""

    def __init__(self, shared_responses: dict[str, bytes] | None = None) -> None:
        self._next_id = 0
        self._shared_responses = dict(shared_responses) if shared_responses else {}
        self.sessions_built: list[FixtureBrowserSession] = []

    def __call__(self) -> BrowserSessionPort:
        session = FixtureBrowserSession(session_id=f"fixture-session-{self._next_id}")
        for query_text, response in self._shared_responses.items():
            session.register_query(query_text, response)
        self._next_id += 1
        self.sessions_built.append(session)
        return session


@dataclass(frozen=True, slots=True)
class BrowserPoolStats:
    """Point-in-time pool occupancy snapshot — test/observability read
    model, never mutated in place."""

    idle: int
    in_use: int
    total: int
    recycled_count: int


class BrowserPool:
    """Bounded pool of `BrowserSessionPort` sessions.

    Thread-safe (same `threading.Lock` discipline as `store.
    InMemoryObservationStore` / `saena_artifact_registry.blobstore.
    InMemoryBlobStore`). Never creates more than `max_size` sessions at
    once; `acquire()` blocks up to `acquire_timeout_seconds` for one to
    free up before raising `BrowserPoolExhaustedError` (bounded — never
    hangs the caller forever, mirrors `ObservationBudget.
    active_deadline_seconds`'s own "never wait unboundedly" discipline).
    """

    def __init__(
        self,
        session_factory: BrowserSessionFactory,
        *,
        max_size: int,
        acquire_timeout_seconds: float = _DEFAULT_ACQUIRE_TIMEOUT_SECONDS,
        max_uses_per_session: int = _DEFAULT_MAX_USES_PER_SESSION,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._session_factory = session_factory
        self._max_size = max_size
        self._acquire_timeout_seconds = acquire_timeout_seconds
        self._max_uses_per_session = max_uses_per_session
        self._clock = clock

        self._condition = threading.Condition()
        self._idle: list[BrowserSessionPort] = []
        self._in_use: set[int] = set()
        self._use_counts: dict[int, int] = {}
        self._total_created = 0
        self._recycled_count = 0
        self._closed = False

    def acquire(self) -> BrowserSessionPort:
        """Return an idle session (creating one if the pool has not yet
        reached `max_size`), blocking up to `acquire_timeout_seconds` for
        one to free up otherwise.

        Raises `BrowserPoolClosedError` if `close()` was already called,
        `BrowserPoolExhaustedError` on timeout.
        """
        deadline = self._clock() + self._acquire_timeout_seconds
        with self._condition:
            while True:
                if self._closed:
                    raise BrowserPoolClosedError(
                        "cannot acquire from a closed BrowserPool", context={}
                    )
                if self._idle:
                    session = self._idle.pop()
                    self._in_use.add(id(session))
                    return session
                if self._total_created < self._max_size:
                    session = self._session_factory()
                    self._total_created += 1
                    self._use_counts[id(session)] = 0
                    self._in_use.add(id(session))
                    return session
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise BrowserPoolExhaustedError(
                        f"no browser session freed up within "
                        f"{self._acquire_timeout_seconds}s (pool max_size="
                        f"{self._max_size})",
                        context={"max_size": self._max_size},
                    )
                self._condition.wait(timeout=remaining)

    def release(self, session: BrowserSessionPort) -> None:
        """Return `session` to the idle set, or recycle it (close +
        replace its capacity slot) if it is now unhealthy or has served
        `max_uses_per_session` renders.

        Releasing a session this pool did not hand out via `acquire()` (or
        releasing the same session twice) is a no-op — defensive, never
        raises, mirrors a typical connection-pool `release`'s idempotence.
        """
        with self._condition:
            key = id(session)
            if key not in self._in_use:
                return
            self._in_use.discard(key)
            self._use_counts[key] = self._use_counts.get(key, 0) + 1

            needs_recycle = (
                not session.is_healthy() or self._use_counts[key] >= self._max_uses_per_session
            )
            if needs_recycle or self._closed:
                session.close()
                self._use_counts.pop(key, None)
                self._total_created -= 1
                if needs_recycle and not self._closed:
                    self._recycled_count += 1
            else:
                self._idle.append(session)
            self._condition.notify_all()

    def leased_session(self) -> _LeasedSession:
        """Context-manager helper: `with pool.leased_session() as session:
        ...` acquires on enter, releases on exit (including on exception)."""
        return _LeasedSession(self)

    def close(self) -> None:
        """Close every idle session and mark the pool closed (idempotent).
        In-flight (acquired-but-not-yet-released) sessions are closed as
        soon as they are released, never forcibly torn down out from under
        a caller still holding one."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            for session in self._idle:
                session.close()
            self._idle.clear()
            self._condition.notify_all()

    def stats(self) -> BrowserPoolStats:
        with self._condition:
            return BrowserPoolStats(
                idle=len(self._idle),
                in_use=len(self._in_use),
                total=self._total_created,
                recycled_count=self._recycled_count,
            )


@dataclass(slots=True)
class _LeasedSession:
    """`with`-statement helper returned by `BrowserPool.leased_session()`."""

    _pool: BrowserPool
    _session: BrowserSessionPort | None = None

    def __enter__(self) -> BrowserSessionPort:
        self._session = self._pool.acquire()
        return self._session

    def __exit__(self, *exc_info: object) -> None:
        if self._session is not None:
            self._pool.release(self._session)
            self._session = None


__all__ = [
    "BrowserPool",
    "BrowserPoolStats",
    "BrowserSessionFactory",
    "BrowserSessionPort",
    "FixtureBrowserSession",
    "FixtureBrowserSessionFactory",
]
