"""ChangePlan `contract_hash` derivation.

`change-plan.schema.json`'s own `$comment` is explicit: `contract_hash` is
"intentionally NOT a member of this schema — it is a self-reference that
would have to be computed over its own containing document (self-reference
avoidance)... Canonicalization method (JCS) that would produce that hash is
an explicitly pre-W2A ADR" (OPEN — no JCS ADR exists yet). This service is
the FIRST W2A consumer that must actually produce a `contract_hash` value (to
key `POST /v1/plans` storage and to populate the `plan.contract.proposed.v1`
event payload's required `contract_hash` field), so it needs a concrete
canonicalization NOW rather than waiting on that open ADR.

Interim choice (flagged OPEN ITEM in the final report — replace this module's
body, not its call sites, once the JCS ADR lands): reuse
`saena_domain.audit.canonical.canonical_json`/`sha256_hex`, the same
deterministic sorted-key/compact-separator canonicalization the audit-ledger
hash chain already depends on (`saena_domain.audit.hashing`/`chain.py`). This
is NOT RFC 8785 JCS (JCS has additional number-formatting/Unicode-escaping
rules `json.dumps(sort_keys=True)` does not fully replicate) — it is a
same-process, same-Python-version deterministic hash sufficient for this
service's own idempotency-key and immutability-check purposes, but it is NOT
guaranteed byte-identical to whatever the eventual JCS ADR mandates. Any
`contract_hash` value computed by THIS module must be treated as
plan-contract-service's own internal derivation, not a cross-service
canonical hash, until the JCS ADR resolves this OPEN ITEM.
"""

from __future__ import annotations

from saena_domain.audit.canonical import canonical_json, sha256_hex

_SHA256_PREFIX = "sha256:"


def compute_contract_hash(change_plan: dict[str, object]) -> str:
    """Return the `sha256_ref`-shaped (`sha256:<64-hex>`) content hash of
    `change_plan` (a validated `ChangePlan` document, as a plain dict).

    Deterministic: the same logical `change_plan` mapping always yields the
    same hash in this process, regardless of key insertion order (canonical
    JSON sorts keys recursively) — this is the property `guard_immutability`
    (`saena_domain.policy`) relies on to detect post-approval content
    mutation under a reused `contract_hash`.
    """
    digest = sha256_hex(canonical_json(change_plan))
    return f"{_SHA256_PREFIX}{digest}"


__all__ = ["compute_contract_hash"]
