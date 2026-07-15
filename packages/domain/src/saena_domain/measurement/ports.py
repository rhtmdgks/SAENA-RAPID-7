"""Measurement persistence ports + idempotency semantics + in-memory reference (w5-09).

Spec basis: `docs/architecture/data-ownership.md` (own-schema-per-service +
tenant discriminator, ADR-0007 rev.2 §5), `docs/architecture/contract-catalog.md`
(per-contract idempotency keys), ADR-0013 (event envelope / `idempotency_key`,
at-least-once delivery dedup), ADR-0014 (tenant propagation / `tenant_id`
discriminator). This module is the measurement-domain counterpart of
`saena_domain.persistence.ports` (w2-07) and `saena_vector_store.port` (w4-07):
`typing.Protocol` ports, `tenant_id` as the mandatory FIRST argument of every
tenant-scoped method, `@runtime_checkable` for structural `isinstance`.

## What this module ships

- Frozen domain records: `ConfirmationRecord`, `MeasurementWindow`,
  `OutcomeDecisionRecord`, `EvidenceBundle`. All immutable (frozen dataclass;
  `payload`/`manifest`/`policy_metadata` DEEP-frozen at construction — nested
  dicts become `MappingProxyType`, nested lists become tuples, recursively),
  so a held or returned value can never be mutated, at any nesting depth, to
  corrupt a store.
- Four `typing.Protocol` ports: `ConfirmationStore`,
  `MeasurementWindowStore`, `OutcomeDecisionStore`, `EvidenceBundleStore`.
- Pure in-memory REFERENCE adapters proving the semantics — NO SQL, NO I/O.
  The Postgres adapter lands in w5-10 and MUST pass the same conformance
  suite (`ports_conformance.py`).
- `PutOutcome` (`STORED`/`DUPLICATE`) + `PutResult` so every write reports
  whether it stored new state or was an idempotent replay no-op, without the
  caller having to re-read.
- A journal/replay facility (`journal()`/`snapshot()`/
  `replay_confirmation_journal`) so a restart from the log of ACCEPTED ops
  rebuilds byte-identical state — the durability-restart property adapters
  must preserve.

## Idempotency model (the invariant every adapter enforces)

Every write is keyed. For a given key, exactly one CONTENT can win:

- key ABSENT → the content is stored (`PutOutcome.STORED`).
- key PRESENT, incoming content byte-identical to the stored content (same
  `canonical_json` fingerprint) → an idempotent no-op; the ALREADY-STORED
  record is returned unchanged (`PutOutcome.DUPLICATE`). This is the
  at-least-once replay guarantee: the same event applied twice yields a single
  record.
- key PRESENT, incoming content DIFFERENT → a fail-closed conflict is raised
  (`IdempotencyConflictError` / `AppendOnlyViolationError` /
  `EvidenceHashMismatchError`, per port). NEVER an arbitrary winner, NEVER a
  silent overwrite. The stored content is the FIRST accepted content, always.

Byte-identity is decided by `canonical_json` (JCS-style sorted-key compact
JSON — reused verbatim from `saena_domain.audit.canonical`, the same
canonicalization the audit hash-chain and experiment ledger are built on),
NOT by Python `==`/`is`, so semantically-identical-but-differently-ordered
payloads compare equal.

## Tenant isolation (structural, not conventional)

Every stored value is keyed by a tuple STARTING with `tenant_id`, so a lookup
under a different `tenant_id` is a different key entirely — one tenant can
never observe another's stored data by construction, independent of any `if`
check (matches `saena_vector_store.memory`'s isolation rationale). A
cross-tenant read is therefore a NON-LEAKING absent (`NotFoundError`), never a
leak and never an isolation error (there is nothing to leak — the key is not
even present in the caller's namespace). The one case the key alone cannot
catch — a caller passing a truthful `tenant_id` alongside a RECORD whose own
embedded `tenant_id` claims a DIFFERENT tenant (a "forged tenant id") — is
caught by an explicit `ensure_caller_owns` check that raises
`TenantIsolationError` BEFORE any key is written under either tenant.

## Atomicity / no partial state

`OutcomeDecisionRecord` binds the decision, its `evidence_bundle_ref`, and its
`policy_metadata` into ONE frozen record validated at construction (empty
evidence ref or empty policy metadata is a hard `ValueError`). There is no
per-field setter and no multi-step write path, so a partial decision (a
decision without its evidence, or vice versa) cannot be constructed OR stored
through this port — atomicity is a property of the API shape, not of a runtime
transaction. A write that raises leaves NO trace: the store is mutated only
after every validation has passed, under one lock, so a failed put is a clean
rollback (no half-written record, no phantom key, no journal entry).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from saena_domain.audit.canonical import canonical_json
from saena_domain.measurement.errors import (
    AppendOnlyViolationError,
    EvidenceHashMismatchError,
    IdempotencyConflictError,
    NotFoundError,
    TenantIsolationError,
)

# --- outcome signalling ------------------------------------------------------------


class PutOutcome(Enum):
    """Whether a write stored NEW state or was an idempotent replay no-op."""

    STORED = "stored"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class PutResult:
    """The outcome of a write plus the resolved record.

    `record` is the newly-stored value on `STORED`, or the ALREADY-STORED
    value on `DUPLICATE` (the two are guaranteed byte-identical in the
    `DUPLICATE` case). A conflicting write never returns a `PutResult` — it
    raises, so a caller can never mistake a conflict for a stored/duplicate
    outcome.
    """

    outcome: PutOutcome
    record: Any


# --- frozen domain records ---------------------------------------------------------


def _deep_freeze(value: Any) -> Any:
    """Recursively convert a JSON-shaped value into an immutable form.

    Mappings become `MappingProxyType` over a FRESH dict of deep-frozen values
    (the fresh dict severs the caller's reference — a caller mutating the dict
    they passed in cannot reach into the stored record); lists/tuples become
    tuples of deep-frozen items; scalars pass through. This is a DEEP freeze
    (critic should-fix 1, w5-09 review): a nested `payload["a"]["b"]` dict or
    a nested list is itself immutable after construction, so no code path —
    caller-side or store-side — can mutate stored state in place through a
    held or returned record.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> MappingProxyType[str, Any]:
    """Deep-freeze `value`: a read-only proxy over deep-frozen contents."""
    frozen = _deep_freeze(value)
    assert isinstance(frozen, MappingProxyType)  # value is a Mapping by signature
    return frozen


