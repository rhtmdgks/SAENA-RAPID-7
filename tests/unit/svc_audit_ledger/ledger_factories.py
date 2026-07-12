"""Factory helpers for `saena_audit_ledger` HTTP boundary tests.

See `tests/unit/domain_persistence/persistence_factories.py`'s own docstring
for why this lives under a unique dotted name rather than `conftest.py`.
"""

from __future__ import annotations

from typing import Any

TENANT_A = "acme-co"
TENANT_B = "globex-co"

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def make_append_body(**overrides: Any) -> dict[str, Any]:
    """A schema-valid `POST /v1/audit/entries` request body."""
    body: dict[str, Any] = {
        "action": "patch.unit.completed.v1",
        "recorded_at": "2026-07-12T09:14:32Z",
        "scope": "tenant",
        "trace_id": TRACE_ID,
        "payload": {"patch_unit_id": "w2-10-audit-ledger"},
        "tenant_id": TENANT_A,
        "run_id": "run-2026-0712-0007",
    }
    body.update(overrides)
    return body


def roles_header(*roles: str) -> dict[str, str]:
    return {"X-Saena-Roles": ",".join(roles)}


def tenant_header(tenant_id: str) -> dict[str, str]:
    return {"X-Saena-Tenant-Id": tenant_id}
