"""Persistence port Protocols (w2-07).

Spec basis: `docs/architecture/data-ownership.md` (own-DB-or-own-schema per
service, tenant discriminator required on every tenant-scoped record —
ADR-0007 rev.2 §5), `docs/architecture/contract-catalog.md` (per-contract
idempotency keys), ADR-0007 (ownership topology), ADR-0013 (event envelope +
`idempotency_key` field), ADR-0014 (tenant propagation / `tenant_id`
discriminator), `docs/architecture/implementation-waves.md` W2A ("이벤트는
transactional outbox 기록까지 — bus 배선은 2C").

These are `typing.Protocol` interfaces only — no I/O, no SQL, no Kafka. SQL
adapters land in w2-13; the bus (Kafka/Redpanda) publisher wiring lands in
w2-18. `packages/domain/src/saena_domain/persistence/memory.py` provides the
only concrete adapters this patch unit ships: pure in-memory reference
implementations used by tests and by any pre-w2-13/w2-18 caller.

Every TENANT-SCOPED method takes `tenant_id: TenantId` as its FIRST
positional/keyword argument. This is a structural convention, not merely a
docstring promise: adapters MUST verify the target record's own tenant_id
matches the caller-supplied `tenant_id` before returning or mutating it, and
raise `TenantIsolationError` (never a bare "not found") when a caller
supplies a tenant_id that does not own the record it is asking for — see
`saena_domain.persistence.errors.TenantIsolationError` and
`InMemoryTenantRepository`/`InMemoryPlanRepository`/etc. in `memory.py` for
the reference enforcement. `AuditLedgerPort`/`OutboxPort`/`IdempotencyStore`
are tenant-scoped by the `tenant_id` carried on each entry/envelope/key
rather than by a leading parameter, since their unit of storage is an
append-only log/queue keyed by content, not a per-tenant single record — see
each Protocol's own docstring for the exact isolation shape.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from saena_domain.audit import AuditEntry
from saena_domain.identity import TenantContext, TenantId
from saena_domain.policy import DecisionRecord, PlanSnapshot, PlanState

# --- TenantRepository --------------------------------------------------------------


@runtime_checkable
class TenantRepository(Protocol):
    """TenantContext store (contract-catalog.md P0 row 1, owner=tenant-control).

    Idempotency key = `tenant_id+policy_version` per the catalog — this
    Protocol does not itself enforce that composite key (no `policy_version`
    field exists on the runtime `TenantContext` wrapper this module reuses;
    that is a contract-schema-level concern), it only guarantees `put` is
    keyed by `tenant_id` and safely repeatable (upsert semantics: calling
    `put` again with an updated `TenantContext` for the same `tenant_id`
    replaces the stored snapshot, it does not error).
    """

    def put(self, tenant_id: TenantId, context: TenantContext) -> None:
        """Insert or replace the stored `TenantContext` for `tenant_id`.

        Raises `ValueError` if `context.tenant_id != tenant_id` (the caller
        must not be able to smuggle a different tenant's context in under a
        mismatched key).
        """
        ...

    def get(self, tenant_id: TenantId) -> TenantContext:
        """Return the stored `TenantContext` for `tenant_id`.

        Raises `NotFoundError` if no context has been `put` for this
        `tenant_id`. Raises `saena_domain.identity`'s
        `TenantSuspendedError`/`TenantTerminatingError` if the stored
        record's status is not `active` — `TenantContext`'s own
        construction-time status gate (see `saena_domain.identity.tenant`
        module docstring) fires on every `get`, by design: a
        suspended/terminating tenant's context must never be handed back as
        a usable object.
        """
        ...

    def update_status(self, tenant_id: TenantId, status: str) -> TenantContext:
        """Replace the stored context's `status` field, returning the
        updated `TenantContext`.

        Raises `NotFoundError` if `tenant_id` has no stored context. Raises
        `TenantSuspendedError`/`TenantTerminatingError` if `status` is
        `suspended`/`terminating` — same construction-time gate as `get`
        (the new status IS persisted either way; only the returned/
        reconstructed `TenantContext` object is what the gate blocks — a
        caller that wants to persist a suspended status without needing a
        `TenantContext` back should catch this exception, which does not
        undo the write).
        """
        ...


# --- PlanRepository -----------------------------------------------------------------


@runtime_checkable
class PlanRepository(Protocol):
    """ChangePlan snapshot + PlanState + ApprovalDecision store
    (contract-catalog.md P0 rows "ChangePlan"/"ApprovalDecision",
    owner=plan-contract).

    ChangePlan idempotency key = `contract_hash`; ApprovalDecision
    idempotency key = `contract_hash+approver actor_id`
    (`DecisionRecord.decision_key`, `saena_domain.policy`). Every method is
    tenant-scoped (own-schema-per-service + tenant discriminator,
    data-ownership.md).
    """

    def put_plan(self, tenant_id: TenantId, snapshot: PlanSnapshot) -> None:
        """Store `snapshot` keyed by `(tenant_id, snapshot.contract_hash)`.

        Idempotent: storing the identical `PlanSnapshot` (same
        `content_fingerprint`) again for a `contract_hash` already on record
        is a no-op. Storing a snapshot with the SAME `contract_hash` but a
        DIFFERENT `content_fingerprint` is a post-approval immutability
        violation at the domain layer (`saena_domain.policy.
        guard_immutability`) — this port does not itself re-run that guard
        (callers own invoking it before persisting); the port only persists
        whatever `PlanSnapshot` it is given.
        """
        ...

    def get_plan(self, tenant_id: TenantId, contract_hash: str) -> PlanSnapshot:
        """Return the stored `PlanSnapshot` for `(tenant_id, contract_hash)`.

        Raises `NotFoundError` if absent, `TenantIsolationError` if
        `contract_hash` exists but under a different tenant.
        """
        ...

    def get_state(self, tenant_id: TenantId, contract_hash: str) -> PlanState:
        """Return the current `PlanState` for `(tenant_id, contract_hash)`.

        Raises `NotFoundError` if no state has been set yet for this plan.
        """
        ...

    def set_state(self, tenant_id: TenantId, contract_hash: str, state: PlanState) -> None:
        """Set the current `PlanState` for `(tenant_id, contract_hash)`.

        Unconditional set (the state-machine legality of the transition is
        `saena_domain.policy.transition`'s responsibility, not this port's —
        this port is a dumb key-value write once the domain layer has
        already computed the next state).
        """
        ...

    def record_decision(self, tenant_id: TenantId, decision: DecisionRecord) -> DecisionRecord:
        """Idempotently record `decision`, keyed by `decision.decision_key`.

        - New key: stores and returns `decision` unchanged.
        - Existing key, identical `decision` value on the stored record:
          idempotent replay — returns the ALREADY-STORED record unchanged
          (no duplicate write).
        - Existing key, different `decision` value: raises
          `DecisionConflictError` (mirrors
          `saena_domain.policy.transition`'s `ConflictingDecisionError` at
          the persistence layer).
        """
        ...

    def get_decisions(self, tenant_id: TenantId, contract_hash: str) -> tuple[DecisionRecord, ...]:
        """Return every recorded decision for `(tenant_id, contract_hash)`,
        in insertion order. Empty tuple if none recorded yet."""
        ...


# --- AuditLedgerPort -----------------------------------------------------------------


@runtime_checkable
class AuditLedgerPort(Protocol):
    """Append-only audit hash-chain store (contract-catalog.md P0 row
    "AuditEvent", owner=audit-ledger).

    Idempotency key = "event hash (chain)". This Protocol is APPEND-ONLY BY
    SHAPE: it declares no update/delete method at all — there is no method
    signature on this Protocol capable of mutating or removing a
    already-appended entry, matching the contract's "contractual, immutable
    role" retention note. `append` enforces hash-chain continuity via
    `saena_domain.audit.append_entry`/`compute_entry_hash` — an entry whose
    `prev_event_hash` does not match the current tail, or whose `event_hash`
    does not match its own recomputed content hash, is rejected before it
    ever enters storage.
    """

    def append(self, entry: AuditEntry) -> AuditEntry:
        """Append `entry`, verifying it links to the current chain tail.

        Raises `ValueError` (propagated from `saena_domain.audit.
        append_entry`) if `entry` does not correctly extend the chain.
        Scope isolation: `entry.scope == "tenant"` entries are isolated per
        `entry.tenant_id`; `entry.scope == "system"` entries share one
        system-wide chain. Returns the appended `entry` unchanged.
        """
        ...

    def read_range(
        self,
        *,
        tenant_id: TenantId | None = None,
        start_index: int = 0,
        end_index: int | None = None,
    ) -> tuple[AuditEntry, ...]:
        """Return entries `[start_index, end_index)` from the relevant chain.

        `tenant_id=None` reads the system-scope chain; a given `tenant_id`
        reads that tenant's own chain — the two chains are never mixed in one
        call. `end_index=None` reads through the current tail.
        """
        ...

    def verify(self, *, tenant_id: TenantId | None = None) -> tuple[bool, int | None]:
        """Verify the relevant chain's hash-chain integrity.

        Same `tenant_id=None`-means-system-scope convention as `read_range`.
        Returns `(True, None)` if intact, or `(False, i)` naming the first
        failing index — mirrors `saena_domain.audit.verify_chain`.
        """
        ...


# --- DecisionRecordPort --------------------------------------------------------------


@runtime_checkable
class DecisionRecordPort(Protocol):
    """Policy-gate approval decisions, keyed idempotently.

    Distinct from `PlanRepository.record_decision`/`get_decisions` (which
    are plan-contract-owned, ChangePlan-scoped storage): this port models
    the policy-gate service's OWN idempotent decision log — e.g. gate
    pre-verification outcomes (ADR-0003 step 2) that the policy-gate service
    itself is the system of record for, independent of plan-contract's plan
    store. Keyed the same way (`DecisionRecord.decision_key`) so the two
    services can cross-check without disagreeing on what "the same decision"
    means.
    """

    def record(self, tenant_id: TenantId, decision: DecisionRecord) -> DecisionRecord:
        """Idempotently record `decision` — same conflict/replay semantics as
        `PlanRepository.record_decision` (see that method's docstring)."""
        ...

    def get(self, tenant_id: TenantId, decision_key: tuple[str, str]) -> DecisionRecord:
        """Return the recorded decision for `decision_key`.

        Raises `NotFoundError` if no decision has been recorded for this key.
        """
        ...


# --- ArtifactManifestPort -------------------------------------------------------------


@runtime_checkable
class ArtifactManifestPort(Protocol):
    """Immutable PatchArtifact manifest store (contract-catalog.md P0 row
    "PatchArtifact", owner=artifact-registry — manifest only; blob content
    itself is object storage, out of this port's scope per data-ownership.md
    "blob 쓰기 단일 관문 = artifact-registry").

    Idempotency key = `patch_unit_id+worktree_commit`. Put-once by that
    composite key: a second `put` under the same key with IDENTICAL content
    is an idempotent no-op (safe retry after a network blip); a second `put`
    under the same key with DIFFERENT content is rejected
    (`DuplicateManifestError`) — the whole point of a manifest is that it
    never silently changes underneath a `(patch_unit_id, worktree_commit)`
    reference once written.
    """

    def put(
        self,
        tenant_id: TenantId,
        patch_unit_id: str,
        worktree_commit: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Store `manifest` under `(tenant_id, patch_unit_id, worktree_commit)`.

        Returns the stored manifest (either the newly-written one, or the
        pre-existing one on an idempotent-replay no-op — the two are
        guaranteed equal in that case). Raises `DuplicateManifestError` if
        the key already holds a DIFFERENT manifest.
        """
        ...

    def get(self, tenant_id: TenantId, patch_unit_id: str, worktree_commit: str) -> dict[str, Any]:
        """Return the stored manifest for the given key.

        Raises `NotFoundError` if absent, `TenantIsolationError` if the key
        exists under a different tenant.
        """
        ...


# --- OutboxPort -------------------------------------------------------------------


@runtime_checkable
class OutboxPort(Protocol):
    """Transactional outbox — RECORDING ONLY (W2A scope; bus wiring is w2-18).

    `record` validates the given mapping is a structurally valid SAENA event
    envelope (`saena_domain.events` dual jsonschema+pydantic validation) —
    an invalid envelope is rejected with `OutboxValidationError` before it
    is ever stored, so nothing malformed can reach a future w2-18 bus
    publisher reading from this outbox. This Protocol deliberately has no
    "publish" method: `mark_published` only flips an internal bookkeeping
    flag this port owns, it does not talk to Kafka/Redpanda (that dispatch
    loop is out of scope for w2-07, see the module docstring).
    """

    def record(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Validate and store `envelope`.

        Idempotent by `envelope["event_id"]`: recording the identical
        envelope again for an `event_id` already on record is a no-op (the
        `event_id` doubles as the outbox's own idempotency key alongside the
        envelope's own `idempotency_key` field). Raises
        `OutboxValidationError` if `envelope` fails envelope validation.
        Returns the stored envelope.
        """
        ...

    def list_pending(self, tenant_id: TenantId | None = None) -> tuple[dict[str, Any], ...]:
        """Return every recorded envelope not yet marked published.

        `tenant_id=None` returns pending envelopes across every tenant plus
        system/aggregate-context envelopes; a given `tenant_id` filters to
        that tenant's `context_type: tenant` envelopes only.
        """
        ...

    def mark_published(self, event_id: str) -> None:
        """Mark the envelope with this `event_id` as published (bookkeeping
        only — does not itself publish to any bus).

        Raises `NotFoundError` if no envelope with this `event_id` has been
        recorded.
        """
        ...


# --- IdempotencyStore ---------------------------------------------------------------


@runtime_checkable
class IdempotencyStore(Protocol):
    """Event-consumer dedup store keyed by an event's `idempotency_key`.

    ADR-0013 field 8, "at-least-once 배달 하의 중복 제거 키" — a downstream
    consumer calls `seen` before processing an inbound event and `mark`
    after successfully processing it, so a redelivered event is skipped
    rather than double-applied.
    """

    def seen(self, tenant_id: TenantId, idempotency_key: str) -> bool:
        """Return whether `idempotency_key` has already been `mark`-ed for
        this tenant."""
        ...

    def mark(self, tenant_id: TenantId, idempotency_key: str) -> None:
        """Record `idempotency_key` as seen for this tenant.

        Idempotent: marking the same key twice is a no-op, not an error.
        """
        ...


__all__ = [
    "ArtifactManifestPort",
    "AuditLedgerPort",
    "DecisionRecordPort",
    "IdempotencyStore",
    "OutboxPort",
    "PlanRepository",
    "TenantRepository",
]
