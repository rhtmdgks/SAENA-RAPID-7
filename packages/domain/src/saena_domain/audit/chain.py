"""Append-only audit hash-chain: entry model, builder, and verifier.

`AuditEntry` mirrors the `AuditEvent` contract fields (`packages/contracts/
json-schema/domain/audit-event/v1/audit-event.schema.json`,
`packages/schemas/saena_schemas/domain/audit_event_v1`) plus the R9-1
scope/tenant_id/run_id conditional rules from that schema's `allOf` block:
`scope="tenant"` requires `tenant_id`; `scope="system"` forbids both
`tenant_id` and `run_id`.

This module owns pure chain-building/verification logic only.
`InMemoryAuditChain` is the reference append-only store used by tests and by
callers that do not yet need persistence — real persistence ports land in
w2-07 and are expected to wrap `append_entry`/`verify_chain` rather than
reimplement them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saena_domain.audit.guard import guard_actor_fields, guard_payload
from saena_domain.audit.hashing import GENESIS, compute_entry_hash

_ACTION_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,3}\.v[0-9]+$"
_TRACE_ID_PATTERN = r"^[0-9a-f]{32}$"
_ERROR_CODE_PATTERN = r"^saena\.[a-z_]+\.[a-z_]+$"
_SHA256_REF_PATTERN = r"^sha256:[0-9a-f]{64}$"
_TIMESTAMP_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"


class AuditEntry(BaseModel):
    """One `AuditEvent` chain entry — field set/patterns match the audit-event schema.

    Field-for-field correspondence with `packages/contracts/json-schema/
    domain/audit-event/v1/audit-event.schema.json`:
    `event_hash`/`prev_event_hash` (sha256_ref wire form), `action`
    (event-name-style pattern), `recorded_at` (Z-terminated UTC timestamp),
    `scope` (`tenant`|`system`), `trace_id` (32-hex), `payload` (open
    object, guarded — see `guard.guard_payload`), `tenant_id`/`run_id`
    (conditionally required/forbidden per `scope`, enforced by
    `_check_scope_rules` below), `actor_id` (PII-minimized identity, see
    `guard.guard_actor_fields`), `error_code` (ADR-0015 taxonomy pattern).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_hash: str = Field(pattern=_SHA256_REF_PATTERN)
    prev_event_hash: str | None = Field(default=None, pattern=_SHA256_REF_PATTERN)
    action: str = Field(pattern=_ACTION_PATTERN)
    recorded_at: str = Field(pattern=_TIMESTAMP_PATTERN)
    scope: Literal["tenant", "system"]
    trace_id: str = Field(pattern=_TRACE_ID_PATTERN)
    payload: dict[str, Any]
    tenant_id: str | None = None
    run_id: str | None = None
    actor_id: str | None = None
    error_code: str | None = Field(default=None, pattern=_ERROR_CODE_PATTERN)

    @model_validator(mode="after")
    def _check_scope_rules(self) -> AuditEntry:
        # Mirrors the schema's R9-1 allOf conditionals verbatim.
        if self.scope == "tenant" and self.tenant_id is None:
            raise ValueError("scope='tenant' requires tenant_id")
        if self.scope == "system" and (self.tenant_id is not None or self.run_id is not None):
            raise ValueError("scope='system' forbids both tenant_id and run_id")
        return self

    def hashable_fields(self) -> dict[str, Any]:
        """Return the field dict `compute_entry_hash` commits to (excludes `event_hash`)."""
        data = self.model_dump(mode="json", exclude={"event_hash"}, exclude_none=True)
        # prev_event_hash is threaded separately by compute_entry_hash's
        # `prev_hash` argument (see hashing.py docstring) — omit it here so
        # the two callers (chain builder, verifier) cannot desync on which
        # copy is authoritative.
        data.pop("prev_event_hash", None)
        return data


