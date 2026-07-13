"""Lineage passthrough surface — injected port Protocol, RBAC gate at the edge.

`GET /v1/lineage/{ref}` is documented (task instruction 3, "Lineage
passthrough surface") as reaching audit-ledger-service downstream; for W2A
that downstream call is STUBBED as an injected `LineagePort` — this service
performs the `view_lineage` RBAC gate (`saena_domain.authz`,
`Role.AUDITOR`-only per ADR-0013 `lineage_audit_ref` "audit role 전용 열람")
at the edge BEFORE any downstream call, and then delegates resolution to
whatever `LineagePort` implementation `create_app()` was given. No real
audit-ledger HTTP/RPC client exists in this patch unit's exclusive-write
paths (no cross-service imports — see this service's README/status note);
wiring a real client is a follow-up patch unit's concern.

`ref` is treated as an opaque string end to end — this module does not
parse/validate it as a `lineage_audit_ref` (`saena_domain.audit.lineage`'s
`is_lineage_ref` format check belongs to the eventual real client, not this
edge stub) since a stub port has no real backing store to validate against.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LineagePort(Protocol):
    """Injected downstream resolution port (audit-ledger reachable only via
    port injection at this W2A stage, per task instruction 3)."""

    def resolve(self, tenant_id: str, ref: str) -> dict[str, Any]:
        """Resolve `ref` to a lineage record for `tenant_id`.

        Raises `KeyError` if no record exists for `ref` (mapped to
        `not_found` at the route layer, `saena_forge_console.routes`).
        """
        ...


class StubLineagePort:
    """Default `LineagePort` — an empty, always-`KeyError`-raising stub, for
    `create_app()` callers (including tests) that do not inject a real
    resolver. Never used to fabricate lineage data; it exists so this
    service is importable/runnable standalone without a live audit-ledger
    dependency, matching the "downstream resolution stubbed as injected
    port" instruction.
    """

    def resolve(self, tenant_id: str, ref: str) -> dict[str, Any]:
        raise KeyError(ref)


class InMemoryLineagePort:
    """Test-oriented `LineagePort` — a plain, tenant-scoped in-memory map,
    for tests that need `resolve` to actually succeed."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict[str, Any]] = {}

    def seed(self, tenant_id: str, ref: str, record: dict[str, Any]) -> None:
        self._store[(tenant_id, ref)] = record

    def resolve(self, tenant_id: str, ref: str) -> dict[str, Any]:
        try:
            return self._store[(tenant_id, ref)]
        except KeyError:
            raise KeyError(ref) from None


__all__ = ["InMemoryLineagePort", "LineagePort", "StubLineagePort"]
