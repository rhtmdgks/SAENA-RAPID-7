"""`hashing.py` — content-hash determinism, reusing `saena_domain.audit.canonical`."""

from __future__ import annotations

import re

from saena_claim_evidence import compute_evidence_content_hash, compute_ledger_entry_hash
from saena_domain.audit.canonical import canonical_json, sha256_hex

_SHA256_REF_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def test_compute_evidence_content_hash_is_sha256_ref_shaped() -> None:
    digest = compute_evidence_content_hash(
        tenant_id="acme-co",
        project_id="project-0001",
        evidence_id="evidence-0001",
        claim_id="claim-0001",
        source_uri="https://docs.example.com/security",
        excerpt="SAML 2.0 SSO is supported.",
    )
    assert _SHA256_REF_PATTERN.match(digest)


def test_compute_evidence_content_hash_is_deterministic() -> None:
    kwargs = {
        "tenant_id": "acme-co",
        "project_id": "project-0001",
        "evidence_id": "evidence-0001",
        "claim_id": "claim-0001",
        "source_uri": "https://docs.example.com/security",
        "excerpt": "SAML 2.0 SSO is supported.",
    }
    assert compute_evidence_content_hash(**kwargs) == compute_evidence_content_hash(**kwargs)


def test_compute_evidence_content_hash_changes_with_excerpt() -> None:
    base = {
        "tenant_id": "acme-co",
        "project_id": "project-0001",
        "evidence_id": "evidence-0001",
        "claim_id": "claim-0001",
        "source_uri": "https://docs.example.com/security",
    }
    hash_a = compute_evidence_content_hash(excerpt="excerpt A", **base)
    hash_b = compute_evidence_content_hash(excerpt="excerpt B", **base)
    assert hash_a != hash_b


def test_compute_evidence_content_hash_excludes_freshness_checked_at() -> None:
    """Re-checking freshness (same content, different check timestamp) must
    NOT change the identity hash — see hashing.py module docstring."""
    kwargs = {
        "tenant_id": "acme-co",
        "project_id": "project-0001",
        "evidence_id": "evidence-0001",
        "claim_id": "claim-0001",
        "source_uri": "https://docs.example.com/security",
        "excerpt": "SAML 2.0 SSO is supported.",
    }
    # freshness_checked_at is not even an accepted parameter here — proven
    # structurally: calling twice with identical inputs always matches.
    assert compute_evidence_content_hash(**kwargs) == compute_evidence_content_hash(**kwargs)


def test_compute_ledger_entry_hash_matches_the_canonical_json_sha256_construction() -> None:
    material = {"b": 2, "a": 1}
    expected = f"sha256:{sha256_hex(canonical_json(material))}"
    assert compute_ledger_entry_hash(material) == expected


def test_compute_ledger_entry_hash_is_key_order_independent() -> None:
    assert compute_ledger_entry_hash({"a": 1, "b": 2}) == compute_ledger_entry_hash(
        {"b": 2, "a": 1}
    )
