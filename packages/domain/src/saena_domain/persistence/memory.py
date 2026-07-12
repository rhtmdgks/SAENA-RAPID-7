"""In-memory reference adapters for every `saena_domain.persistence` port.

Pure-Python reference implementations — no SQL, no Kafka, no network I/O
(SQL adapters land in w2-13; the bus publisher lands in w2-18, per this
patch unit's scope note in `ports.py`'s module docstring). Used by tests and
by any caller that does not yet need real persistence.

Tenant isolation (ADR-0014 discriminator, data-ownership.md): every
tenant-scoped adapter stores records keyed by `(tenant_id, ...)` internally
and raises `TenantIsolationError` — never a bare `NotFoundError` — when a
caller supplies a `tenant_id` that does not own the record referenced by the
rest of the key. This distinguishes "never existed" from "exists, but not
yours" at the type level, matching the exclusive-write-path instruction's
"accessing tenant B data with tenant A id -> TenantIsolationError" mandate.
"""

from __future__ import annotations

import threading
from typing import Any

from pydantic import ValidationError
from saena_schemas.envelope.event_envelope_v1 import SaenaEventEnvelopeV1

from saena_domain.audit import AuditEntry, guard_payload
from saena_domain.audit import append_entry as _audit_append_entry
from saena_domain.audit import verify_chain as _audit_verify_chain
from saena_domain.events._validation import jsonschema_errors
from saena_domain.identity import TenantContext, TenantId
from saena_domain.persistence.errors import (
    DecisionConflictError,
    DuplicateManifestError,
    NotFoundError,
    OutboxValidationError,
    TenantIsolationError,
)
from saena_domain.policy import DecisionRecord, PlanSnapshot, PlanState

# --- TenantRepository ----------------------------------------------------------------


