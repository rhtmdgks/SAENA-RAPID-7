"""Guard-mutation coverage (directive §8): removing/weakening each core guard
must break at least one adversarial test here.

Each test pins ONE guard clause so that a mutant which deletes that clause
turns this test red. These are the "if you delete this line, this test
fails" anchors for:
  - raw-content field-name denylist
  - field-name normalization (NFKC + casefold + separator strip, SF-1)
  - non-ASCII field-name rejection (homoglyph defense, SF-1)
  - oversize-blob length gate
  - secret-shaped value patterns (incl. SF-2 widened corpus)
  - recursive nested walk
  - observation-kind provenance requirement
  - commitment-chain construction gate
  - position/index commitment (reorder-evidence)
  - previous-commitment folding (splice-evidence)
  - divergence localization (verify returns the true first index)
  - tenant match gate (cross-tenant non-leak)
"""

from __future__ import annotations

import pytest
from saena_domain.measurement.evidence import (
    EvidenceBundleManifest,
    EvidenceDomainError,
    EvidenceEntry,
    EvidenceKind,
    EvidenceMetadata,
    RawContentRejectedError,
    _compute_commitment,
    compute_manifest_hash,
    entry_for_tenant,
    guard_evidence_fields,
    verify_manifest,
)

from .conftest import complete_entries, ref, sealed_bundle


def test_mutation_field_name_denylist_active() -> None:
    # delete the forbidden-name check → this passes (bug). Guard present → raises.
    with pytest.raises(RawContentRejectedError):
        guard_evidence_fields({"raw_content": "short"})


def test_mutation_name_normalization_active() -> None:
    # delete the NFKC/casefold/separator normalization → camelCase and kebab
    # variants slip past the snake_case marker list (bug)
    with pytest.raises(RawContentRejectedError):
        guard_evidence_fields({"rawContent": "short"})
    with pytest.raises(RawContentRejectedError):
        guard_evidence_fields({"raw-content": "short"})


def test_mutation_non_ascii_name_rejection_active() -> None:
    # delete the non-ASCII field-name rejection → a Cyrillic homoglyph name
    # ("raw_сontent" with U+0441) bypasses the denylist (bug)
    with pytest.raises(RawContentRejectedError):
        guard_evidence_fields({"raw_сontent": "short"})


def test_mutation_widened_secret_patterns_active() -> None:
    # delete any SF-2 widened pattern → its token slips through (bug)
    for token in ("xoxb-1234567890-abcdef", "AIza" + "B" * 35, "sk_live_a1b2c3d4e5f6"):
        with pytest.raises(RawContentRejectedError):
            guard_evidence_fields({"x": token})


def test_mutation_verify_localization_exact() -> None:
    # weaken localization back to a constant (e.g. always 0) → this fails:
    # the divergence really is at index 5
    entries = complete_entries()
    original = sealed_bundle(entries)
    tampered = list(entries)
    tampered[5] = EvidenceEntry(kind=tampered[5].kind, ref=ref("f"))
    forged = EvidenceBundleManifest.model_construct(
        tenant_id=original.tenant_id,
        run_id=original.run_id,
        experiment_id=original.experiment_id,
        entries=tuple(tampered),
        entry_commitments=original.entry_commitments,
        manifest_hash=original.manifest_hash,
    )
    assert verify_manifest(forged) == (False, 5)


def test_mutation_oversize_gate_active() -> None:
    with pytest.raises(RawContentRejectedError):
        guard_evidence_fields({"note": "z" * (4096 + 1)})
    # boundary: exactly-at-limit is allowed (proves the gate is `>` not `>=`)
    guard_evidence_fields({"note": "z" * 4096})


def test_mutation_secret_pattern_active() -> None:
    with pytest.raises(RawContentRejectedError):
        guard_evidence_fields({"x": "AKIA" + "B" * 16})


def test_mutation_recursive_walk_active() -> None:
    # a secret one level deep is only caught if the recursive walk exists
    with pytest.raises(RawContentRejectedError):
        guard_evidence_fields({"outer": {"inner": "sk-" + "Q" * 30}})


def test_mutation_observation_provenance_required() -> None:
    # delete the observation-kind provenance check → bare metadata passes (bug)
    with pytest.raises(EvidenceDomainError):
        EvidenceEntry(
            kind=EvidenceKind.BASELINE_OBSERVATION, ref=ref("a"), metadata=EvidenceMetadata()
        )


def test_mutation_manifest_hash_gate_active() -> None:
    # delete the construction hash check → a wrong hash is accepted (bug)
    with pytest.raises(EvidenceDomainError):
        EvidenceBundleManifest(
            tenant_id="t",
            run_id="r",
            experiment_id="e",
            entries=complete_entries(),
            manifest_hash="sha256:" + "0" * 64,
        )


def test_mutation_index_commitment_active() -> None:
    # If the commitment did NOT fold in `index`, reordering entries whose
    # content hashes differ could still be masked in edge cases. Directly
    # assert index sensitivity of the commitment primitive.
    h = "sha256:" + "a" * 64
    c_at_0 = _compute_commitment(None, h, 0)
    c_at_1 = _compute_commitment(None, h, 1)
    assert c_at_0 != c_at_1


def test_mutation_prev_commitment_folding_active() -> None:
    # If prev were not folded in, two entries with the same content hash at
    # the same index but different history would collide. Assert prev matters.
    h = "sha256:" + "a" * 64
    c_prev_none = _compute_commitment(None, h, 0)
    c_prev_x = _compute_commitment("sha256:" + "9" * 64, h, 0)
    assert c_prev_none != c_prev_x


def test_mutation_reorder_detected_end_to_end() -> None:
    entries = complete_entries()
    base = compute_manifest_hash(entries)
    swapped = (entries[2], entries[1], entries[0], *entries[3:])
    assert compute_manifest_hash(swapped) != base


def test_mutation_tenant_match_gate_active() -> None:
    # delete the tenant check → cross-tenant read leaks the entry (bug)
    m = sealed_bundle()
    assert entry_for_tenant(m, tenant_id="attacker-co", index=0) is None
    assert entry_for_tenant(m, tenant_id=m.tenant_id, index=0) is m.entries[0]
