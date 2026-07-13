"""saena_audit_ledger — append-only hash-chain audit trail service (w2-10).

Public surface: `create_app` (FastAPI app factory, `saena_audit_ledger.app`)
bound to a `saena_domain.persistence.AuditLedgerPort` implementation. See
`app.py`'s module docstring for endpoint list, spec basis, and documented
W2A scope boundaries (authN stub, PROPOSED outbox topic).
"""

from __future__ import annotations

from saena_audit_ledger.app import create_app

__all__ = ["create_app"]
