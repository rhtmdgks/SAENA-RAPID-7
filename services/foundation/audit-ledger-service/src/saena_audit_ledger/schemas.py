"""HTTP boundary request/response models — distinct from `saena_domain.audit.AuditEntry`.

`AppendEntryRequest` is intentionally NOT `AuditEntry`-shaped: it omits
`event_hash`/`prev_event_hash` entirely (the caller must never supply them —
the service computes both via `saena_domain.audit.build_entry`, see the
module docstring in `app.py`'s append handler for why a caller-supplied hash
would defeat the whole point of a hash-linked ledger). `EntryResponse` is the
read-side mirror: every `AuditEntry` field, serialized to plain JSON-friendly
types (the generated model's `Sha256Ref`/`TenantId`/etc. root-model wrappers
are unwrapped to bare `str` here — an HTTP response body has no reason to
carry those wrapper types, only their `.root` string value).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from saena_domain.audit import AuditEntry


class AppendEntryRequest(BaseModel):
    """POST /v1/audit/entries body — everything `build_entry` needs except `prev_hash`.

    `prev_hash` is deliberately absent from this model too: the service
    always links to its own current chain tail (`AuditLedgerPort` tracks
    that internally), a caller-supplied `prev_hash` could otherwise be used
    to fork or replay against a stale tail.
    """

    model_config = ConfigDict(extra="forbid")

    action: str
    recorded_at: str
    scope: Literal["tenant", "system"]
    trace_id: str
    payload: dict[str, Any]
    tenant_id: str | None = None
    run_id: str | None = None
    actor_id: str | None = None
    error_code: str | None = None


class EntryResponse(BaseModel):
    """One ledger entry, plain-`str`-typed for JSON response bodies."""

    model_config = ConfigDict(extra="forbid")

    event_hash: str
    prev_event_hash: str | None
    action: str
    recorded_at: str
    scope: Literal["tenant", "system"]
    trace_id: str
    payload: dict[str, Any]
    tenant_id: str | None = None
    run_id: str | None = None
    actor_id: str | None = None
    error_code: str | None = None

    @classmethod
    def from_entry(cls, entry: AuditEntry) -> EntryResponse:
        return cls(
            event_hash=entry.event_hash.root,
            prev_event_hash=entry.prev_event_hash.root if entry.prev_event_hash else None,
            action=entry.action,
            recorded_at=entry.recorded_at.root,
            scope=entry.scope.value,
            trace_id=entry.trace_id,
            payload=entry.payload,
            tenant_id=entry.tenant_id.root if entry.tenant_id else None,
            run_id=entry.run_id.root if entry.run_id else None,
            actor_id=entry.actor_id.root if entry.actor_id else None,
            error_code=entry.error_code,
        )


class VerifyResponse(BaseModel):
    """GET /v1/audit/verify result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    first_broken_index: int | None = None


class EntryListResponse(BaseModel):
    """GET /v1/audit/entries result — a bare list wrapper for room to add
    pagination metadata later without a breaking response-shape change."""

    model_config = ConfigDict(extra="forbid")

    entries: list[EntryResponse] = Field(default_factory=list)