class InMemoryTenantRepository:
    """Reference `TenantRepository` — one stored payload per `tenant_id`.

    Stores the RAW `TenantContext` payload (`dict`), not the gated
    `TenantContext` wrapper object, as its source of truth. This is
    deliberate: `TenantContext.__init__` fails closed for
    `suspended`/`terminating` status (`saena_domain.identity.tenant`'s own
    module docstring — "a suspended tenant's context should never reach
    business logic that assumes an active tenant"), so a repository that
    stored only the wrapper could never represent (or later retrieve) a
    suspended/terminating tenant at all — `update_status(..., "suspended")`
    would have nothing valid to construct. Storing the raw payload and
    reconstructing `TenantContext.from_payload(...)` on every `get`/
    `update_status` call means those identity-layer gates fire naturally and
    consistently at read time, exactly as `saena_domain.identity` intends:
    reading a suspended tenant's context raises `TenantSuspendedError`
    rather than silently handing back a usable-looking object.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, Any]] = {}

    def put(self, tenant_id: TenantId, context: TenantContext) -> None:
        if context.tenant_id.value != tenant_id.value:
            raise ValueError(
                f"context.tenant_id {context.tenant_id.value!r} does not match "
                f"the supplied tenant_id {tenant_id.value!r}"
            )
        payload = context.model.model_dump(mode="json")
        with self._lock:
            self._store[tenant_id.value] = payload

    def get(self, tenant_id: TenantId) -> TenantContext:
        with self._lock:
            payload = self._store.get(tenant_id.value)
        if payload is None:
            raise NotFoundError(
                f"no TenantContext stored for tenant_id {tenant_id.value!r}",
                context={"tenant_id": tenant_id.value},
            )
        return TenantContext.from_payload(dict(payload))

    def update_status(self, tenant_id: TenantId, status: str) -> TenantContext:
        with self._lock:
            payload = self._store.get(tenant_id.value)
            if payload is None:
                raise NotFoundError(
                    f"no TenantContext stored for tenant_id {tenant_id.value!r}",
                    context={"tenant_id": tenant_id.value},
                )
            updated_payload = dict(payload)
            updated_payload["status"] = status
            self._store[tenant_id.value] = updated_payload
        return TenantContext.from_payload(dict(updated_payload))


# --- PlanRepository --------------------------------------------------------------------


class InMemoryPlanRepository:
    """Reference `PlanRepository` — plan snapshots/state/decisions keyed by
    `(tenant_id, contract_hash)` / `(tenant_id, decision_key)`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plans: dict[str, dict[str, PlanSnapshot]] = {}
        self._states: dict[str, dict[str, PlanState]] = {}
        self._decisions: dict[str, dict[tuple[str, str], DecisionRecord]] = {}
        self._decision_order: dict[str, list[tuple[str, str]]] = {}

    def _tenant_plans(self, tenant_id: TenantId) -> dict[str, PlanSnapshot]:
        return self._plans.setdefault(tenant_id.value, {})

    def _tenant_states(self, tenant_id: TenantId) -> dict[str, PlanState]:
        return self._states.setdefault(tenant_id.value, {})

    def _tenant_decisions(self, tenant_id: TenantId) -> dict[tuple[str, str], DecisionRecord]:
        return self._decisions.setdefault(tenant_id.value, {})

    def _assert_owned(
        self, tenant_id: TenantId, contract_hash: str, index: dict[str, dict[str, Any]]
    ) -> None:
        for other_tenant, records in index.items():
            if other_tenant != tenant_id.value and contract_hash in records:
                raise TenantIsolationError(
                    f"contract_hash {contract_hash!r} belongs to a different tenant",
                    context={"requested_tenant_id": tenant_id.value},
                )

    def put_plan(self, tenant_id: TenantId, snapshot: PlanSnapshot) -> None:
        with self._lock:
            self._assert_owned(tenant_id, snapshot.contract_hash, self._plans)
            self._tenant_plans(tenant_id)[snapshot.contract_hash] = snapshot

    def get_plan(self, tenant_id: TenantId, contract_hash: str) -> PlanSnapshot:
        with self._lock:
            self._assert_owned(tenant_id, contract_hash, self._plans)
            snapshot = self._tenant_plans(tenant_id).get(contract_hash)
        if snapshot is None:
            raise NotFoundError(
                f"no ChangePlan stored for contract_hash {contract_hash!r}",
                context={"tenant_id": tenant_id.value, "contract_hash": contract_hash},
            )
        return snapshot

    def get_state(self, tenant_id: TenantId, contract_hash: str) -> PlanState:
        with self._lock:
            self._assert_owned(tenant_id, contract_hash, self._states)
            state = self._tenant_states(tenant_id).get(contract_hash)
        if state is None:
            raise NotFoundError(
                f"no PlanState stored for contract_hash {contract_hash!r}",
                context={"tenant_id": tenant_id.value, "contract_hash": contract_hash},
            )
        return state

    def set_state(self, tenant_id: TenantId, contract_hash: str, state: PlanState) -> None:
        with self._lock:
            self._assert_owned(tenant_id, contract_hash, self._states)
            self._tenant_states(tenant_id)[contract_hash] = state

    def record_decision(self, tenant_id: TenantId, decision: DecisionRecord) -> DecisionRecord:
        key = decision.decision_key
        with self._lock:
            for other_tenant, records in self._decisions.items():
                if other_tenant != tenant_id.value and key in records:
                    raise TenantIsolationError(
                        f"decision key {key!r} belongs to a different tenant",
                        context={"requested_tenant_id": tenant_id.value},
                    )
            decisions = self._tenant_decisions(tenant_id)
            prior = decisions.get(key)
            if prior is not None:
                if prior.decision == decision.decision:
                    return prior
                raise DecisionConflictError(
                    f"conflicting decision for key {key!r}: "
                    f"{prior.decision!r} then {decision.decision!r}",
                    context={"tenant_id": tenant_id.value, "decision_key": list(key)},
                )
            decisions[key] = decision
            self._decision_order.setdefault(tenant_id.value, []).append(key)
            return decision

    def get_decisions(self, tenant_id: TenantId, contract_hash: str) -> tuple[DecisionRecord, ...]:
        with self._lock:
            decisions = self._tenant_decisions(tenant_id)
            order = self._decision_order.get(tenant_id.value, [])
            return tuple(
                decisions[key] for key in order if key[0] == contract_hash and key in decisions
            )


# --- AuditLedgerPort ---------------------------------------------------------------


