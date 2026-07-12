"""IdempotentConsumer — consumer-side dedup on redelivery (W2C exit criterion).

Spec basis: `docs/architecture/implementation-waves.md` W2C exit ("...
consumer idempotency"), ADR-0013 field 8 (`idempotency_key`, "at-least-once
배달 하의 중복 제거 키"), `saena_domain.persistence.IdempotencyStore` (the
dedup store Protocol this wraps — already shipped in w2-07/w2-13, this module
is the CONSUMER-side usage of it the outbox/bus round-trip needed).

`IdempotentConsumer.process(envelope, handler)`:

1. Reads `envelope["idempotency_key"]` (every ADR-0013 v1 envelope carries
   this field — the 8th common, frozen field).
2. If the key has already been `mark`-ed for this envelope's owning tenant
   scope, `handler` is SKIPPED entirely (redelivery — at-least-once transport
   means the SAME envelope can legitimately arrive more than once; the
   handler must run exactly once from the consumer's point of view).
3. Otherwise `handler(envelope)` runs, and ONLY on successful (non-raising)
   completion is the key `mark`-ed — a handler that raises leaves the key
   unmarked, so a subsequent redelivery of the SAME envelope (or an explicit
   retry) still gets a chance to actually process it, rather than being
   silently swallowed by a dedup entry written before the handler proved it
   succeeded.

Tenant scoping for the dedup key's scope: `IdempotencyStore.seen`/`mark` take
`tenant_id: TenantId` (non-optional) per `saena_domain.persistence.ports`.
`context_type: tenant` envelopes use their own `tenant_id`;
`system`/`aggregate` envelopes carry no `tenant_id` at all, so this module
uses a fixed sentinel `TenantId` (`SYSTEM_SCOPE_TENANT_ID`, a
schema-valid-looking slug that this module treats purely as a dedup
namespace key — it is never a real tenant, never appears in any tenant
registry, and is never propagated to any tenant-scoped port beyond this
consumer's own `IdempotencyStore` calls) so system/aggregate envelopes get
their own consistent dedup namespace, separate from every real tenant's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from saena_domain.identity import TenantId
from saena_domain.persistence import IdempotencyStore

#: Dedup namespace for `context_type: system`/`aggregate` envelopes, which
#: structurally carry no `tenant_id` (see module docstring).
SYSTEM_SCOPE_TENANT_ID = TenantId("saena-system-scope")

Handler = Callable[[dict[str, Any]], Awaitable[None]]


def _dedup_scope(envelope: dict[str, Any]) -> TenantId:
    if envelope.get("context_type") == "tenant":
        owner = envelope.get("tenant_id")
        if isinstance(owner, str) and owner:
            return TenantId(owner)
    return SYSTEM_SCOPE_TENANT_ID


class IdempotentConsumer:
    """Wraps an `IdempotencyStore` to dedup `handler` invocation per envelope
    `idempotency_key` — a redelivered envelope runs `handler` at most once.
    """

    def __init__(self, store: IdempotencyStore) -> None:
        self._store = store

    async def process(self, envelope: dict[str, Any], handler: Handler) -> bool:
        """Run `handler(envelope)` unless `envelope`'s `idempotency_key` has
        already been marked seen for its owning dedup scope.

        Returns `True` if `handler` actually ran (first delivery, or a prior
        attempt raised and left the key unmarked), `False` if this call was a
        no-op dedup skip (redelivery of an already-successfully-processed
        envelope).
        """
        idempotency_key = envelope["idempotency_key"]
        scope = _dedup_scope(envelope)

        if self._store.seen(scope, idempotency_key):
            return False

        await handler(envelope)
        self._store.mark(scope, idempotency_key)
        return True


__all__ = ["Handler", "IdempotentConsumer", "SYSTEM_SCOPE_TENANT_ID"]
