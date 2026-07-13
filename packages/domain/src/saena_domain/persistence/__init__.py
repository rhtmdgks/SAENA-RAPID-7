"""saena_domain.persistence — persistence port Protocols + in-memory reference adapters (w2-07).

Spec basis: `docs/architecture/data-ownership.md` (own-DB-or-own-schema,
tenant discriminator), `docs/architecture/contract-catalog.md` (per-contract
idempotency keys), ADR-0007 (ownership topology), ADR-0013 (event envelope /
`idempotency_key`), ADR-0014 (tenant propagation), `docs/architecture/
implementation-waves.md` W2A ("이벤트는 transactional outbox 기록까지 —
bus 배선은 2C").

This module ships PORTS (`ports.py`, `typing.Protocol` interfaces) and pure
in-memory REFERENCE ADAPTERS (`memory.py`) only. SQL adapters land in w2-13;
the Kafka/Redpanda bus publisher lands in w2-18 — neither is implemented
here (see each module's docstring for the exact boundary).

Public API:

- Ports: `TenantRepository`, `PlanRepository`, `AuditLedgerPort`,
  `DecisionRecordPort`, `ArtifactManifestPort`, `OutboxPort`,
  `IdempotencyStore`.
- In-memory adapters: `InMemoryTenantRepository`, `InMemoryPlanRepository`,
  `InMemoryAuditLedger`, `InMemoryDecisionRecordStore`,
  `InMemoryArtifactManifestStore`, `InMemoryOutbox`,
  `InMemoryIdempotencyStore`.
- Errors: `PersistenceError`, `TenantIsolationError`, `NotFoundError`,
  `DuplicateManifestError`, `OutboxValidationError`, `LedgerIntegrityError`,
  `DecisionConflictError`.
- Value objects: `TenantRecord` (gate-free tenant status view, critic
  MUST-FIX 4 — see `ports.py`'s own docstring).
"""

from __future__ import annotations

from saena_domain.persistence.errors import (
    DecisionConflictError,
    DuplicateManifestError,
    LedgerIntegrityError,
    NotFoundError,
    OutboxValidationError,
    PersistenceError,
    TenantIsolationError,
)
from saena_domain.persistence.memory import (
    InMemoryArtifactManifestStore,
    InMemoryAuditLedger,
    InMemoryDecisionRecordStore,
    InMemoryIdempotencyStore,
    InMemoryOutbox,
    InMemoryPlanRepository,
    InMemoryTenantRepository,
)
from saena_domain.persistence.ports import (
    ArtifactManifestPort,
    AuditLedgerPort,
    DecisionRecordPort,
    IdempotencyStore,
    OutboxPort,
    PlanRepository,
    TenantRecord,
    TenantRepository,
)

__all__ = [
    "ArtifactManifestPort",
    "AuditLedgerPort",
    "DecisionConflictError",
    "DecisionRecordPort",
    "DuplicateManifestError",
    "IdempotencyStore",
    "InMemoryArtifactManifestStore",
    "InMemoryAuditLedger",
    "InMemoryDecisionRecordStore",
    "InMemoryIdempotencyStore",
    "InMemoryOutbox",
    "InMemoryPlanRepository",
    "InMemoryTenantRepository",
    "LedgerIntegrityError",
    "NotFoundError",
    "OutboxPort",
    "OutboxValidationError",
    "PersistenceError",
    "PlanRepository",
    "TenantIsolationError",
    "TenantRecord",
    "TenantRepository",
]