class InMemoryAuditLedger:
    """Reference `AuditLedgerPort` — one system-scope chain plus one
    per-tenant chain, each strictly append-only (no mutation/removal method
    exists on this class beyond `append`; the internal lists are only ever
    grown via `saena_domain.audit.append_entry`, which itself rejects any
    entry that would break the chain).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._system_chain: list[AuditEntry] = []
        self._tenant_chains: dict[str, list[AuditEntry]] = {}

    def _chain_for(self, tenant_id: TenantId | None) -> list[AuditEntry]:
        if tenant_id is None:
            return self._system_chain
        return self._tenant_chains.setdefault(tenant_id.value, [])

    def append(self, entry: AuditEntry) -> AuditEntry:
        guard_payload(entry.payload)
        tenant_id = TenantId(entry.tenant_id.root) if entry.tenant_id is not None else None
        with self._lock:
            chain = self._chain_for(tenant_id)
            updated = _audit_append_entry(chain, entry)
            if tenant_id is None:
                self._system_chain = updated
            else:
                self._tenant_chains[tenant_id.value] = updated
        return entry

    def read_range(
        self,
        *,
        tenant_id: TenantId | None = None,
        start_index: int = 0,
        end_index: int | None = None,
    ) -> tuple[AuditEntry, ...]:
        with self._lock:
            chain = tuple(self._chain_for(tenant_id))
        stop = end_index if end_index is not None else len(chain)
        return chain[start_index:stop]

    def verify(self, *, tenant_id: TenantId | None = None) -> tuple[bool, int | None]:
        with self._lock:
            chain = list(self._chain_for(tenant_id))
        return _audit_verify_chain(chain)

    # --- test-only tamper simulation -------------------------------------------------
    #
    # No PUBLIC mutation method exists on this class — the append-only
    # invariant holds for every normal caller. Tests that need to prove
    # `verify()` actually detects tampering (rather than trivially always
    # passing) reach into `_system_chain`/`_tenant_chains` directly, which is
    # exactly what "private attribute" means: accessible from the same
    # process for a white-box test, never part of this class's public
    # contract.


# --- DecisionRecordPort --------------------------------------------------------------


class InMemoryDecisionRecordStore:
    """Reference `DecisionRecordPort` — policy-gate's own idempotent decision log."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[tuple[str, str], DecisionRecord]] = {}

    def record(self, tenant_id: TenantId, decision: DecisionRecord) -> DecisionRecord:
        key = decision.decision_key
        with self._lock:
            tenant_store = self._store.setdefault(tenant_id.value, {})
            prior = tenant_store.get(key)
            if prior is not None:
                if prior.decision == decision.decision:
                    return prior
                raise DecisionConflictError(
                    f"conflicting decision for key {key!r}: "
                    f"{prior.decision!r} then {decision.decision!r}",
                    context={"tenant_id": tenant_id.value, "decision_key": list(key)},
                )
            tenant_store[key] = decision
            return decision

    def get(self, tenant_id: TenantId, decision_key: tuple[str, str]) -> DecisionRecord:
        with self._lock:
            tenant_store = self._store.get(tenant_id.value, {})
            record = tenant_store.get(decision_key)
        if record is None:
            raise NotFoundError(
                f"no decision recorded for key {decision_key!r}",
                context={"tenant_id": tenant_id.value, "decision_key": list(decision_key)},
            )
        return record


# --- ArtifactManifestPort -------------------------------------------------------------


