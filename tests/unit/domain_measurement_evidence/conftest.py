"""Shared fixtures/builders for saena_domain.measurement.evidence tests (w5-08)."""

from __future__ import annotations

from typing import Any

from saena_domain.measurement.evidence import (
    EvidenceBundleManifest,
    EvidenceEntry,
    EvidenceKind,
    EvidenceMetadata,
    EvidenceRef,
)

_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64
_HASH_C = "sha256:" + "c" * 64


def ref(suffix: str = "a") -> EvidenceRef:
    return EvidenceRef(uri=f"s3://bundle/artifact-{suffix}", content_hash="sha256:" + suffix * 64)


def observation_metadata(**overrides: Any) -> EvidenceMetadata:
    base: dict[str, Any] = {
        "timestamp": "2026-07-13T09:00:00Z",
        "client_version": "chatgpt-search-2026.07",
        "asset_hash": _HASH_C,
        "citation": "https://example.test/cited",
    }
    base.update(overrides)
    return EvidenceMetadata(**base)


def entry(kind: EvidenceKind, *, suffix: str = "a", **meta_overrides: Any) -> EvidenceEntry:
    """Build one entry. Observation kinds get full provenance by default."""
    from saena_domain.measurement.evidence import _OBSERVATION_KINDS  # noqa: PLC0415

    if kind in _OBSERVATION_KINDS:
        metadata = observation_metadata(**meta_overrides)
    else:
        metadata = EvidenceMetadata(**meta_overrides) if meta_overrides else EvidenceMetadata()
    return EvidenceEntry(kind=kind, ref=ref(suffix), metadata=metadata)


def complete_entries() -> tuple[EvidenceEntry, ...]:
    """One entry of every REQUIRED_B_GATE_KIND (a complete B-gate bundle)."""
    return (
        entry(EvidenceKind.REGISTRATION, suffix="0"),
        entry(EvidenceKind.DEPLOYMENT_CONFIRMATION, suffix="1"),
        entry(EvidenceKind.BASELINE_OBSERVATION, suffix="2"),
        entry(EvidenceKind.TREATMENT_OBSERVATION, suffix="3"),
        entry(EvidenceKind.CONTROL_OBSERVATION, suffix="4"),
        entry(EvidenceKind.RAW_OBSERVATION_REF, suffix="5"),
        entry(EvidenceKind.DID_INPUTS, suffix="6"),
        entry(EvidenceKind.DID_OUTPUTS, suffix="7"),
        entry(EvidenceKind.B_GATE_DECISION, suffix="8"),
        entry(EvidenceKind.GRS_POLICY, suffix="9"),
    )


def sealed_bundle(
    entries: tuple[EvidenceEntry, ...] | None = None, **overrides: Any
) -> EvidenceBundleManifest:
    base: dict[str, Any] = {
        "tenant_id": "acme-co",
        "run_id": "run-2026-0713-0001",
        "experiment_id": "exp-2026-0713-0001",
        "entries": complete_entries() if entries is None else entries,
    }
    base.update(overrides)
    return EvidenceBundleManifest.seal(**base)
