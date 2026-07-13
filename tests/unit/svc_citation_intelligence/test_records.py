"""`saena_citation_intelligence.records` — `CitationRecord` construction/
validation + `compute_content_hash` (w4-05, `saena_domain.audit.canonical`
reuse, no new hashing rule)."""

from __future__ import annotations

import pytest
from saena_citation_intelligence.errors import UrlNormalizationError
from saena_citation_intelligence.ownership import OwnershipClass
from saena_citation_intelligence.records import CitationRecord, compute_content_hash


def _build_record(
    *,
    tenant_id: str = "acme-co",
    citation_id: str = "cite-0001",
    normalized_uri: str = "https://example.com/product",
    content_hash: str | None = None,
    ownership_class: OwnershipClass = OwnershipClass.THIRD_PARTY,
    ownership_confidence: float = 0.3,
    matched_rule: str = "calibrated_prior:generic",
    observed_at: str = "2026-07-13T00:00:00Z",
) -> CitationRecord:
    resolved_content_hash = content_hash or compute_content_hash(
        citation_id=citation_id,
        normalized_uri=normalized_uri,
        ownership_class=ownership_class,
        ownership_confidence=ownership_confidence,
    )
    return CitationRecord(
        tenant_id=tenant_id,
        citation_id=citation_id,
        normalized_uri=normalized_uri,
        content_hash=resolved_content_hash,
        ownership_class=ownership_class,
        ownership_confidence=ownership_confidence,
        matched_rule=matched_rule,
        observed_at=observed_at,
    )


def test_compute_content_hash_is_deterministic() -> None:
    first = compute_content_hash(
        citation_id="cite-0001",
        normalized_uri="https://example.com/x",
        ownership_class=OwnershipClass.OWNED,
        ownership_confidence=1.0,
    )
    second = compute_content_hash(
        citation_id="cite-0001",
        normalized_uri="https://example.com/x",
        ownership_class=OwnershipClass.OWNED,
        ownership_confidence=1.0,
    )
    assert first == second


def test_compute_content_hash_matches_sha256_ref_pattern() -> None:
    digest = compute_content_hash(
        citation_id="cite-0001",
        normalized_uri="https://example.com/x",
        ownership_class=OwnershipClass.OWNED,
        ownership_confidence=1.0,
    )
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_compute_content_hash_differs_for_different_inputs() -> None:
    base = compute_content_hash(
        citation_id="cite-0001",
        normalized_uri="https://example.com/x",
        ownership_class=OwnershipClass.OWNED,
        ownership_confidence=1.0,
    )
    different_uri = compute_content_hash(
        citation_id="cite-0001",
        normalized_uri="https://example.com/y",
        ownership_class=OwnershipClass.OWNED,
        ownership_confidence=1.0,
    )
    assert base != different_uri


def test_valid_record_constructs() -> None:
    record = _build_record()
    assert record.citation_id == "cite-0001"
    assert record.ownership_class == OwnershipClass.THIRD_PARTY


def test_record_is_frozen() -> None:
    record = _build_record()
    with pytest.raises(AttributeError):
        record.citation_id = "other"  # type: ignore[misc]


def test_invalid_tenant_id_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(tenant_id="Not_Valid!")


def test_empty_citation_id_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(citation_id="")


def test_citation_id_too_long_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(citation_id="c" * 129)


def test_normalized_uri_with_query_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(normalized_uri="https://example.com/x?y=1")


def test_normalized_uri_with_fragment_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(normalized_uri="https://example.com/x#frag")


def test_normalized_uri_without_scheme_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(normalized_uri="example.com/x")


def test_tampered_content_hash_raises() -> None:
    """`content_hash` is re-derived and checked at construction time — a
    caller cannot pass an arbitrary/stale hash and have it silently
    accepted (defense in depth)."""
    with pytest.raises(UrlNormalizationError):
        CitationRecord(
            tenant_id="acme-co",
            citation_id="cite-0001",
            normalized_uri="https://example.com/x",
            content_hash="sha256:" + "0" * 64,
            ownership_class=OwnershipClass.THIRD_PARTY,
            ownership_confidence=0.3,
            matched_rule="calibrated_prior:generic",
            observed_at="2026-07-13T00:00:00Z",
        )


def test_confidence_above_one_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(ownership_confidence=1.5)


def test_confidence_below_zero_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(ownership_confidence=-0.1)


def test_empty_observed_at_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        _build_record(observed_at="")
