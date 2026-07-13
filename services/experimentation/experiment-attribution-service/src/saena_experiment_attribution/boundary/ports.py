"""Injected ports for the experiment-attribution service boundary (w5-12).

Pure `typing.Protocol` interfaces — no real bus/DB implementation lives here.
Everything the boundary handlers depend on is injected, so every handler is
testable with plain in-memory fakes (dependency injection, per the task
brief). Mirrors `saena_domain.measurement.ports`'s Protocol +
`@runtime_checkable` convention.

## Tenant-scoped registration lookup neutralizes the w5-03 `cross_tenant_replay`
## oracle at the boundary layer (w5-18 finding resolution)

`RegistrationLookup.lookup` is keyed by `(tenant_id, registration_hash)` as a
COMPOUND key — never `registration_hash` alone with a secondary tenant check.
This is deliberate and is the load-bearing property: a lookup for a real
`registration_hash` presented under the WRONG `tenant_id` and a lookup for a
`registration_hash` that never existed at all are STRUCTURALLY the same
lookup — there is no code path, no branch, and no timing difference between
them, because the "wrong tenant" case never reaches a "found the row, tenant
mismatched" comparison in the first place. It simply misses the compound key,
exactly like a genuinely-unknown hash would. This directly neutralizes the
`cross_tenant_replay` oracle w5-18 flagged: an attacker who has learned (or
guessed) a real registration hash belonging to another tenant cannot use this
lookup to confirm that guess — the response is identical (`None`) whether the
hash exists under a different tenant or does not exist anywhere at all.

Compare this to a naive two-step implementation ("look up by
`registration_hash` alone, then check if the returned tenant matches") — that
shape is exactly the oracle: it necessarily distinguishes "no such hash"
(step 1 misses) from "hash exists, wrong tenant" (step 1 hits, step 2 fails),
even if both eventually return the same exception type, because the two
paths are reachable by different internal state and are trivially
distinguishable by a sufficiently persistent timing/behavioral probe. The
compound-key contract in THIS protocol's signature makes that two-step shape
impossible to implement correctly against — `lookup(tenant_id,
registration_hash)` has exactly one key, so there is nothing to compare after
the fact.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from saena_domain.measurement.confirmation import RegistrationView


@runtime_checkable
class RegistrationLookup(Protocol):
    """Server-side tenant-scoped registration lookup — see module docstring.

    `lookup` returns the `RegistrationView` for `(tenant_id,
    registration_hash)` or `None` if that COMPOUND key is absent — including
    when `registration_hash` is a real hash belonging to a DIFFERENT tenant.
    There is no other method that could leak existence under another tenant
    (no `exists_anywhere`, no `find_by_hash`); the compound key is the only
    entry point.
    """

    def lookup(self, tenant_id: str, registration_hash: str) -> RegistrationView | None:
        """Return the registration view for `(tenant_id, registration_hash)`,
        or `None` if that exact compound key has no registration — a
        cross-tenant hash guess is indistinguishable from a nonexistent one.
        """
        ...


@runtime_checkable
class WorkflowSignal(Protocol):
    """Direct signal to the durable measurement workflow (ADR-0003 pattern).

    Called ONLY on an `Accepted` confirmation verdict. This is a DIRECT
    signal, NOT a bus event — per ADR-0003 ("plan-contract-service가 Temporal
    signal을 직접 발송 — 이벤트 버스 경유 배제") the transition-relevant
    authority path bypasses the event bus entirely to avoid delay/ordering/
    duplicate-delivery ambiguity in a security-relevant decision. Any
    `experiment.outcome.observed.v1` (or similar) bus event this boundary
    later publishes is notification-only and never itself a trigger.
    """

    def signal_confirmed(self, tenant_id: str, experiment_id: str, server_received_at: str) -> None:
        """Directly signal the workflow that a deployment was confirmed.

        Called AT MOST ONCE per newly-accepted confirmation — a `Duplicate`
        verdict (idempotent replay) must never re-invoke this."""
        ...


@runtime_checkable
class ManifestLookup(Protocol):
    """Resolves an evidence-bundle `manifest_hash` to the manifest itself.

    `OutcomePublisher`'s fail-closed policy gate (deliverable #2b) needs the
    actual `EvidenceBundleManifest` to call
    `saena_domain.measurement.evidence.verify_manifest` — a bare hash string
    proves nothing by itself. Tenant-scoped for the same non-leaking reason
    as `RegistrationLookup`.
    """

    def lookup(self, tenant_id: str, manifest_hash: str) -> Any | None:
        """Return the `EvidenceBundleManifest` for `(tenant_id,
        manifest_hash)`, or `None` if absent (including cross-tenant)."""
        ...


__all__ = ["ManifestLookup", "RegistrationLookup", "WorkflowSignal"]
