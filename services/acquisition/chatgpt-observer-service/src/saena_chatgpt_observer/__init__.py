"""saena_chatgpt_observer — chatgpt-observer-service (W3 capture pipeline +
W4 w4-08 browser-pool observer adapter, `JobKind.CHATGPT_OBSERVER`).

Read-only, tenant-scoped, `engine_id`-guarded (v1: `chatgpt-search` only)
ChatGPT Search observation capture. Two capture pipelines now coexist:

- W3 (`capture.py`/`source.py`, unchanged by w4-08): engine-guard-then-
  capture pass over a single injected `ObservationSourcePort` (fake-only),
  producing this package's own pre-formal-contract `PlatformObservation`
  local value object.
- W4 w4-08 (`pool.py`/`artifact_gateway.py`/`platform_observation_record.py`/
  `pool_capture.py`): engine-guard-then-capture pass over a bounded
  `BrowserPool` of `BrowserSessionPort` sessions, routing every raw
  response through the `RawArtifactGatewayPort` single gateway (raw
  content NEVER inline) and producing the formal, w4-10-landed
  `saena_schemas.domain.platform_observation_v1.PlatformObservation`
  record plus its `observation.captured.v1` notification event. The real
  Playwright/Chromium driver (`playwright_driver.py`) is intentionally
  NOT imported here — importing `saena_chatgpt_observer` itself never
  requires `playwright` to be installed; import `playwright_driver`
  directly (integration-lane only) when you need the real driver.

See `services/acquisition/chatgpt-observer-service/README.md` and
`docs/architecture/execution-runtime.md`/`docs/architecture/wave4-plan.md`
for the bounded-context write-up.

Public API:
    PlatformObservation / ObservationValidationError
    ObservationSourcePort / FakeObservationSource / CapturedObservation /
        TransientCaptureError / UnknownQueryError
    ObservationBudget / observation_budget_for
    AuditEntry / ChatgptObserverRunResult / run_chatgpt_observation
    InMemoryObservationStore
    BrowserPool / BrowserPoolStats / BrowserSessionPort /
        FixtureBrowserSession / FixtureBrowserSessionFactory
    RawArtifactGatewayPort / RawArtifactRef / FakeArtifactGateway
    build_platform_observation_record / build_observation_captured_envelope
    PooledObservationResult / PooledObservationRunResult /
        run_pooled_observation
    ChatgptObserverError and every specific error subclass
"""

from __future__ import annotations

from saena_chatgpt_observer.artifact_gateway import (
    FakeArtifactGateway,
    RawArtifactGatewayPort,
    RawArtifactRef,
)
from saena_chatgpt_observer.budget import ObservationBudget, observation_budget_for
from saena_chatgpt_observer.capture import (
    AuditEntry,
    ChatgptObserverRunResult,
    run_chatgpt_observation,
)
from saena_chatgpt_observer.errors import (
    BrowserPoolClosedError,
    BrowserPoolExhaustedError,
    BrowserSessionRenderError,
    ChatgptObserverError,
    CrossTenantObservationError,
    JobKindScopeError,
    ObservationBudgetExceededError,
    ObservationDeadlineExceededError,
    ObservationNotFoundError,
    ObservationRetryExhaustedError,
)
from saena_chatgpt_observer.observation import ObservationValidationError, PlatformObservation
from saena_chatgpt_observer.platform_observation_record import (
    ObservationCapturedEventError,
    PlatformObservationRecordError,
    build_observation_captured_envelope,
    build_platform_observation_record,
)
from saena_chatgpt_observer.pool import (
    BrowserPool,
    BrowserPoolStats,
    BrowserSessionPort,
    FixtureBrowserSession,
    FixtureBrowserSessionFactory,
)
from saena_chatgpt_observer.pool_capture import (
    PooledObservationResult,
    PooledObservationRunResult,
    run_pooled_observation,
)
from saena_chatgpt_observer.source import (
    CapturedObservation,
    FakeObservationSource,
    ObservationSourcePort,
    TransientCaptureError,
    UnknownQueryError,
)
from saena_chatgpt_observer.store import InMemoryObservationStore

__all__ = [
    "AuditEntry",
    "BrowserPool",
    "BrowserPoolClosedError",
    "BrowserPoolExhaustedError",
    "BrowserPoolStats",
    "BrowserSessionPort",
    "BrowserSessionRenderError",
    "CapturedObservation",
    "ChatgptObserverError",
    "ChatgptObserverRunResult",
    "CrossTenantObservationError",
    "FakeArtifactGateway",
    "FakeObservationSource",
    "FixtureBrowserSession",
    "FixtureBrowserSessionFactory",
    "InMemoryObservationStore",
    "JobKindScopeError",
    "ObservationBudget",
    "ObservationBudgetExceededError",
    "ObservationCapturedEventError",
    "ObservationDeadlineExceededError",
    "ObservationNotFoundError",
    "ObservationRetryExhaustedError",
    "ObservationSourcePort",
    "ObservationValidationError",
    "PlatformObservation",
    "PlatformObservationRecordError",
    "PooledObservationResult",
    "PooledObservationRunResult",
    "RawArtifactGatewayPort",
    "RawArtifactRef",
    "TransientCaptureError",
    "UnknownQueryError",
    "build_observation_captured_envelope",
    "build_platform_observation_record",
    "observation_budget_for",
    "run_chatgpt_observation",
    "run_pooled_observation",
]
