"""Postgres measurement-persistence adapters for the measurement stores (w5-10).

Implements the four `saena_domain.measurement.ports` Protocols
(`ConfirmationStore`, `MeasurementWindowStore`, `OutcomeDecisionStore`,
`EvidenceBundleStore`) over real PostgreSQL, holding the SAME conformance
contract (`saena_domain.measurement.ports_conformance`) the in-memory
reference (w5-09) holds — a divergence in either backend fails the shared
suite immediately.

Layering (coverage-ratchet discipline, w2-13/w4-07 precedent):

- `tables` — pure DDL/DML SQL builders + schema names. No I/O. Unit-tested.
- `fingerprint` — canonical-content fingerprints (JCS via
  `saena_domain.audit.canonical`, byte-identity idempotency key). Pure.
  Unit-tested.
- `mapping` — record <-> row-dict translation + JSON (de)serialization +
  the SF-4 evidence re-verification boundary. Pure. Unit-tested.
- `adapter` — the ONLY module that touches a live `AsyncEngine`/asyncpg.
  Kept out of the blocking unit-lane ratchet via its per-class
  `# pragma: no cover` markers (the current, self-sufficient mechanism); the
  root-pyproject `[tool.coverage.run].omit` registration matching the w2-13
  persistence + w4-07 pgvector precedent entries is Integrator-owned and
  happens at merge. Its behavior is proven by the real-container
  `tests/integration/measurement_pg/**` conformance lane, not by a mock.
"""

from __future__ import annotations

from saena_experiment_attribution.persistence.adapter import (
    PgConfirmationStore,
    PgEvidenceBundleStore,
    PgMeasurementWindowStore,
    PgOutcomeDecisionStore,
    apply_migrations,
    create_schema,
    truncate_all,
)

__all__ = [
    "PgConfirmationStore",
    "PgEvidenceBundleStore",
    "PgMeasurementWindowStore",
    "PgOutcomeDecisionStore",
    "apply_migrations",
    "create_schema",
    "truncate_all",
]
