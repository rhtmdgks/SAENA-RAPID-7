"""saena_tenant_control — tenant-control-service runtime (W2A).

Bounded context: tenancy, policy profile, retention (service-catalog.md).
Spec basis: `services/foundation/tenant-control-service/README.md`,
`docs/architecture/service-catalog.md`, `docs/architecture/tenancy-model.md`,
ADR-0014 (tenant propagation), ADR-0015 (canonical error model).

W2A scope: FastAPI HTTP API + in-memory persistence
(`saena_domain.persistence.InMemoryTenantRepository`/`InMemoryOutbox`) behind
dependency-injected ports. SQL adapters land in w2-13 (see
`saena_domain.persistence.ports` module docstring). This package reuses
`saena_domain.identity` (`TenantId`, `TenantContext`, `derive_namespace`,
`reconcile_tenant`), `saena_domain.persistence` (`TenantRepository`,
`OutboxPort`), `saena_domain.events` (`EnvelopeFactory`), and
`saena_observability` (`get_logger`, `bind_telemetry_context`) — it defines
no duplicate DTOs for any of those contracts.

Public API:
    create_app — FastAPI application factory (dependency-injected ports).
"""

from __future__ import annotations

from saena_tenant_control.app import create_app

__all__ = ["create_app"]

__version__ = "0.1.0"
