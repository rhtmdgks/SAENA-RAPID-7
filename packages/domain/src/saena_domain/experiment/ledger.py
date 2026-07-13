"""Append-only experiment-registration ledger: hash, register, verify (w4-09).

REUSES `saena_domain.audit.canonical.canonical_json`/`sha256_hex` verbatim —
the same JCS-style sorted-key compact-JSON canonicalization the audit
hash-chain (`saena_domain.audit.chain`/`hashing`) is built on. This module
does NOT invent a second canonicalization rule; it only adds the
`sha256:<hex>` wire-form prefix convention (matching the `sha256_ref` $def
pattern `^sha256:[0-9a-f]{64}$` used throughout the contracts — see
`saena_domain.audit.hashing.compute_entry_hash`, which applies the identical
prefix convention for the audit chain's `event_hash`).

## r4-03 remediation: two separate hash identities

The original w4-09 shape computed a single `canonical_hash` that excluded
BOTH `canonical_hash` and `previous_hash` from its own hashed material, and
used that same value both for idempotent-replay comparison AND as the value
`verify_ledger` checked for chain integrity. That conflation was a defect:
because the stored `canonical_hash` never committed to `previous_hash` (chain
position), an attacker could reorder ledger entries, rewrite each entry's
`previous_hash` to match the new order, and reuse every entry's EXISTING
`canonical_hash` unchanged — `verify_ledger` recomputes each entry's content
hash and compares it to the stored `canonical_hash`, and since content
hashing never depended on `previous_hash`, the recompute still matched even
after reorder+relink. See
`tests/unit/domain_experiment/test_ledger.py::
test_old_vulnerability_reorder_and_relink_would_have_passed_verify` for the
pinned regression that proves this against the OLD hashing shape.

This module now separates the two identities cleanly, mirroring
`saena_domain.audit.hashing.compute_entry_hash`'s own approach (which already
threads `prev_hash` into its hashed material for exactly this reason):

- `compute_content_fingerprint` — content-only, EXCLUDES `previous_hash`,
  `canonical_hash`, AND `content_fingerprint` itself from the hashed
  material. Used ONLY by `register`'s idempotent-replay comparison: two
  byte-identical registrations (ignoring where either lands in a ledger)
  fingerprint identically. This is intentionally chain-position-independent
  — idempotency must not care about ledger position.
- `compute_experiment_hash` — the CHAIN-ENTRY hash. Commits to the entry's
  content fingerprint AND `previous_hash` (chain position), in the same
  shape `saena_domain.audit.hashing.compute_entry_hash` uses:
  `canonical_json({"previous_hash": previous_hash, "content_fingerprint":
  fingerprint})`. This is the value stored in `canonical_hash` and the value
  `verify_ledger` checks — so tampering with chain position (reorder,
  splice, relink) changes the chain hash even when content and
  `previous_hash` are individually "consistent-looking" post-tamper, because
  the ONLY way to reproduce a given `canonical_hash` is to reproduce both
  its content fingerprint AND its exact `previous_hash` simultaneously.

The content fingerprint is deliberately NEVER reused as the chain hash (that
would reintroduce the original vulnerability) and the chain hash is
deliberately NEVER used for idempotency comparison (that would make
idempotency chain-position-dependent, breaking the "byte-identical content
is always a no-op" contract).
"""

from __future__ import annotations

from typing import Any

from saena_domain.audit.canonical import canonical_json, sha256_hex
from saena_domain.experiment.errors import ConflictError, RejectedError
from saena_domain.experiment.models import ExperimentRegistration

#: Sentinel `previous_hash` for the first entry in a ledger — mirrors
#: `saena_domain.audit.hashing.GENESIS`.
GENESIS: None = None

#: Ledger state is an immutable tuple of registered entries, in append
#: order — `register` returns a NEW tuple rather than mutating its input,
#: matching `saena_domain.audit.chain.append_entry`'s "returns a NEW list"
#: contract.
LedgerState = tuple[ExperimentRegistration, ...]

_SHA256_PREFIX = "sha256:"

#: Fields never fed into either hash: the three hash/link-bearing fields
#: themselves. `content_fingerprint` is excluded from the CONTENT hash too
#: (a fingerprint must not hash itself).
_HASH_BEARING_FIELDS = {"canonical_hash", "previous_hash", "content_fingerprint"}


def _format_sha256(digest: str) -> str:
    return f"{_SHA256_PREFIX}{digest}"


def _content_fields(registration: ExperimentRegistration) -> dict[str, Any]:
    """Every `ExperimentRegistration` field except the hash/link-bearing ones."""
    return registration.model_dump(mode="json", exclude=_HASH_BEARING_FIELDS)


def compute_content_fingerprint(registration: ExperimentRegistration) -> str:
    """Deterministic CONTENT-ONLY fingerprint of `registration` — see module docstring.

    Excludes `canonical_hash`, `previous_hash`, AND `content_fingerprint`
    from the hashed material. Same registration content (regardless of
    where it lands in a ledger, or whether its hash fields are already
    populated) → byte-identical `sha256:<hex>` string on every
    call/process/machine. Any other field change → a different fingerprint.

    Used ONLY for idempotent re-registration comparison in `register` — NOT
    a substitute for the chain-entry hash (`compute_experiment_hash`), which
    also commits to `previous_hash`.
    """
    material = _content_fields(registration)
    digest = sha256_hex(canonical_json(material))
    return _format_sha256(digest)


