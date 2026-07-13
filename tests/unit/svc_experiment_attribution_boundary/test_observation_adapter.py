"""Tests for `saena_experiment_attribution.boundary.observation_adapter`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from saena_experiment_attribution.boundary.errors import BasisDerivationError
from saena_experiment_attribution.boundary.observation_adapter import (
    CapturedObservation,
    ObservationIngestAdapter,
    derive_evidence_basis_id,
)

_TS = datetime(2026, 7, 5, 0, 0, 0, tzinfo=UTC)


def _observation(
    *, observation_id: str = "obs-1", artifact_hash: str = "sha256:" + "a" * 64, value: float = 1.0
) -> CapturedObservation:
    return CapturedObservation(
        observation_id=observation_id, artifact_hash=artifact_hash, value=value, observed_at=_TS
    )


def test_same_artifact_hash_derives_same_basis_id():
    hash_value = "sha256:" + "a" * 64
    basis_1 = derive_evidence_basis_id(hash_value)
    basis_2 = derive_evidence_basis_id(hash_value)

    assert basis_1 == basis_2


def test_different_artifact_hash_derives_different_basis_id():
    basis_a = derive_evidence_basis_id("sha256:" + "a" * 64)
    basis_b = derive_evidence_basis_id("sha256:" + "b" * 64)

    assert basis_a != basis_b


def test_basis_id_is_sha256_shaped_and_not_the_artifact_hash_itself():
    artifact_hash = "sha256:" + "c" * 64
    basis = derive_evidence_basis_id(artifact_hash)

    assert basis.startswith("sha256:")
    assert len(basis) == len("sha256:") + 64
    assert basis != artifact_hash  # derived, not a passthrough


def test_derivation_deterministic_across_many_calls():
    hash_value = "sha256:" + "d" * 64
    results = {derive_evidence_basis_id(hash_value) for _ in range(50)}

    assert len(results) == 1


def test_empty_artifact_hash_refused_fail_closed():
    with pytest.raises(BasisDerivationError):
        derive_evidence_basis_id("")


def test_whitespace_only_artifact_hash_refused_fail_closed():
    with pytest.raises(BasisDerivationError):
        derive_evidence_basis_id("   ")


def test_caller_cannot_assert_an_arbitrary_basis_id():
    """The adapter's public surface has NO parameter that accepts a
    caller-supplied basis id -- basis_id_for/to_cell_observation only ever
    take the CapturedObservation (whose only hash-shaped field is
    artifact_hash)."""
    import inspect

    basis_id_for_params = set(inspect.signature(ObservationIngestAdapter.basis_id_for).parameters)
    to_cell_params = set(inspect.signature(ObservationIngestAdapter.to_cell_observation).parameters)

    assert "evidence_basis_id" not in basis_id_for_params
    assert "basis_id" not in basis_id_for_params
    assert "evidence_basis_id" not in to_cell_params
    assert "basis_id" not in to_cell_params


def test_captured_observation_has_no_caller_basis_id_field():
    """w5-12 critic SF-1: guard the INPUT dataclass's field set, not only the
    adapter method signatures. A future PR adding a caller-asserted basis id
    directly onto CapturedObservation (which the adapter might then prefer over
    derivation) would otherwise ship undetected. basis id must ALWAYS be
    derived from artifact_hash (w5-06 trust-boundary obligation)."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(CapturedObservation)}
    assert field_names == {"observation_id", "artifact_hash", "value", "observed_at"}
    assert "evidence_basis_id" not in field_names
    assert "basis_id" not in field_names


def test_to_cell_observation_builds_expected_shape():
    observations = (
        _observation(observation_id="o1", value=1.0),
        _observation(observation_id="o2", value=2.0),
    )

    cell = ObservationIngestAdapter.to_cell_observation(observations)

    assert cell.repeat_values == (1.0, 2.0)
    assert cell.observation_ids == ("o1", "o2")
    assert cell.timestamps == (_TS, _TS)


def test_observation_id_passthrough_unchanged():
    """w5-05 dedup obligation: observation_id is passed through verbatim,
    never regenerated, so the DiD engine's own dedup can use it."""
    observations = (_observation(observation_id="stable-id-123", value=1.0),)

    cell = ObservationIngestAdapter.to_cell_observation(observations)

    assert cell.observation_ids == ("stable-id-123",)


def test_to_cell_observation_refuses_malformed_artifact_hash():
    observations = (_observation(artifact_hash="   "),)

    with pytest.raises(BasisDerivationError):
        ObservationIngestAdapter.to_cell_observation(observations)


def test_basis_id_for_matches_derive_evidence_basis_id():
    observation = _observation(artifact_hash="sha256:" + "e" * 64)

    assert ObservationIngestAdapter.basis_id_for(observation) == derive_evidence_basis_id(
        "sha256:" + "e" * 64
    )
