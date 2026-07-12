"""Structural conformance: every in-memory adapter satisfies its Protocol.

`runtime_checkable` Protocol `isinstance` checks only verify method NAMES are
present (not signatures) — this is a cheap regression guard against a
method being renamed/removed on one side without the other, not a full
signature check (mypy's static structural check, run via `just typecheck`,
covers the signature-compatibility gap).
"""

from __future__ import annotations

from saena_domain.persistence import (
    ArtifactManifestPort,
    AuditLedgerPort,
    DecisionRecordPort,
    IdempotencyStore,
    InMemoryArtifactManifestStore,
    InMemoryAuditLedger,
    InMemoryDecisionRecordStore,
    InMemoryIdempotencyStore,
    InMemoryOutbox,
    InMemoryPlanRepository,
    InMemoryTenantRepository,
    OutboxPort,
    PlanRepository,
    TenantRepository,
)


def test_in_memory_tenant_repository_satisfies_port() -> None:
    assert isinstance(InMemoryTenantRepository(), TenantRepository)


def test_in_memory_plan_repository_satisfies_port() -> None:
    assert isinstance(InMemoryPlanRepository(), PlanRepository)


def test_in_memory_audit_ledger_satisfies_port() -> None:
    assert isinstance(InMemoryAuditLedger(), AuditLedgerPort)


def test_in_memory_decision_record_store_satisfies_port() -> None:
    assert isinstance(InMemoryDecisionRecordStore(), DecisionRecordPort)


def test_in_memory_artifact_manifest_store_satisfies_port() -> None:
    assert isinstance(InMemoryArtifactManifestStore(), ArtifactManifestPort)


def test_in_memory_outbox_satisfies_port() -> None:
    assert isinstance(InMemoryOutbox(), OutboxPort)


def test_in_memory_idempotency_store_satisfies_port() -> None:
    assert isinstance(InMemoryIdempotencyStore(), IdempotencyStore)
