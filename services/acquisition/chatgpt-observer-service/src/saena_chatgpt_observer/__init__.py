"""saena_chatgpt_observer — chatgpt-observer-service (W3,
`JobKind.CHATGPT_OBSERVER`).

Read-only, tenant-scoped, `engine_id`-guarded (v1: `chatgpt-search` only)
ChatGPT Search observation capture: engine-guard-then-capture pass over an
`ObservationSourcePort` adapter (fake-only in this patch unit — a real
Playwright/browser-pool fleet is W4), producing immutable
`PlatformObservation`s (with an audit trail). See
`services/acquisition/chatgpt-observer-service/README.md` and
`docs/architecture/execution-runtime.md` for the bounded-context write-up.

W3 MINIMAL scope — explicitly OUT of this package (Wave 4 or later,
deliberately not implemented here): a real browser-pool/Playwright client,
`observation.captured.v1`'s own event payload builder (deferred per
`docs/architecture/execution-runtime.md` "Deferred to later units" — that
event needs `payload.engine_id`, unlike the 4 events w3-01 already builds),
citation-intelligence/experiment-attribution analysis over captured
observations, any 2nd-engine (Google/Gemini) adapter (CLAUDE.md "Engine
scope (v1)" — disabled, `guard_engine_id` rejects them structurally).

Public API:
    PlatformObservation / ObservationValidationError
    ObservationSourcePort / FakeObservationSource / CapturedObservation /
        TransientCaptureError / UnknownQueryError
    ObservationBudget / observation_budget_for
    AuditEntry / ChatgptObserverRunResult / run_chatgpt_observation
    InMemoryObservationStore
    ChatgptObserverError and every specific error subclass
"""

from __future__ import annotations

from saena_chatgpt_observer.budget import ObservationBudget, observation_budget_for
from saena_chatgpt_observer.capture import (
    AuditEntry,
    ChatgptObserverRunResult,
    run_chatgpt_observation,
)
from saena_chatgpt_observer.errors import (
    ChatgptObserverError,
    CrossTenantObservationError,
    JobKindScopeError,
    ObservationBudgetExceededError,
    ObservationDeadlineExceededError,
    ObservationNotFoundError,
    ObservationRetryExhaustedError,
)
from saena_chatgpt_observer.observation import ObservationValidationError, PlatformObservation
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
    "CapturedObservation",
    "ChatgptObserverError",
    "ChatgptObserverRunResult",
    "CrossTenantObservationError",
    "FakeObservationSource",
    "InMemoryObservationStore",
    "JobKindScopeError",
    "ObservationBudget",
    "ObservationBudgetExceededError",
    "ObservationDeadlineExceededError",
    "ObservationNotFoundError",
    "ObservationRetryExhaustedError",
    "ObservationSourcePort",
    "ObservationValidationError",
    "PlatformObservation",
    "TransientCaptureError",
    "UnknownQueryError",
    "observation_budget_for",
    "run_chatgpt_observation",
]
