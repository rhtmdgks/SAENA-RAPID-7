"""Append-only experiment-registration ledger: hash, register, verify (w4-09).

REUSES `saena_domain.audit.canonical.canonical_json`/`sha256_hex` verbatim —
the same JCS-style sorted-key compact-JSON canonicalization the audit
hash-chain (`saena_domain.audit.chain`/`hashing`) is built on. This module
does NOT invent a second canonicalization rule; it only adds the
`sha256:<hex>` wire-form prefix convention (matching the `sha256_ref` $def
pattern `^sha256:[0-9a-f]{64}$` used throughout the contracts — see
`saena_domain.audit.hashing.compute_entry_hash`, which applies the identical
prefix convention for the audit chain's `event_hash`).

One deliberate divergence from `saena_domain.audit.hashing.compute_entry_hash`:
that function threads `prev_hash` INTO the hashed material (so an audit
entry's own hash depends on chain position). `compute_experiment_hash` here
does NOT — per the w4-09 mission, the canonical hash commits to "every field
except canonical_hash/previous_hash" only, so two byte-identical
registrations hash identically regardless of where either lands in a ledger.
Chain-position integrity is instead carried entirely by `previous_hash`
(set by `register`) and checked by `verify_ledger` — the same two-part
verification shape as `saena_domain.audit.chain.verify_chain` (own-hash
recompute + prev-linkage check), just with the linkage input decoupled from
the content hash.
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


def _hashable_fields(registration: ExperimentRegistration) -> dict[str, Any]:
    """Every `ExperimentRegistration` field except `canonical_hash`/`previous_hash`."""
    return registration.model_dump(mode="json", exclude={"canonical_hash", "previous_hash"})


def compute_experiment_hash(registration: ExperimentRegistration) -> str:
    """Deterministic content hash of `registration` — see module docstring.

    Same registration content (regardless of whether `canonical_hash`/
    `previous_hash` are already populated) → byte-identical `sha256:<hex>`
    string on every call/process/machine. Any other field change → a
    different hash. Does not depend on ledger/chain position.
    """
    material = _hashable_fields(registration)
    digest = sha256_hex(canonical_json(material))
    return f"{_SHA256_PREFIX}{digest}"


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
      chain-anchor step — `canonical_hash` is computed via
      `compute_experiment_hash`, and the resulting entry is appended.
    - Existing `experiment_id`, byte-identical content (same
      `compute_experiment_hash` value): no-op replay — returns the
      UNCHANGED `ledger_state` and the ALREADY-stored entry (no double
      append; `register` is safe to call twice with the same registration).
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
        if compute_experiment_hash(existing) == compute_experiment_hash(registration):
            return ledger_state, existing
        if _design_changed(existing, registration):
            raise RejectedError(registration.experiment_id)
        raise ConflictError(registration.experiment_id)

    previous_hash = ledger_state[-1].canonical_hash if ledger_state else GENESIS
    canonical_hash = compute_experiment_hash(registration)
    entry = registration.model_copy(
        update={"canonical_hash": canonical_hash, "previous_hash": previous_hash}
    )
    return (*ledger_state, entry), entry


def verify_ledger(entries: LedgerState) -> tuple[bool, int | None]:
    """Verify every entry's `canonical_hash` and the `previous_hash` chain.

    Returns `(True, None)` if the ledger is intact, or `(False, i)` where
    `i` is the index of the FIRST entry that fails verification — either its
    `previous_hash` does not match the preceding entry's `canonical_hash`
    (or `GENESIS` for index 0), or its own `canonical_hash` does not match
    the hash recomputed from its field content. Mirrors
    `saena_domain.audit.chain.verify_chain`'s two-part check shape: a
    mutated field is caught at the entry it mutated (own-hash mismatch); a
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