def _thaw(value: Any) -> Any:
    """Recursively convert a deep-frozen value back to plain dict/list JSON
    shapes. `canonical_json` (stdlib `json.dumps`) cannot serialize
    `MappingProxyType`, so the fingerprint helpers thaw before hashing; tuples
    thaw to lists (the JSON-array form they canonically are, so a record built
    from a list and its frozen tuple round-trip fingerprint identically)."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ConfirmationRecord:
    """A measurement confirmation, keyed by `(tenant_id, confirmation_key)`.

    `confirmation_key` is the idempotency key (ADR-0013 field 8 shape —
    typically `tenant:run:unit`). `payload` is frozen (`MappingProxyType`) so a
    returned record can never be mutated to corrupt the store.
    """

    tenant_id: str
    confirmation_key: str
    measurement_kind: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not self.confirmation_key:
            raise ValueError("confirmation_key is required")
        if not self.measurement_kind:
            raise ValueError("measurement_kind is required")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class MeasurementWindow:
    """An observation window for `(tenant_id, experiment_id)`.

    At most one ACTIVE window may exist per `(tenant_id, experiment_id)` (the
    store enforces this). `ends_at=None` means still open. `starts_at`,
    `ends_at`, and `policy_version` all participate in the byte-identity check,
    so re-opening with any differing field is a conflict.
    """

    tenant_id: str
    experiment_id: str
    starts_at: str
    ends_at: str | None
    policy_version: str

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not self.experiment_id:
            raise ValueError("experiment_id is required")
        if not self.starts_at:
            raise ValueError("starts_at is required")
        if not self.policy_version:
            raise ValueError("policy_version is required")


@dataclass(frozen=True, slots=True)
class OutcomeDecisionRecord:
    """An append-only outcome decision — decision + evidence + policy, ATOMIC.

    The decision (`outcome`), its `evidence_bundle_ref` (a `sha256:` content
    ref into an `EvidenceBundleStore`), and its `policy_metadata` are bound
    together in ONE frozen record validated at construction: an empty evidence
    ref or empty policy metadata is a hard `ValueError`, so a partial decision
    can never be constructed — atomicity by API shape (see module docstring
    "Atomicity / no partial state"). Keyed by `(tenant_id, decision_key)`.
    """

    tenant_id: str
    decision_key: tuple[str, str]
    outcome: str
    evidence_bundle_ref: str
    policy_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not (isinstance(self.decision_key, tuple) and len(self.decision_key) == 2):
            raise ValueError("decision_key must be a 2-tuple (experiment_id, decision_slot)")
        if not all(self.decision_key):
            raise ValueError("decision_key components must be non-empty")
        if not self.outcome:
            raise ValueError("outcome is required")
        if not self.evidence_bundle_ref:
            raise ValueError("evidence_bundle_ref is required (no partial decision state)")
        if not self.policy_metadata:
            raise ValueError("policy_metadata is required (no partial decision state)")
        object.__setattr__(self, "policy_metadata", _freeze_mapping(self.policy_metadata))


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """A content-addressed evidence bundle, stored under a `manifest_hash`.

    `manifest` is frozen (`MappingProxyType`). The `manifest_hash` under which
    a bundle is stored is supplied to `EvidenceBundleStore.put` separately (it
    is the caller-computed content address); this record carries the content.
    """

    tenant_id: str
    manifest: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        object.__setattr__(self, "manifest", _freeze_mapping(self.manifest))


# --- canonical fingerprint helpers -------------------------------------------------


def _confirmation_fingerprint(rec: ConfirmationRecord) -> str:
    return canonical_json(
        {
            "tenant_id": rec.tenant_id,
            "confirmation_key": rec.confirmation_key,
            "measurement_kind": rec.measurement_kind,
            "payload": _thaw(rec.payload),
        }
    )


def _window_fingerprint(w: MeasurementWindow) -> str:
    return canonical_json(
        {
            "tenant_id": w.tenant_id,
            "experiment_id": w.experiment_id,
            "starts_at": w.starts_at,
            "ends_at": w.ends_at,
            "policy_version": w.policy_version,
        }
    )


def _decision_fingerprint(d: OutcomeDecisionRecord) -> str:
    return canonical_json(
        {
            "tenant_id": d.tenant_id,
            "decision_key": list(d.decision_key),
            "outcome": d.outcome,
            "evidence_bundle_ref": d.evidence_bundle_ref,
            "policy_metadata": _thaw(d.policy_metadata),
        }
    )


def _bundle_fingerprint(b: EvidenceBundle) -> str:
    return canonical_json({"tenant_id": b.tenant_id, "manifest": _thaw(b.manifest)})


def _ensure_caller_owns(caller_tenant: str, record_tenant: str, *, key: Any) -> None:
    """Raise `TenantIsolationError` if a record's own tenant_id disagrees with
    the caller-supplied tenant_id (a "forged tenant id" write)."""
    if record_tenant != caller_tenant:
        raise TenantIsolationError(
            f"record claims tenant {record_tenant!r} but caller supplied {caller_tenant!r}",
            context={
                "caller_tenant_id": caller_tenant,
                "record_tenant_id": record_tenant,
                "key": key,
            },
        )


def _require_tenant(tenant_id: str) -> None:
    if not tenant_id:
        raise ValueError("tenant_id is required")


# --- Protocols ---------------------------------------------------------------------


@runtime_checkable
class ConfirmationStore(Protocol):
    """Idempotent measurement-confirmation store, keyed by
    `(tenant_id, confirmation_key)`.

    `put_confirmation` is the single write path; its idempotency model is the
    one described in this module's docstring: absent → stored; byte-identical
    replay → `DUPLICATE` no-op; differing content under the same key →
    `IdempotencyConflictError` (never an arbitrary winner, never an overwrite).
    """

    def put_confirmation(self, tenant_id: str, key: str, record: ConfirmationRecord) -> PutResult:
        """Store `record` under `(tenant_id, key)`.

        Raises `TenantIsolationError` if `record.tenant_id != tenant_id`.
        Raises `IdempotencyConflictError` if `key` already holds a
        byte-DIFFERENT record. Returns `PutResult(STORED, record)` on a fresh
        write or `PutResult(DUPLICATE, stored)` on an identical replay.
        """
        ...

    def get(self, tenant_id: str, key: str) -> ConfirmationRecord:
        """Return the record for `(tenant_id, key)`.

        Raises `NotFoundError` if absent — including when the key exists ONLY
        under a different tenant (a non-leaking absent; there is no way to
        observe another tenant's key existing at all through this port).
        """
        ...


@runtime_checkable
class MeasurementWindowStore(Protocol):
    """At-most-one-active-window store, keyed by `(tenant_id, experiment_id)`."""

    def open_window(self, tenant_id: str, window: MeasurementWindow) -> PutResult:
        """Open `window` for `(tenant_id, window.experiment_id)`.

        Raises `TenantIsolationError` on a forged tenant id. If an active
        window already exists: byte-identical → `DUPLICATE` no-op; any
        differing field → `IdempotencyConflictError`. Returns
        `PutResult(STORED, window)` on the first open.
        """
        ...

    def get_active(self, tenant_id: str, experiment_id: str) -> MeasurementWindow:
        """Return the active window; `NotFoundError` if none (non-leaking absent)."""
        ...


@runtime_checkable
class OutcomeDecisionStore(Protocol):
    """Append-only outcome-decision store, keyed by `(tenant_id, decision_key)`.

    Append-only BY SHAPE: no update/delete method exists. `append_decision`
    stores one atomic `OutcomeDecisionRecord`; an identical replay is a
    `DUPLICATE` no-op, but any attempt to overwrite an existing decision with
    DIFFERENT content raises `AppendOnlyViolationError`.
    """

    def append_decision(self, tenant_id: str, decision: OutcomeDecisionRecord) -> PutResult:
        """Append `decision`. Raises `TenantIsolationError` on a forged tenant
        id, `AppendOnlyViolationError` on a differing overwrite. Identical
        replay → `DUPLICATE`."""
        ...

    def get(self, tenant_id: str, decision_key: tuple[str, str]) -> OutcomeDecisionRecord:
        """Return the decision for `decision_key`; `NotFoundError` if absent
        (non-leaking absent across tenants)."""
        ...

    def list_decisions(self, tenant_id: str) -> tuple[OutcomeDecisionRecord, ...]:
        """Return every decision for `tenant_id` in append order (empty if none)."""
        ...


@runtime_checkable
class EvidenceBundleStore(Protocol):
    """Content-addressed evidence-bundle store, keyed by
    `(tenant_id, manifest_hash)`.

    `put` is idempotent when the stored content under `manifest_hash` is
    identical, and raises `EvidenceHashMismatchError` when the SAME hash is
    presented with DIFFERENT content (a hash collision / integrity violation —
    never a silent overwrite). Still tenant-scoped: a tenant cannot read
    another's bundle by guessing its hash.
    """

    def put(self, tenant_id: str, manifest_hash: str, bundle: EvidenceBundle) -> PutResult:
        """Store `bundle` under `(tenant_id, manifest_hash)`. Raises
        `TenantIsolationError` on a forged tenant id, `EvidenceHashMismatchError`
        on same-hash/different-content. Identical replay → `DUPLICATE`."""
        ...

    def get(self, tenant_id: str, manifest_hash: str) -> EvidenceBundle:
        """Return the bundle for `manifest_hash`; `NotFoundError` if absent
        (non-leaking absent across tenants)."""
        ...


# --- in-memory reference adapters --------------------------------------------------


@dataclass(frozen=True, slots=True)
class _JournalEntry:
    """One ACCEPTED write, in acceptance order — the durability log a restart
    replays. Only writes that actually stored NEW state are journaled;
    idempotent-replay no-ops and conflicting writes are never journaled."""

    tenant_id: str
    key: str
    record: ConfirmationRecord


class InMemoryConfirmationStore:
    """Reference `ConfirmationStore` — a single lock guards a dict keyed by
    `(tenant_id, confirmation_key)`, mirroring
    `saena_domain.persistence.memory`'s in-memory locking convention.

    Also maintains an append-only `_journal` of accepted writes so a restart
    (`replay_confirmation_journal`) rebuilds byte-identical state — the
    durability property a real backend gets from its write-ahead log.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[tuple[str, str], ConfirmationRecord] = {}
        self._fingerprints: dict[tuple[str, str], str] = {}
        self._journal: list[_JournalEntry] = []

    def put_confirmation(self, tenant_id: str, key: str, record: ConfirmationRecord) -> PutResult:
        _require_tenant(tenant_id)
        if not key:
            raise ValueError("key is required")
        _ensure_caller_owns(tenant_id, record.tenant_id, key=key)
        incoming_fp = _confirmation_fingerprint(record)
        store_key = (tenant_id, key)
        with self._lock:
            existing = self._store.get(store_key)
            if existing is not None:
                if self._fingerprints[store_key] == incoming_fp:
                    return PutResult(PutOutcome.DUPLICATE, existing)
                raise IdempotencyConflictError(
                    f"confirmation_key {key!r} for tenant {tenant_id!r} already holds "
                    f"different content",
                    context={"tenant_id": tenant_id, "confirmation_key": key},
                )
            # Fail-closed atomic store: all validation above passed, mutate now.
            self._store[store_key] = record
            self._fingerprints[store_key] = incoming_fp
            self._journal.append(_JournalEntry(tenant_id, key, record))
        return PutResult(PutOutcome.STORED, record)

    def get(self, tenant_id: str, key: str) -> ConfirmationRecord:
        _require_tenant(tenant_id)
        with self._lock:
            record = self._store.get((tenant_id, key))
        if record is None:
            raise NotFoundError(
                f"no confirmation for tenant={tenant_id!r} key={key!r}",
                context={"tenant_id": tenant_id, "confirmation_key": key},
            )
        return record

    def snapshot(self, tenant_id: str) -> dict[str, ConfirmationRecord]:
        """Return a `{confirmation_key: record}` view of `tenant_id`'s stored
        state — used by restart tests to prove two stores are byte-identical."""
        _require_tenant(tenant_id)
        with self._lock:
            return {k: v for (t, k), v in self._store.items() if t == tenant_id}

    def journal(self) -> tuple[_JournalEntry, ...]:
        """Return the append-only log of ACCEPTED writes, in acceptance order."""
        with self._lock:
            return tuple(self._journal)


def replay_confirmation_journal(
    journal: Sequence[_JournalEntry],
) -> InMemoryConfirmationStore:
    """Rebuild an `InMemoryConfirmationStore` by replaying `journal`.

    Replay is idempotent: applying the same journal (or a journal with
    duplicate entries, as an at-least-once log delivery would produce) yields
    the identical state, because each entry re-enters through
    `put_confirmation`, whose byte-identical-replay path is a no-op. A restart
    from the log of accepted ops therefore reconstructs byte-identical state.
    """
    store = InMemoryConfirmationStore()
    for entry in journal:
        store.put_confirmation(entry.tenant_id, entry.key, entry.record)
    return store


class InMemoryMeasurementWindowStore:
    """Reference `MeasurementWindowStore` — one active window per
    `(tenant_id, experiment_id)`, single-lock guarded."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[tuple[str, str], MeasurementWindow] = {}
        self._fingerprints: dict[tuple[str, str], str] = {}

    def open_window(self, tenant_id: str, window: MeasurementWindow) -> PutResult:
        _require_tenant(tenant_id)
        _ensure_caller_owns(tenant_id, window.tenant_id, key=window.experiment_id)
        incoming_fp = _window_fingerprint(window)
        store_key = (tenant_id, window.experiment_id)
        with self._lock:
            existing = self._store.get(store_key)
            if existing is not None:
                if self._fingerprints[store_key] == incoming_fp:
                    return PutResult(PutOutcome.DUPLICATE, existing)
                raise IdempotencyConflictError(
                    f"an active window with different parameters already exists for "
                    f"experiment {window.experiment_id!r} (tenant {tenant_id!r})",
                    context={"tenant_id": tenant_id, "experiment_id": window.experiment_id},
                )
            self._store[store_key] = window
            self._fingerprints[store_key] = incoming_fp
        return PutResult(PutOutcome.STORED, window)

    def get_active(self, tenant_id: str, experiment_id: str) -> MeasurementWindow:
        _require_tenant(tenant_id)
        with self._lock:
            window = self._store.get((tenant_id, experiment_id))
        if window is None:
            raise NotFoundError(
                f"no active window for tenant={tenant_id!r} experiment={experiment_id!r}",
                context={"tenant_id": tenant_id, "experiment_id": experiment_id},
            )
        return window


class InMemoryOutcomeDecisionStore:
    """Reference `OutcomeDecisionStore` — append-only per
    `(tenant_id, decision_key)`, single-lock guarded, insertion order preserved."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # dict preserves insertion order → list_decisions is append-ordered.
        self._store: dict[tuple[str, tuple[str, str]], OutcomeDecisionRecord] = {}
        self._fingerprints: dict[tuple[str, tuple[str, str]], str] = {}

    def append_decision(self, tenant_id: str, decision: OutcomeDecisionRecord) -> PutResult:
        _require_tenant(tenant_id)
        _ensure_caller_owns(tenant_id, decision.tenant_id, key=list(decision.decision_key))
        incoming_fp = _decision_fingerprint(decision)
        store_key = (tenant_id, decision.decision_key)
        with self._lock:
            existing = self._store.get(store_key)
            if existing is not None:
                if self._fingerprints[store_key] == incoming_fp:
                    return PutResult(PutOutcome.DUPLICATE, existing)
                raise AppendOnlyViolationError(
                    f"decision {list(decision.decision_key)!r} for tenant {tenant_id!r} "
                    f"already recorded — append-only, no overwrite",
                    context={
                        "tenant_id": tenant_id,
                        "decision_key": list(decision.decision_key),
                    },
                )
            self._store[store_key] = decision
            self._fingerprints[store_key] = incoming_fp
        return PutResult(PutOutcome.STORED, decision)

    def get(self, tenant_id: str, decision_key: tuple[str, str]) -> OutcomeDecisionRecord:
        _require_tenant(tenant_id)
        with self._lock:
            decision = self._store.get((tenant_id, decision_key))
        if decision is None:
            raise NotFoundError(
                f"no decision for tenant={tenant_id!r} decision_key={list(decision_key)!r}",
                context={"tenant_id": tenant_id, "decision_key": list(decision_key)},
            )
        return decision

    def list_decisions(self, tenant_id: str) -> tuple[OutcomeDecisionRecord, ...]:
        _require_tenant(tenant_id)
        with self._lock:
            return tuple(v for (t, _dk), v in self._store.items() if t == tenant_id)


class InMemoryEvidenceBundleStore:
    """Reference `EvidenceBundleStore` — content-addressed per
    `(tenant_id, manifest_hash)`, single-lock guarded."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[tuple[str, str], EvidenceBundle] = {}
        self._fingerprints: dict[tuple[str, str], str] = {}

    def put(self, tenant_id: str, manifest_hash: str, bundle: EvidenceBundle) -> PutResult:
        _require_tenant(tenant_id)
        if not manifest_hash:
            raise ValueError("manifest_hash is required")
        _ensure_caller_owns(tenant_id, bundle.tenant_id, key=manifest_hash)
        incoming_fp = _bundle_fingerprint(bundle)
        store_key = (tenant_id, manifest_hash)
        with self._lock:
            existing = self._store.get(store_key)
            if existing is not None:
                if self._fingerprints[store_key] == incoming_fp:
                    return PutResult(PutOutcome.DUPLICATE, existing)
                raise EvidenceHashMismatchError(
                    f"manifest_hash {manifest_hash!r} for tenant {tenant_id!r} already "
                    f"resolves to different content (hash collision / integrity violation)",
                    context={"tenant_id": tenant_id, "manifest_hash": manifest_hash},
                )
            self._store[store_key] = bundle
            self._fingerprints[store_key] = incoming_fp
        return PutResult(PutOutcome.STORED, bundle)

    def get(self, tenant_id: str, manifest_hash: str) -> EvidenceBundle:
        _require_tenant(tenant_id)
        with self._lock:
            bundle = self._store.get((tenant_id, manifest_hash))
        if bundle is None:
            raise NotFoundError(
                f"no evidence bundle for tenant={tenant_id!r} manifest_hash={manifest_hash!r}",
                context={"tenant_id": tenant_id, "manifest_hash": manifest_hash},
            )
        return bundle


__all__ = [
    "AppendOnlyViolationError",
    "ConfirmationRecord",
    "ConfirmationStore",
    "EvidenceBundle",
    "EvidenceBundleStore",
    "EvidenceHashMismatchError",
    "IdempotencyConflictError",
    "InMemoryConfirmationStore",
    "InMemoryEvidenceBundleStore",
    "InMemoryMeasurementWindowStore",
    "InMemoryOutcomeDecisionStore",
    "MeasurementWindow",
    "MeasurementWindowStore",
    "NotFoundError",
    "OutcomeDecisionRecord",
    "OutcomeDecisionStore",
    "PutOutcome",
    "PutResult",
    "TenantIsolationError",
    "replay_confirmation_journal",
]
