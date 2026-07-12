"""In-memory `AuditTrailRecord` store — this service's own audit descriptor
buffer, keyed by `(tenant_id, contract_hash)`.

`saena_domain.policy.audit.AuditTrailRecord` (see that module's docstring) is
explicitly a "plain descriptor... it does not write to any ledger" — actual
`AuditEvent` hash-chain append is `audit-ledger-service`'s exclusive-write
domain (`saena_domain.audit`/`AuditLedgerPort`), and this service must not
import `saena_audit_ledger` or reach into another service's storage
(services-are-independent, `.importlinter`). Until an audit-ledger HTTP
client/outbox-consumer wiring exists (out of this patch unit's scope, same
boundary note as `gate_client.py`), this module is plan-contract-service's
own local record of "what audit descriptors this service produced" — exposed
read-only via `GET /v1/plans/{contract_hash}` per this unit's task spec
("state + decisions"), not a substitute for the real audit ledger.
"""

from __future__ import annotations

import threading

from saena_domain.identity import TenantId
from saena_domain.policy import AuditTrailRecord


class AuditTrailStore:
    """Append-only, tenant-scoped, in-process `AuditTrailRecord` buffer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, list[AuditTrailRecord]]] = {}

    def append(self, tenant_id: TenantId, record: AuditTrailRecord) -> None:
        with self._lock:
            tenant_records = self._records.setdefault(tenant_id.value, {})
            tenant_records.setdefault(record.contract_hash, []).append(record)

    def list_for_plan(
        self, tenant_id: TenantId, contract_hash: str
    ) -> tuple[AuditTrailRecord, ...]:
        with self._lock:
            return tuple(self._records.get(tenant_id.value, {}).get(contract_hash, ()))


__all__ = ["AuditTrailStore"]
