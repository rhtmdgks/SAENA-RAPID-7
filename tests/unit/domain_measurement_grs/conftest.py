"""Shared builders/doubles for saena_domain.measurement.grs tests.

The verifier is an INJECTED protocol (never a live crypto library): these
doubles let a unit test drive every fail-closed branch of
``load_policy_bundle`` deterministically and with no I/O — a valid-signature
verifier, an always-reject verifier, and (the absent-verifier case) ``None``
passed straight through.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from saena_domain.audit.canonical import canonical_json, sha256_hex
from saena_domain.measurement.grs import (
    GrsPolicyBundle,
    PolicyProvenance,
    compute_bundle_hash,
)

# A representative opaque threshold map. The MECHANISM treats these values as
# opaque — the test suite never asserts any of these numbers is "the"
# production threshold (production values are a HUMAN decision, §13-7). They
# exist only to exercise the strict accessor / eligibility branches.
FIXTURE_VALUES: Mapping[str, Any] = {
    "min_grs": 0.7,
    "min_independent_layers": 2,
    "max_open_incidents": 0,
}


def canonical_bundle_payload(*, version: str, values: Mapping[str, Any], provenance: str) -> str:
    """Reproduce the exact canonical byte-string the module hashes, so a test
    can assert byte-for-byte agreement rather than trusting the module's own
    hash back to itself."""
    return canonical_json({"provenance": provenance, "values": dict(values), "version": version})


def signed_digest_for(*, version: str, values: Mapping[str, Any], provenance: str) -> str:
    """The digest a legitimate signer would have signed — sha256 of the
    canonical payload."""
    return sha256_hex(
        canonical_bundle_payload(version=version, values=values, provenance=provenance)
    )


class AcceptingVerifier:
    """A verifier double that accepts a signature IFF it equals the string
    ``"sig:" + signed_digest``. Deterministic, no crypto — but it still binds
    the signature to the exact signed digest, so a hash-mismatch or a
    tampered-values bundle is genuinely rejected, not waved through."""

    def verify(self, signed_digest: str, signature: str) -> bool:
        return signature == "sig:" + signed_digest


class RejectingVerifier:
    """A verifier double that rejects every signature (models an invalid
    signature / wrong key)."""

    def verify(self, signed_digest: str, signature: str) -> bool:
        return False


class RaisingVerifier:
    """A verifier double whose ``verify`` raises — models a broken/misbehaving
    verifier implementation. ``load_policy_bundle`` must treat this as REFUSED
    (fail-closed), never propagate the exception as an accidental allow."""

    def verify(self, signed_digest: str, signature: str) -> bool:
        raise RuntimeError("verifier backend unavailable")


def valid_signature_for(*, version: str, values: Mapping[str, Any], provenance: str) -> str:
    """The signature string ``AcceptingVerifier`` will accept for this bundle."""
    return "sig:" + signed_digest_for(version=version, values=values, provenance=provenance)


def raw_production_bundle(
    *, version: str = "1.0.0", values: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """A raw (untrusted, pre-verification) production-bundle mapping as it
    would arrive from bytes — plain dict, no marker, provenance=production."""
    return {
        "version": version,
        "values": dict(values if values is not None else FIXTURE_VALUES),
        "provenance": "production",
    }


def make_production_bundle(
    *, version: str = "1.0.0", values: Mapping[str, Any] | None = None
) -> GrsPolicyBundle:
    """Directly construct a production-provenance bundle object (bypassing the
    loader) — used to test evaluation independently of loading."""
    return GrsPolicyBundle(
        version=version,
        values=dict(values if values is not None else FIXTURE_VALUES),
        provenance=PolicyProvenance.PRODUCTION,
    )


def eligible_inputs() -> dict[str, Any]:
    """Inputs that clear the FIXTURE thresholds."""
    return {"grs": 0.9, "independent_layers": 3, "open_incidents": 0}


def denying_inputs() -> dict[str, Any]:
    """Inputs that fail at least one FIXTURE threshold."""
    return {"grs": 0.1, "independent_layers": 3, "open_incidents": 0}


__all__ = [
    "FIXTURE_VALUES",
    "AcceptingVerifier",
    "RejectingVerifier",
    "RaisingVerifier",
    "canonical_bundle_payload",
    "compute_bundle_hash",
    "denying_inputs",
    "eligible_inputs",
    "make_production_bundle",
    "raw_production_bundle",
    "signed_digest_for",
    "valid_signature_for",
]
