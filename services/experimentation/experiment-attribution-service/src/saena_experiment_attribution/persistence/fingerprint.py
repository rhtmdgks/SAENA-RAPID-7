"""Canonical content fingerprints for the measurement records (w5-10) — PURE.

The idempotency key that decides byte-identity (`ports.py` "Idempotency
model"): two writes for the same store key collide iff they carry the same
fingerprint. Reuses `saena_domain.audit.canonical.canonical_json` VERBATIM —
the same JCS-style sorted-key canonicalization the in-memory reference
(`saena_domain.measurement.ports._*_fingerprint`) and the audit hash-chain use
— so a record fingerprinted here compares equal to the same record
fingerprinted by the in-memory reference. No second canonicalization rule is
invented.

The fingerprint stored in the row's `content_fingerprint` column is the
canonical JSON STRING itself (not a hash of it): it is short (these records
are small), it is exact (no collision risk a digest could theoretically
introduce), and storing the string lets a read-back-compare be a plain string
equality with no re-hash. This mirrors the in-memory reference, which also
compares the canonical strings directly (`_fingerprints[key] == incoming_fp`).

No `MappingProxyType`/tuple handling is needed here because the adapter builds
these fingerprints from PLAIN dict/list JSON shapes (either freshly
deserialized from a row's JSONB `::text`, or thawed from a frozen record via
the port's own `_thaw` on the way in) — this module only ever sees plain
JSON-shaped Python values, exactly as `canonical_json` requires.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from saena_domain.audit.canonical import canonical_json


def confirmation_fingerprint(
    *, tenant_id: str, confirmation_key: str, measurement_kind: str, payload: Mapping[str, Any]
) -> str:
    """Canonical fingerprint of a confirmation's logical content.

    Field set + order-independence match
    `saena_domain.measurement.ports._confirmation_fingerprint` exactly (keys
    are sorted by `canonical_json`, so the argument order here is irrelevant).
    """
    return canonical_json(
        {
            "tenant_id": tenant_id,
            "confirmation_key": confirmation_key,
            "measurement_kind": measurement_kind,
            "payload": payload,
        }
    )


def window_fingerprint(
    *,
    tenant_id: str,
    experiment_id: str,
    starts_at: str,
    ends_at: str | None,
    policy_version: str,
) -> str:
    """Canonical fingerprint of a window — mirrors `ports._window_fingerprint`."""
    return canonical_json(
        {
            "tenant_id": tenant_id,
            "experiment_id": experiment_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "policy_version": policy_version,
        }
    )


def decision_fingerprint(
    *,
    tenant_id: str,
    decision_key: Sequence[str],
    outcome: str,
    evidence_bundle_ref: str,
    policy_metadata: Mapping[str, Any],
) -> str:
    """Canonical fingerprint of a decision — mirrors `ports._decision_fingerprint`
    (`decision_key` serialized as a 2-element list, exactly as the reference does).
    """
    return canonical_json(
        {
            "tenant_id": tenant_id,
            "decision_key": list(decision_key),
            "outcome": outcome,
            "evidence_bundle_ref": evidence_bundle_ref,
            "policy_metadata": policy_metadata,
        }
    )


def bundle_fingerprint(*, tenant_id: str, manifest: Mapping[str, Any]) -> str:
    """Canonical fingerprint of an evidence bundle — mirrors `ports._bundle_fingerprint`."""
    return canonical_json({"tenant_id": tenant_id, "manifest": manifest})


__all__ = [
    "bundle_fingerprint",
    "confirmation_fingerprint",
    "decision_fingerprint",
    "window_fingerprint",
]