class InMemoryArtifactManifestStore:
    """Reference `ArtifactManifestPort` — put-once by
    `(tenant_id, patch_unit_id, worktree_commit)`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # tenant_id -> (patch_unit_id, worktree_commit) -> manifest
        self._store: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}

    def put(
        self,
        tenant_id: TenantId,
        patch_unit_id: str,
        worktree_commit: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        key = (patch_unit_id, worktree_commit)
        with self._lock:
            for other_tenant, records in self._store.items():
                if other_tenant != tenant_id.value and key in records:
                    raise TenantIsolationError(
                        f"manifest key {key!r} belongs to a different tenant",
                        context={"requested_tenant_id": tenant_id.value},
                    )
            tenant_store = self._store.setdefault(tenant_id.value, {})
            existing = tenant_store.get(key)
            if existing is not None:
                if existing == manifest:
                    return existing
                raise DuplicateManifestError(
                    f"manifest key {key!r} already stored with different content",
                    context={
                        "tenant_id": tenant_id.value,
                        "patch_unit_id": patch_unit_id,
                        "worktree_commit": worktree_commit,
                    },
                )
            stored = dict(manifest)
            tenant_store[key] = stored
            return stored

    def get(self, tenant_id: TenantId, patch_unit_id: str, worktree_commit: str) -> dict[str, Any]:
        key = (patch_unit_id, worktree_commit)
        with self._lock:
            for other_tenant, records in self._store.items():
                if other_tenant != tenant_id.value and key in records:
                    raise TenantIsolationError(
                        f"manifest key {key!r} belongs to a different tenant",
                        context={"requested_tenant_id": tenant_id.value},
                    )
            manifest = self._store.get(tenant_id.value, {}).get(key)
        if manifest is None:
            raise NotFoundError(
                f"no manifest stored for key {key!r}",
                context={
                    "tenant_id": tenant_id.value,
                    "patch_unit_id": patch_unit_id,
                    "worktree_commit": worktree_commit,
                },
            )
        return manifest


# --- OutboxPort -------------------------------------------------------------------


def _validate_envelope(envelope: dict[str, Any]) -> None:
    """Validate `envelope` the same dual (jsonschema + pydantic) way
    `saena_domain.events.EnvelopeFactory` does, without re-synthesizing any
    field — this is a pure validate-as-given check, not a builder."""
    messages = jsonschema_errors(envelope)
    try:
        SaenaEventEnvelopeV1.model_validate(envelope)
    except ValidationError as exc:
        messages.append(f"pydantic: {exc}")
    if messages:
        raise OutboxValidationError(
            "envelope failed dual validation: " + "; ".join(messages),
            context={"messages": messages, "event_id": envelope.get("event_id")},
        )


class InMemoryOutbox:
    """Reference `OutboxPort` — RECORDING ONLY (W2A scope, see module docstring).

    Forbidden-data guard: `saena_domain.audit.guard_payload` is invoked on
    `envelope["payload"]` at record time (credentials/stack traces/PII must
    never enter the outbox, same runtime gate audit entries get — the outbox
    is itself a durable, at-least-once-replayed store, so the same
    guard applies).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._published: set[str] = set()

    def record(self, envelope: dict[str, Any]) -> dict[str, Any]:
        _validate_envelope(envelope)
        guard_payload(envelope.get("payload", {}))
        event_id = envelope["event_id"]
        with self._lock:
            existing = self._entries.get(event_id)
            if existing is not None:
                if existing == envelope:
                    return existing
                raise OutboxValidationError(
                    f"event_id {event_id!r} already recorded with a different envelope",
                    context={"event_id": event_id},
                )
            stored = dict(envelope)
            self._entries[event_id] = stored
            self._order.append(event_id)
            return stored

    def list_pending(self, tenant_id: TenantId | None = None) -> tuple[dict[str, Any], ...]:
        with self._lock:
            pending = [
                self._entries[event_id]
                for event_id in self._order
                if event_id not in self._published
            ]
        if tenant_id is None:
            return tuple(pending)
        return tuple(
            envelope
            for envelope in pending
            if envelope.get("context_type") == "tenant"
            and envelope.get("tenant_id") == tenant_id.value
        )

    def mark_published(self, event_id: str) -> None:
        with self._lock:
            if event_id not in self._entries:
                raise NotFoundError(
                    f"no outbox entry recorded for event_id {event_id!r}",
                    context={"event_id": event_id},
                )
            self._published.add(event_id)


# --- IdempotencyStore ---------------------------------------------------------------


class InMemoryIdempotencyStore:
    """Reference `IdempotencyStore` — per-tenant set of seen idempotency keys."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, set[str]] = {}

    def seen(self, tenant_id: TenantId, idempotency_key: str) -> bool:
        with self._lock:
            return idempotency_key in self._store.get(tenant_id.value, set())

    def mark(self, tenant_id: TenantId, idempotency_key: str) -> None:
        with self._lock:
            self._store.setdefault(tenant_id.value, set()).add(idempotency_key)


__all__ = [
    "InMemoryArtifactManifestStore",
    "InMemoryAuditLedger",
    "InMemoryDecisionRecordStore",
    "InMemoryIdempotencyStore",
    "InMemoryOutbox",
    "InMemoryPlanRepository",
    "InMemoryTenantRepository",
]
