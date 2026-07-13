"""Content-hash helpers — REUSES `saena_domain.audit.canonical`, verbatim.

Mirrors `saena_domain.experiment.ledger`'s reuse discipline exactly (see
that module's docstring): the SAME `canonical_json` (sorted-key, compact,
ASCII-safe JSON) + `sha256_hex` pair the audit hash-chain is built on,
wrapped only with the `sha256:<hex>` wire-form prefix convention the
`sha256_ref` contract `$def` requires
(`^sha256:[0-9a-f]{64}$` — see `EvidenceRecord.content_hash` /
`ClaimEvidenceVersionedV1Payload.provenance_ref`, both typed
`Sha256Ref` in the generated schemas). No second hashing/canonicalization
rule is invented anywhere in this package.
"""

from __future__ import annotations

from typing import Any

from saena_domain.audit.canonical import canonical_json, sha256_hex

_SHA256_PREFIX = "sha256:"


def _prefixed_hash(material: dict[str, Any]) -> str:
    digest = sha256_hex(canonical_json(material))
    return f"{_SHA256_PREFIX}{digest}"


def compute_evidence_content_hash(
    *,
    tenant_id: str,
    project_id: str,
    evidence_id: str,
    claim_id: str,
    source_uri: str,
    excerpt: str,
) -> str:
    """Deterministic `sha256:<hex>` content hash for one `EvidenceRecord`.

    Deliberately excludes `freshness_checked_at` — re-checking freshness
    (the same evidence re-verified as still current at a later instant)
    must NOT be indistinguishable from an actual content change; freshness
    re-checks are tracked by the ledger's `EvidenceLinkStatus`/
    `freshness_checked_at` field directly, not folded into the identity
    hash of the evidence's own claimed content. Same
    (tenant_id, project_id, evidence_id, claim_id, source_uri, excerpt) =>
    byte-identical hash on every call/process/machine.
    """
    material = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "evidence_id": evidence_id,
        "claim_id": claim_id,
        "source_uri": source_uri,
        "excerpt": excerpt,
    }
    return _prefixed_hash(material)


def compute_ledger_entry_hash(material: dict[str, Any]) -> str:
    """Deterministic `sha256:<hex>` hash of an arbitrary JSON-serializable
    ledger-entry material dict (append-only chain hashing — see
    `ledger.py`'s `_hashable_fields`, which is the sole caller and decides
    exactly which fields belong in `material`)."""
    return _prefixed_hash(material)


__all__ = ["compute_evidence_content_hash", "compute_ledger_entry_hash"]
