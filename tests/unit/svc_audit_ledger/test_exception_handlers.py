"""Module-level `IdentityError`/`PersistenceError` exception handlers.

These handlers are the LAST-RESORT mapping for a `saena_domain` structured
exception that escapes a route's own inline try/except (see `app.py`'s
`_identity_error_handler`/`_persistence_error_handler`). The `IdentityError`
path is exercised naturally by `test_append.py`'s malformed-tenant_id case
(`_resolve_scope_tenant` raises outside any inline try/except); the
`PersistenceError` path has no current trigger from the in-memory reference
adapter (`InMemoryAuditLedger` never raises a `PersistenceError` subclass —
only `ForbiddenAuditDataError`/`ValueError`, both handled inline) — this
module exercises it directly with a minimal fake `AuditLedgerPort` that
raises one, proving the handler itself is wired and functions correctly
ahead of a real w2-13 SQL adapter that legitimately can raise
`TenantIsolationError`/`LedgerIntegrityError`.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from ledger_factories import TENANT_A, roles_header
from saena_audit_ledger import create_app
from saena_domain.audit import AuditEntry
from saena_domain.identity import TenantId
from saena_domain.persistence.errors import TenantIsolationError


class _ExplodingLedger:
    """Minimal `AuditLedgerPort`-shaped stub whose `read_range` always
    raises `TenantIsolationError` (a `PersistenceError` subclass)."""

    def append(self, entry: AuditEntry) -> AuditEntry:  # pragma: no cover - not exercised
        raise NotImplementedError

    def read_range(
        self,
        *,
        tenant_id: TenantId | None = None,
        start_index: int = 0,
        end_index: int | None = None,
    ) -> tuple[AuditEntry, ...]:
        raise TenantIsolationError("simulated cross-tenant access", context={"tenant_id": TENANT_A})

    def verify(self, *, tenant_id: TenantId | None = None) -> tuple[bool, int | None]:
        raise TenantIsolationError("simulated cross-tenant access", context={"tenant_id": TENANT_A})


def test_persistence_error_is_mapped_to_409_problem_json() -> None:
    exploding_client = TestClient(create_app(_ExplodingLedger()))  # type: ignore[arg-type]

    resp = exploding_client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 409
    body: dict[str, Any] = resp.json()
    assert body["error_code"] == "saena.persistence.tenant_isolation_violation"
    assert body["status"] == 409
