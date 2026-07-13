"""Audit hash-chain primitives.

`AuditEvent`'s idempotency key is "event hash (chain)" (contract-catalog.md
P0 row 12) and the JSON Schema (`packages/contracts/json-schema/domain/
audit-event/v1/audit-event.schema.json`) fixes the wire shape of both
`event_hash` and `prev_event_hash` to the shared `sha256_ref` $def:
`^sha256:[0-9a-f]{64}$` (lowercase hex, `sha256:` prefix required). Chain
*linkage semantics* are explicitly deferred to W2A by that schema's
`$comment` — this module is that W2A linkage: each entry's hash commits to
its own field content plus the immediately preceding entry's hash, so
tampering with any entry (head, middle, or tail) breaks every hash computed
from that point forward and is detectable by `chain.verify_chain`.
"""

from __future__ import annotations

from typing import Any

from saena_domain.audit.canonical import canonical_json, sha256_hex

#: Sentinel `prev_event_hash` for the first (genesis) entry in a chain — the
#: schema's `prev_event_hash` field is `anyOf: [null, sha256_ref]` and the
#: schema `$comment` states "genesis event uses null (chain head has no
#: predecessor)". `GENESIS` is the domain-layer name for that `None` value so
#: chain-building call sites read as intent rather than a bare `None`.
GENESIS: None = None

_SHA256_REF_PREFIX = "sha256:"


def _format_sha256_ref(hex_digest: str) -> str:
    """Wrap a raw hex digest in the contract's `sha256_ref` wire form."""
    return f"{_SHA256_REF_PREFIX}{hex_digest}"


def compute_entry_hash(entry_without_hash: dict[str, Any], prev_hash: str | None) -> str:
    """Compute the `event_hash` for an entry given its other fields and `prev_hash`.

    `entry_without_hash` must contain every `AuditEvent` field EXCEPT
    `event_hash` itself (including `prev_event_hash`, which the caller sets
    to `prev_hash` — this function does not implicitly inject it, so the
    caller controls exactly what is committed to the hash). The digest input
    is the canonical JSON of `{"prev_event_hash": prev_hash, "entry":
    entry_without_hash}`, keeping the previous-hash linkage explicit in the
    hashed bytes even if a caller's `entry_without_hash` dict happens to omit
    or mis-set `prev_event_hash`.

    Returns the `sha256:<64-hex>` wire form (matches the `sha256_ref` $def
    used by both `event_hash` and `prev_event_hash` in the audit-event
    schema).
    """
    material = {"prev_event_hash": prev_hash, "entry": entry_without_hash}
    digest = sha256_hex(canonical_json(material))
    return _format_sha256_ref(digest)
