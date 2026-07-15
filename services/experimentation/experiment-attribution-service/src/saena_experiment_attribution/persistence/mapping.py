"""Record <-> row translation + JSON (de)serialization + SF-4 re-verification (w5-10).

PURE (no DB I/O): every function here maps between a frozen domain record and
the plain-Python row/bind shapes the adapter hands to/receives from
SQLAlchemy. Unit-tested to ~100% without a database.

## Deep-thaw on the write path

The measurement records deep-FREEZE their `payload`/`policy_metadata`/`manifest`
(nested dicts become `MappingProxyType`, lists become tuples — see
`ports._deep_freeze`). `json.dumps` cannot serialize `MappingProxyType`, so the
`*_to_bind` helpers THAW back to plain dict/list JSON shapes before binding a
`::jsonb` parameter. Tuples thaw to lists (their canonical JSON-array form), so
a record built from a list and its frozen tuple round-trip identically — the
same rule `ports._thaw` applies before fingerprinting, kept in lockstep here.

## SF-4 obligation (w5-08 security critic) — re-verify on the deserialization boundary

Reading a row back from Postgres is a DESERIALIZATION boundary: the bytes came
from outside this process's memory and cannot be trusted to still satisfy the
evidence bundle's tamper-evident commitment chain (a DBA edit, a replication
corruption, a restore from a tampered backup, a malicious row write bypassing
the adapter). `row_to_evidence_bundle` therefore RE-VERIFIES every manifest
that is shaped like an `EvidenceBundleManifest` (`evidence.verify_manifest`)
and raises `EvidenceIntegrityError` on `(False, _)` — a tampered/reordered/
spliced manifest can never be handed back to a caller as if intact. A manifest
that is NOT an `EvidenceBundleManifest` shape (e.g. a bare `{"artifacts": [...]}`
conformance fixture that carries no commitment chain) is passed through
unverified — there is nothing to verify — but the moment a manifest declares a
commitment chain (`entry_commitments`/`manifest_hash` present), it MUST verify
or the read fails closed.

`EvidenceBundleManifest`'s own pydantic constructor ALSO recomputes the chain
(`_check_commitment_chain`), so a tampered chain would already raise at
`model_validate` time; `verify_manifest` is called explicitly and unconditionally
regardless, so the obligation is satisfied by an EXPLICIT check (the
security-critic requirement is a call to `verify_manifest`, not reliance on a
constructor side-effect) and so a manifest reconstructed via a path that skips
validation is still caught.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from saena_domain.measurement import evidence
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    EvidenceBundle,
    MeasurementWindow,
    OutcomeDecisionRecord,
)


class EvidenceIntegrityError(Exception):
    """A manifest read back from storage failed its commitment-chain re-verification.

    Raised fail-closed by `row_to_evidence_bundle` (SF-4 obligation) when
    `evidence.verify_manifest` reports the deserialized manifest is not intact
    — a tampered/reordered/spliced bundle is never returned to a caller as
    valid. Log-safe `context` carries only the tenant/hash/divergence-index,
    never raw manifest content.
    """

    error_code = "saena.measurement.evidence_integrity_violation"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}


def _thaw(value: Any) -> Any:
    """Deep-thaw a possibly-frozen JSON value to plain dict/list shapes.

    Local re-implementation (not an import of `ports._thaw`, a private symbol)
    with identical semantics: mappings -> plain dicts, lists/tuples -> lists,
    scalars pass through — so `json.dumps` can serialize the result and a
    tuple-vs-list difference never changes the serialized bytes.
    """
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def to_jsonb_text(value: Mapping[str, Any]) -> str:
    """Serialize a (possibly frozen) mapping to compact JSON text for a
    `CAST(:x AS jsonb)` bind. Thaws first so `MappingProxyType`/tuple nesting
    serializes cleanly."""
    return json.dumps(_thaw(value), separators=(",", ":"), ensure_ascii=False)


def from_jsonb_text(text: str) -> dict[str, Any]:
    """Parse a `jsonb::text` projection back into a plain dict."""
    parsed = json.loads(text)
    if not isinstance(parsed, dict):  # pragma: no cover — every stored payload is an object
        raise ValueError("expected a JSON object from jsonb column")
    return parsed


# --- confirmations -----------------------------------------------------------------


def confirmation_to_bind(
    tenant_id: str, key: str, record: ConfirmationRecord, fingerprint: str
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "confirmation_key": key,
        "measurement_kind": record.measurement_kind,
        "payload": to_jsonb_text(record.payload),
        "content_fingerprint": fingerprint,
    }


def row_to_confirmation(row: Mapping[str, Any]) -> ConfirmationRecord:
    return ConfirmationRecord(
        tenant_id=row["tenant_id"],
        confirmation_key=row["confirmation_key"],
        measurement_kind=row["measurement_kind"],
        payload=from_jsonb_text(row["payload"]),
    )


# --- windows -----------------------------------------------------------------------


def window_to_bind(tenant_id: str, window: MeasurementWindow, fingerprint: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "experiment_id": window.experiment_id,
        "starts_at": window.starts_at,
        "ends_at": window.ends_at,
        "policy_version": window.policy_version,
        "content_fingerprint": fingerprint,
    }


def row_to_window(row: Mapping[str, Any]) -> MeasurementWindow:
    return MeasurementWindow(
        tenant_id=row["tenant_id"],
        experiment_id=row["experiment_id"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        policy_version=row["policy_version"],
    )


# --- decisions ---------------------------------------------------------------------


def decision_to_bind(
    tenant_id: str, decision: OutcomeDecisionRecord, fingerprint: str
) -> dict[str, Any]:
    experiment_id, decision_slot = decision.decision_key
    return {
        "tenant_id": tenant_id,
        "experiment_id": experiment_id,
        "decision_slot": decision_slot,
        "outcome": decision.outcome,
        "evidence_bundle_ref": decision.evidence_bundle_ref,
        "policy_metadata": to_jsonb_text(decision.policy_metadata),
        "content_fingerprint": fingerprint,
    }


def row_to_decision(row: Mapping[str, Any]) -> OutcomeDecisionRecord:
    return OutcomeDecisionRecord(
        tenant_id=row["tenant_id"],
        decision_key=(row["experiment_id"], row["decision_slot"]),
        outcome=row["outcome"],
        evidence_bundle_ref=row["evidence_bundle_ref"],
        policy_metadata=from_jsonb_text(row["policy_metadata"]),
    )


# --- evidence bundles (SF-4 re-verification boundary) ------------------------------


def evidence_to_bind(
    tenant_id: str, manifest_hash: str, bundle: EvidenceBundle, fingerprint: str
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "manifest_hash": manifest_hash,
        "manifest": to_jsonb_text(bundle.manifest),
        "content_fingerprint": fingerprint,
    }


def _looks_like_bundle_manifest(manifest: Mapping[str, Any]) -> bool:
    """True iff the manifest declares an `EvidenceBundleManifest` commitment
    chain (so it MUST be re-verified). A bare mapping with none of the
    chain-defining fields (e.g. a conformance fixture `{"artifacts": [...]}`)
    carries no integrity claim to check."""
    return "entry_commitments" in manifest or "manifest_hash" in manifest


def _reverify_manifest(tenant_id: str, manifest_hash: str, manifest: Mapping[str, Any]) -> None:
    """SF-4: re-verify a chain-bearing manifest on the deserialization boundary.

    Reconstructs an `EvidenceBundleManifest` from the stored JSON and calls
    `evidence.verify_manifest`; raises `EvidenceIntegrityError` on
    `(False, _)`. A manifest whose stored bytes no longer satisfy the chain
    fails BOTH here (explicit) and — for the same reason —
    `EvidenceBundleManifest`'s own constructor; either way the read fails
    closed. A shape that cannot be parsed as an `EvidenceBundleManifest` at all
    (declared a chain but is malformed) is itself an integrity failure and is
    reported as one, never silently passed through.
    """
    try:
        reconstructed = evidence.EvidenceBundleManifest.model_validate(dict(manifest))
    except Exception as exc:  # pydantic ValidationError or the chain check raising
        raise EvidenceIntegrityError(
            "evidence manifest read back from storage declares a commitment chain but "
            "failed to reconstruct/verify — integrity violation, value redacted",
            context={"tenant_id": tenant_id, "manifest_hash": manifest_hash},
        ) from exc
    intact, divergence_index = evidence.verify_manifest(reconstructed)
    if not intact:
        raise EvidenceIntegrityError(
            "evidence manifest read back from storage failed commitment-chain "
            "re-verification (tamper/reorder/splice) — value redacted",
            context={
                "tenant_id": tenant_id,
                "manifest_hash": manifest_hash,
                "divergence_index": divergence_index,
            },
        )


def row_to_evidence_bundle(row: Mapping[str, Any]) -> EvidenceBundle:
    """Rebuild an `EvidenceBundle`, RE-VERIFYING a chain-bearing manifest (SF-4).

    The single deserialization boundary for evidence bundles: any manifest that
    declares a commitment chain is re-verified via `evidence.verify_manifest`
    and raises `EvidenceIntegrityError` on failure BEFORE the bundle is
    returned. See module docstring "SF-4 obligation".
    """
    tenant_id = row["tenant_id"]
    manifest_hash = row["manifest_hash"]
    manifest = from_jsonb_text(row["manifest"])
    if _looks_like_bundle_manifest(manifest):
        _reverify_manifest(tenant_id, manifest_hash, manifest)
    return EvidenceBundle(tenant_id=tenant_id, manifest=manifest)


__all__ = [
    "EvidenceIntegrityError",
    "confirmation_to_bind",
    "decision_to_bind",
    "evidence_to_bind",
    "from_jsonb_text",
    "row_to_confirmation",
    "row_to_decision",
    "row_to_evidence_bundle",
    "row_to_window",
    "to_jsonb_text",
    "window_to_bind",
]
