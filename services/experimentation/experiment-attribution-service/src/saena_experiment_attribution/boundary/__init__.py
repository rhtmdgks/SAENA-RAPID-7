"""experiment-attribution-service boundary — event consumption/publication +
fail-closed guards (w5-12).

Public surface:
- `confirmed_consumer.DeploymentConfirmedConsumer` — consumes
  `deployment.confirmed.v1`, validates against the w5-03 domain gate,
  tenant-scoped registration lookup (neutralizes the w5-18
  `cross_tenant_replay` oracle), direct workflow signal on accept
  (ADR-0003), non-leaking rejection records.
- `outcome_publisher.OutcomePublisher` — assembles + fail-closed-gates
  `experiment.outcome.observed.v1` from a `BGateDecision` + `DiDResult` +
  evidence manifest hash (engine-scope guard + PASS policy gate: ≥2
  qualifying layers, verified evidence manifest, production-or-test
  provenance).
- `observation_adapter.ObservationIngestAdapter` — maps
  `observation.captured.v1`-shaped records into DiD `CellObservation`
  inputs; derives `evidence_basis_id` from the observation artifact hash
  (never caller-asserted); passes `observation_id` through unchanged.
- `ports` — injected `RegistrationLookup` / `WorkflowSignal` /
  `ManifestLookup` protocols (no real bus/DB; dependency injection only).
- `errors` — the boundary's exception hierarchy, including the ONE
  non-leaking `BoundaryLookupAbsent` shape used for every cross-tenant /
  not-found outcome.

Excludes `persistence/` (w5-10), `workflow/` (w5-14), `pipeline/` (w5-13) —
this subpackage is `boundary/` ONLY, per wave5-plan.md's w5-12 exclusive
path.
"""

from __future__ import annotations

from .confirmed_consumer import (
    ConsumeOutcome,
    DeploymentConfirmedConsumer,
    RejectionRecord,
    TransportMetadata,
)
from .errors import (
    BasisDerivationError,
    BoundaryError,
    BoundaryLookupAbsent,
    EngineNotPermittedError,
    PayloadValidationError,
    PublishRefusedError,
    TenantDuplicationError,
)
from .observation_adapter import (
    CapturedObservation,
    ObservationIngestAdapter,
    derive_evidence_basis_id,
)
from .outcome_publisher import OutcomePublisher
from .ports import ManifestLookup, RegistrationLookup, WorkflowSignal

__all__ = [
    "BasisDerivationError",
    "BoundaryError",
    "BoundaryLookupAbsent",
    "CapturedObservation",
    "ConsumeOutcome",
    "DeploymentConfirmedConsumer",
    "EngineNotPermittedError",
    "ManifestLookup",
    "ObservationIngestAdapter",
    "OutcomePublisher",
    "PayloadValidationError",
    "PublishRefusedError",
    "RegistrationLookup",
    "RejectionRecord",
    "TenantDuplicationError",
    "TransportMetadata",
    "WorkflowSignal",
    "derive_evidence_basis_id",
]