def build_entry(
    *,
    prev_hash: str | None,
    action: str,
    recorded_at: str,
    scope: Literal["tenant", "system"],
    trace_id: str,
    payload: dict[str, Any],
    tenant_id: str | None = None,
    run_id: str | None = None,
    actor: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> AuditEntry:
    """Construct one guarded, hash-linked `AuditEntry`.

    Applies `guard_payload` to `payload` and, if `actor` is given,
    `guard_actor_fields` to reduce it to a bare `actor_id` — both raise
    `ForbiddenAuditDataError` (see `guard.py`) before any hash is computed,
    so a rejected entry never enters the chain. `prev_hash` should be
    `hashing.GENESIS` (`None`) for the first entry in a chain, or the
    previous entry's `event_hash` otherwise.
    """
    guard_payload(payload)
    actor_id = guard_actor_fields(actor) if actor is not None else None

    fields_for_hash: dict[str, Any] = {
        "action": action,
        "recorded_at": recorded_at,
        "scope": scope,
        "trace_id": trace_id,
        "payload": payload,
    }
    if tenant_id is not None:
        fields_for_hash["tenant_id"] = tenant_id
    if run_id is not None:
        fields_for_hash["run_id"] = run_id
    if actor_id is not None:
        fields_for_hash["actor_id"] = actor_id
    if error_code is not None:
        fields_for_hash["error_code"] = error_code

    event_hash = compute_entry_hash(fields_for_hash, prev_hash)

    return AuditEntry(
        event_hash=event_hash,
        prev_event_hash=prev_hash,
        action=action,
        recorded_at=recorded_at,
        scope=scope,
        trace_id=trace_id,
        payload=payload,
        tenant_id=tenant_id,
        run_id=run_id,
        actor_id=actor_id,
        error_code=error_code,
    )


def append_entry(chain: list[AuditEntry], entry: AuditEntry) -> list[AuditEntry]:
    """Append `entry` to `chain`, verifying it correctly links to the current tail.

    Returns a NEW list (`chain` is not mutated in place) with `entry`
    appended — callers that want in-place semantics should use
    `InMemoryAuditChain.append` instead. Raises `ValueError` if `entry`'s
    `prev_event_hash` does not match the current tail's `event_hash` (or, for
    an empty chain, if `entry.prev_event_hash` is not `GENESIS`/`None`), or if
    `entry.event_hash` does not match the hash recomputed from its own
    fields — both checks guarantee `append_entry` can never silently corrupt
    the chain.
    """
    expected_prev = chain[-1].event_hash if chain else GENESIS
    if entry.prev_event_hash != expected_prev:
        raise ValueError(
            "entry.prev_event_hash does not match the current chain tail "
            f"(expected {expected_prev!r}, got {entry.prev_event_hash!r})"
        )
    recomputed = compute_entry_hash(entry.hashable_fields(), entry.prev_event_hash)
    if recomputed != entry.event_hash:
        raise ValueError("entry.event_hash does not match its own field content")
    return [*chain, entry]


def verify_chain(entries: list[AuditEntry]) -> tuple[bool, int | None]:
    """Verify every entry's hash and prev-linkage across the full chain.

    Returns `(True, None)` if the chain is intact, or `(False, i)` where `i`
    is the index of the FIRST entry that fails verification — either because
    its `prev_event_hash` does not match the preceding entry's `event_hash`
    (or `GENESIS` for index 0), or because its own `event_hash` does not
    match the hash recomputed from its field content. A tamper anywhere
    (head, middle, or tail) is detected: tampering with entry `i`'s content
    breaks entry `i`'s own recomputed hash (caught at index `i`); tampering
    with entry `i`'s stored `event_hash` directly breaks entry `i+1`'s
    `prev_event_hash` linkage (caught at index `i+1` if `i` itself still
    self-verifies, otherwise still caught at `i`).
    """
    expected_prev: str | None = GENESIS
    for index, entry in enumerate(entries):
        if entry.prev_event_hash != expected_prev:
            return False, index
        recomputed = compute_entry_hash(entry.hashable_fields(), entry.prev_event_hash)
        if recomputed != entry.event_hash:
            return False, index
        expected_prev = entry.event_hash
    return True, None


class InMemoryAuditChain:
    """Reference append-only in-memory audit chain.

    Pure-Python reference implementation for tests and pre-w2-07 callers.
    `append` guards + hash-links + appends in one call (build via
    `build_entry` first if you need to inspect the entry before committing
    it). The chain is exposed read-only via `entries`; there is no removal or
    mutation API by design (append-only, matching the AuditEvent contract's
    "contractual, immutable role").
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    @property
    def tail_hash(self) -> str | None:
        """The current chain tail's `event_hash`, or `GENESIS` if empty."""
        return self._entries[-1].event_hash if self._entries else GENESIS

    def append(
        self,
        *,
        action: str,
        recorded_at: str,
        scope: Literal["tenant", "system"],
        trace_id: str,
        payload: dict[str, Any],
        tenant_id: str | None = None,
        run_id: str | None = None,
        actor: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> AuditEntry:
        """Guard, hash-link, and append a new entry; returns the appended entry."""
        entry = build_entry(
            prev_hash=self.tail_hash,
            action=action,
            recorded_at=recorded_at,
            scope=scope,
            trace_id=trace_id,
            payload=payload,
            tenant_id=tenant_id,
            run_id=run_id,
            actor=actor,
            error_code=error_code,
        )
        self._entries = append_entry(self._entries, entry)
        return entry

    def verify(self) -> tuple[bool, int | None]:
        """Verify the full chain — see module-level `verify_chain`."""
        return verify_chain(self._entries)
