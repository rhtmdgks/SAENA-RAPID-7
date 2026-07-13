"""Shared constants/factory helpers for `tests/unit/svc_tenant_control`.

Deliberately NOT named `conftest.py`'s own module surface — pytest's default
`prepend` import mode inserts each directory containing a `conftest.py` onto
`sys.path` and imports it under the bare top-level name `conftest`; a SECOND
directory doing `from conftest import ...` while ALSO having its own
`conftest.py` collides with whichever `conftest` module Python's import
cache already holds when the full `tests/unit` suite is collected together
(same failure mode documented in
`tests/unit/domain_persistence/persistence_factories.py`'s own docstring —
proven empirically here too: `ImportError: cannot import name 'HEADER_NAME'
from 'conftest'` when collected alongside `tests/unit/domain_identity`).
This module is imported by its own unique dotted name
(`tenant_control_factories`, inserted onto `sys.path` by `conftest.py` in
this same directory) to avoid that collision entirely.
"""

from __future__ import annotations

TENANT_A = "acme-co"
TENANT_B = "globex-co"

HEADER_NAME = "X-Saena-Tenant-Id"


def create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": TENANT_A,
        "display_name": "Acme Co",
        "isolation_profile": "internal-k3s",
        "policy_version": "1.0.0",
        "engine_scope": ["chatgpt-search"],
        "retention_policy_ref": "retention-policy-default",
    }
    payload.update(overrides)
    return payload
