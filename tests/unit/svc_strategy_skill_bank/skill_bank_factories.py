"""Factory helpers for `tests/unit/svc_strategy_skill_bank`.

Deliberately NOT named `conftest.py` — see
`tests/unit/svc_observer_discovery/observer_discovery_factories.py`'s
module docstring for why a second `conftest.py` in a sibling test directory
causes an import collision when the full `tests/unit` suite is collected
together. Imported by its own unique dotted name (`skill_bank_factories`),
inserted onto `sys.path` by this directory's `conftest.py`.
"""

from __future__ import annotations

from saena_domain.audit.canonical import canonical_json, sha256_hex
from saena_domain.measurement.evidence import (
    EvidenceBundleManifest,
    EvidenceEntry,
    EvidenceKind,
    EvidenceMetadata,
    EvidenceRef,
)

TENANT_A = "acme-co"
RUN_A = "run-0001"
EXPERIMENT_A = "experiment-0001"

VALID_SHA_A = "sha256:" + "a" * 64
VALID_SHA_B = "sha256:" + "b" * 64


def _hash(value: str) -> str:
    return f"sha256:{sha256_hex(canonical_json({'v': value}))}"


def build_evidence_entry(
    *,
    kind: EvidenceKind = EvidenceKind.REGISTRATION,
    uri: str = "artifact://evidence/registration-0001",
    content_hash: str = VALID_SHA_A,
    with_observation_provenance: bool = False,
) -> EvidenceEntry:
    metadata = EvidenceMetadata()
    if with_observation_provenance or kind in (
        EvidenceKind.BASELINE_OBSERVATION,
        EvidenceKind.TREATMENT_OBSERVATION,
        EvidenceKind.CONTROL_OBSERVATION,
    ):
        metadata = EvidenceMetadata(
            timestamp="2026-07-14T00:00:00Z",
            client_version="1.0.0",
            asset_hash=VALID_SHA_B,
            citation_present=False,
        )
    return EvidenceEntry(
        kind=kind,
        ref=EvidenceRef(uri=uri, content_hash=content_hash),
        metadata=metadata,
    )


def build_manifest(
    *,
    tenant_id: str = TENANT_A,
    run_id: str = RUN_A,
    experiment_id: str = EXPERIMENT_A,
    entries: tuple[EvidenceEntry, ...] | None = None,
) -> EvidenceBundleManifest:
    if entries is None:
        entries = (build_evidence_entry(),)
    return EvidenceBundleManifest.seal(
        tenant_id=tenant_id,
        run_id=run_id,
        experiment_id=experiment_id,
        entries=entries,
    )


def build_strategy_card_eligible_payload(
    *,
    card_candidate_ref: str = "candidate-0001",
    b_verdict: str = "pass",
    evidence_bundle_manifest_hash: str | None = None,
) -> dict:
    """A dict shaped exactly like the `strategy.card.eligible.v1` wire
    payload (`packages/contracts/json-schema/event/strategy-card-eligible/
    v1/strategy-card-eligible.schema.json`)."""
    manifest_hash = evidence_bundle_manifest_hash or VALID_SHA_A
    return {
        "card_candidate_ref": card_candidate_ref,
        "source_outcome": {
            "b_verdict": b_verdict,
            "evidence_bundle_manifest_hash": manifest_hash,
        },
    }
