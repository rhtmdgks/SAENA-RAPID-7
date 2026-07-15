"""`ObservationIngestAdapter` — maps `observation.captured.v1`-shaped records
into DiD `CellObservation` inputs (w5-12).

## `evidence_basis_id` MUST be derived, never caller-asserted (w5-06 trust
## boundary obligation)

`b_gate.py`'s module docstring is explicit: "(layer, evidence_basis_id)
independence is caller-asserted... Upstream owners are w5-04 ... and the
w5-12 service boundary: THEY must derive `evidence_basis_id` from the actual
evidence (e.g. content-addressed refs), never accept caller-supplied free
strings." This adapter is that derivation point for observation-sourced
signals: `derive_evidence_basis_id` computes a deterministic
`sha256:<hex>` digest FROM the observation's artifact hash — a caller can
never simply pass in an arbitrary basis-id string and have it accepted as
the observation's basis.

Determinism / collision properties (pinned by tests):
- Same artifact hash → same basis id, on every call, every process.
- Different artifact hash → different basis id (collision-free within the
  bounds of SHA-256).

Reuses `saena_domain.audit.canonical.sha256_hex` verbatim — no new hashing
rule invented (matches the wave5-plan.md "reuse, not reinvention" convention
used throughout `saena_domain.measurement`).

## `observation_id` passthrough (w5-05 dedup obligation)

`did.py`'s `CellObservation.observation_ids` docstring notes that, when
`observation_ids` are ABSENT, "guaranteeing repeat uniqueness is then
explicitly an UPSTREAM obligation of ... the w5-12 experiment-attribution
service boundary". This adapter therefore ALWAYS passes the incoming
`observation_id` straight through into `CellObservation.observation_ids` —
never regenerated, never dropped, never overwritten — so the DiD engine's
own dedup (`_dedupe_repeats`) has the identity it needs to collapse
byte-identical replayed repeats and flag conflicting ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from saena_domain.audit.canonical import sha256_hex
from saena_domain.measurement.did import CellObservation

from .errors import BasisDerivationError

_SHA256_HEX_RE_LENGTH = 64
_SHA256_PREFIX = "sha256:"


@dataclass(frozen=True, slots=True)
class CapturedObservation:
    """One `observation.captured.v1`-shaped record (already envelope-parsed).

    `artifact_hash` is the content-addressed hash of the captured observation
    artifact (e.g. snapshot/response hash) — the SOLE input
    `derive_evidence_basis_id` derives a basis id from. `value` is the metric
    reading; `observed_at` is the observation timestamp; `observation_id` is
    the stable per-repeat identity passed through to `CellObservation`
    untouched.
    """

    observation_id: str
    artifact_hash: str
    value: float
    observed_at: datetime


def derive_evidence_basis_id(artifact_hash: str) -> str:
    """Deterministically derive an `evidence_basis_id` from an artifact hash.

    NEVER accepts a caller-asserted basis id — the only input is the
    artifact hash itself, so two observations that share an artifact hash
    (the same underlying evidence) always derive the identical basis id, and
    two observations with different artifact hashes derive different basis
    ids (collision-free within the bounds of SHA-256 — the same guarantee
    `saena_domain.audit.canonical.sha256_hex` gives every other hash-derived
    identifier in this codebase).

    Raises `BasisDerivationError` for an empty/whitespace-only artifact hash
    — there is no fallback derivation for a malformed input; a basis id is
    refused outright rather than derived from garbage.
    """
    normalized = artifact_hash.strip()
    if not normalized:
        raise BasisDerivationError(
            "cannot derive an evidence_basis_id from an empty artifact_hash",
            context={},
        )
    # Hash-of-hash: derives a NEW stable identifier namespaced to "basis
    # derivation" rather than re-emitting the artifact hash verbatim (so a
    # basis id is legible as "derived", never confusable with the artifact
    # hash it also has access to) while remaining fully deterministic.
    digest = sha256_hex(f"evidence_basis_id:{normalized}")
    return f"{_SHA256_PREFIX}{digest}"


class ObservationIngestAdapter:
    """Maps `CapturedObservation` records into DiD `CellObservation` inputs.

    Pure mapping — no I/O, no store. `evidence_basis_id` for the resulting
    signal is derived (never accepted as a parameter) via
    `derive_evidence_basis_id`; `observation_id` is passed through unchanged
    for every repeat.
    """

    @staticmethod
    def to_cell_observation(observations: tuple[CapturedObservation, ...]) -> CellObservation:
        """Build one `CellObservation` from a tuple of captured repeats.

        Raises `BasisDerivationError` (via `derive_evidence_basis_id`,
        called per-observation for validation even though only the FIRST
        artifact hash's derivation is surfaced by `basis_id_for`) if any
        repeat's `artifact_hash` cannot be derived from.
        """
        for observation in observations:
            derive_evidence_basis_id(observation.artifact_hash)  # validate, fail-closed
        return CellObservation(
            repeat_values=tuple(o.value for o in observations),
            timestamps=tuple(o.observed_at for o in observations),
            observation_ids=tuple(o.observation_id for o in observations),
        )

    @staticmethod
    def basis_id_for(observation: CapturedObservation) -> str:
        """The derived `evidence_basis_id` for one observation's artifact hash."""
        return derive_evidence_basis_id(observation.artifact_hash)


__all__ = [
    "CapturedObservation",
    "ObservationIngestAdapter",
    "derive_evidence_basis_id",
]