def compute_experiment_hash(registration: ExperimentRegistration) -> str:
    """Deterministic CHAIN-ENTRY hash: content fingerprint + `previous_hash`.

    This is the value stored in `canonical_hash` and the value `verify_ledger`
    checks. Unlike `compute_content_fingerprint`, this commits to chain
    position: `canonical_json({"previous_hash": registration.previous_hash,
    "content_fingerprint": compute_content_fingerprint(registration)})`,
    mirroring `saena_domain.audit.hashing.compute_entry_hash`'s
    `{"prev_event_hash": prev_hash, "entry": entry_without_hash}` shape.

    Two entries with identical content but different `previous_hash` values
    (e.g. the same entry reordered to a different chain position) hash
    DIFFERENTLY here — this is what makes reorder/splice/relink attacks
    detectable by `verify_ledger` (see module docstring).
    """
    fingerprint = compute_content_fingerprint(registration)
    material = {"previous_hash": registration.previous_hash, "content_fingerprint": fingerprint}
    digest = sha256_hex(canonical_json(material))
    return _format_sha256(digest)


def _design_changed(existing: ExperimentRegistration, incoming: ExperimentRegistration) -> bool:
    """True if `incoming` changes `arms` or `metric_definitions` vs. `existing`."""
    return (
        existing.arms != incoming.arms or existing.metric_definitions != incoming.metric_definitions
    )


def register(
    ledger_state: LedgerState, registration: ExperimentRegistration
) -> tuple[LedgerState, ExperimentRegistration]:
    """Append `registration` to `ledger_state`; returns `(new_ledger_state, stored_entry)`.

    Append-only, fail-closed idempotency:

    - New `experiment_id`: `previous_hash` is set to the ledger tail's
      `canonical_hash` (`GENESIS`/`None` for an empty ledger) — the
      chain-anchor step. `content_fingerprint` is computed via
      `compute_content_fingerprint` (content-only). `canonical_hash` (the
      chain-entry hash) is then computed via `compute_experiment_hash`,
      which commits to both the content fingerprint AND `previous_hash`.
      The resulting entry — with all three fields populated — is appended.
    - Existing `experiment_id`, byte-identical content (same
      `compute_content_fingerprint` value): no-op replay — returns the
      UNCHANGED `ledger_state` and the ALREADY-stored entry (no double
      append; `register` is safe to call twice with the same registration).
      Idempotency comparison deliberately uses the CONTENT fingerprint, not
      the chain-entry hash, so it does not care where either registration
      would land in a ledger.
    - Existing `experiment_id`, different content, where `arms` or
      `metric_definitions` changed: raises `RejectedError` — preregistration
      design immutability (a re-register may never mutate the experiment's
      arms or declared metrics).
    - Existing `experiment_id`, different content, where the change is NOT
      to `arms`/`metric_definitions`: raises `ConflictError`.

    No outcome/effect/lift computation happens anywhere in this function —
    it only ever compares and stores registration CONTENT.
    """
    existing = next(
        (entry for entry in ledger_state if entry.experiment_id == registration.experiment_id),
        None,
    )

    if existing is not None:
        if compute_content_fingerprint(existing) == compute_content_fingerprint(registration):
            return ledger_state, existing
        if _design_changed(existing, registration):
            raise RejectedError(registration.experiment_id)
        raise ConflictError(registration.experiment_id)

    previous_hash = ledger_state[-1].canonical_hash if ledger_state else GENESIS
    unanchored = registration.model_copy(update={"previous_hash": previous_hash})
    content_fingerprint = compute_content_fingerprint(unanchored)
    canonical_hash = compute_experiment_hash(unanchored)
    entry = registration.model_copy(
        update={
            "canonical_hash": canonical_hash,
            "previous_hash": previous_hash,
            "content_fingerprint": content_fingerprint,
        }
    )
    return (*ledger_state, entry), entry


def verify_ledger(entries: LedgerState) -> tuple[bool, int | None]:
    """Verify every entry's `canonical_hash` (chain-entry hash) and `previous_hash` chain.

    Returns `(True, None)` if the ledger is intact, or `(False, i)` where
    `i` is the index of the FIRST entry that fails verification — either its
    `previous_hash` does not match the preceding entry's `canonical_hash`
    (or `GENESIS` for index 0), or its own `canonical_hash` does not match
    the chain-entry hash recomputed from its field content AND its
    `previous_hash`. Because `compute_experiment_hash` commits to
    `previous_hash`, reordering entries and relinking `previous_hash` to
    match the new order — while reusing each entry's existing
    `canonical_hash` unchanged — is now detected: the reused `canonical_hash`
    was computed against the OLD `previous_hash`, so it no longer matches
    the hash recomputed against the NEW `previous_hash` at that entry's new
    position. Mirrors `saena_domain.audit.chain.verify_chain`'s two-part
    check shape: a mutated field is caught at the entry it mutated
    (own-hash mismatch, which now also covers position mutation); a
    broken/forged `previous_hash` link is caught at the entry whose linkage
    no longer matches the preceding entry's recomputed hash.
    """
    expected_prev: str | None = GENESIS
    for index, entry in enumerate(entries):
        if entry.previous_hash != expected_prev:
            return False, index
        recomputed = compute_experiment_hash(entry)
        if recomputed != entry.canonical_hash:
            return False, index
        expected_prev = entry.canonical_hash
    return True, None
