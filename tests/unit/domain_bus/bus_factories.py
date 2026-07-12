"""Factory helpers for `saena_domain.bus` unit tests.

Uniquely-named module (not `conftest.py`) — same import-collision rationale
`tests/unit/domain_persistence/persistence_factories.py`'s own docstring
documents (pytest's `prepend` import mode collapses every `conftest.py` under
one bare top-level `conftest` name across the full collected suite).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from saena_domain.bus.errors import PublishFailedError
from saena_domain.bus.publisher import Publisher
from saena_domain.events import EnvelopeFactory

TENANT_A = "acme-co"
TENANT_B = "globex-co"

#: A well-formed lineage_audit_ref string (opaque per ADR-0013 — any
#: non-empty string is structurally valid).
LINEAGE_AUDIT_REF = "sha256:8f2e1c9a7b3d5f4e6a8c2b1d9f7e3a5c4b6d8f2e1c9a7b3d5f4e6a8c2b1d9f7e"


def make_tenant_envelope(**overrides: Any) -> dict[str, Any]:
    """A valid `context_type: tenant` envelope via the real `EnvelopeFactory`."""
    base: dict[str, Any] = {
        "producer": "agent-runner-service",
        "event_type": "patch.unit.completed.v1",
        "tenant_id": TENANT_A,
        "run_id": "run-2026-0712-0007",
        "idempotency_key": "acme-co:run-2026-0712-0007:patch-unit-042",
        "payload": {"patch_unit_id": "w2-18-outbox-bus", "worktree_commit": "9f1c2e7"},
    }
    base.update(overrides)
    return EnvelopeFactory.build_tenant_envelope(**base)


def make_system_envelope(**overrides: Any) -> dict[str, Any]:
    """A schema-valid `context_type: system` envelope, hand-reshaped from a
    valid tenant envelope — same rationale as
    `tests/unit/domain_persistence/persistence_factories.py::
    make_system_envelope` (v1 AsyncAPI catalog carries zero `system` channels
    yet, `saena_domain.events.factory` module docstring "Catalog gap note")."""
    base = make_tenant_envelope(
        event_type=overrides.pop("event_type", "patch.unit.completed.v1"),
        idempotency_key=overrides.pop("idempotency_key", "system:adapter-config:v1.3.0"),
    )
    base.pop("tenant_id", None)
    base.pop("run_id", None)
    base["context_type"] = "system"
    base.update(overrides)
    return base


def make_aggregate_envelope(**overrides: Any) -> dict[str, Any]:
    """A valid `context_type: aggregate` envelope, `de_identification_status
    = k_anonymized` and `cohort_size >= privacy_threshold` by default (passes
    `guard_aggregate_publish`) — via the real `EnvelopeFactory`."""
    base: dict[str, Any] = {
        "producer": "strategy-skill-bank-service",
        "event_type": "strategy.card.eligible.v1",
        "aggregate_scope_id": "aggregate-scope-014",
        "cohort_size": 12,
        "privacy_threshold": 5,
        "de_identification_status": "k_anonymized",
        "lineage_audit_ref": LINEAGE_AUDIT_REF,
        "idempotency_key": "strategy-card:aggregate-scope-014:2026-07-12",
        "payload": {"engine_id": "chatgpt-search", "strategy_card_id": "card-0142"},
    }
    base.update(overrides)
    return EnvelopeFactory.build_aggregate_envelope(**base)


def make_suppressed_aggregate_envelope(**overrides: Any) -> dict[str, Any]:
    """An aggregate envelope with `cohort_size < privacy_threshold` — must
    fail `guard_aggregate_publish` (`SuppressedEventError`)."""
    base: dict[str, Any] = {
        "cohort_size": 2,
        "privacy_threshold": 5,
        "idempotency_key": "strategy-card:aggregate-scope-014:under-threshold",
    }
    base.update(overrides)
    return make_aggregate_envelope(**base)


@dataclass
class FailNTimesPublisher(Publisher):
    """Test double: raises `PublishFailedError` for the first `fail_count`
    calls to `publish`, then delegates to `InMemoryPublisher` semantics
    (records the call) — used to prove `OutboxDrainer` leaves a row pending
    (never marks published) on publish failure, and successfully publishes
    on a later retry.
    """

    fail_count: int = 0
    published: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _calls: int = 0

    async def publish(self, topic: str, envelope: dict[str, Any]) -> None:
        self._calls += 1
        if self._calls <= self.fail_count:
            raise PublishFailedError(
                f"simulated publish failure #{self._calls} for topic {topic!r}",
                context={"topic": topic},
            )
        self.published.append((topic, copy.deepcopy(envelope)))


class AlwaysFailsPublisher:
    """Test double: every `publish` call raises `PublishFailedError`."""

    async def publish(self, topic: str, envelope: dict[str, Any]) -> None:
        raise PublishFailedError(
            f"simulated permanent publish failure for topic {topic!r}",
            context={"topic": topic},
        )
