"""`saena_citation_intelligence.ownership.classify_ownership` — rule-based
classification + calibrated-prior application, incl. competitor-not-owned
fail-closed discipline (w4-05)."""

from __future__ import annotations

import pytest
from citation_intelligence_factories import COMPETITOR_DOMAINS, TENANT_OWNED_DOMAINS
from saena_citation_intelligence.errors import OwnershipClassificationError
from saena_citation_intelligence.normalization import normalize_url
from saena_citation_intelligence.ownership import OwnershipClass, classify_ownership


def test_exact_owned_domain_match_classifies_owned() -> None:
    decision = classify_ownership(
        normalize_url("https://acme.com/product"),
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
    )
    assert decision.ownership_class == OwnershipClass.OWNED
    assert decision.confidence == 1.0
    assert "tenant_owned_domain" in decision.matched_rule


def test_owned_subdomain_match_classifies_owned() -> None:
    decision = classify_ownership(
        normalize_url("https://shop.acme.com/product"),
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
    )
    assert decision.ownership_class == OwnershipClass.OWNED


def test_lookalike_domain_is_not_a_subdomain_match() -> None:
    """`notacme.com` shares a suffix string with `acme.com` but is NOT a
    `.`-boundary subdomain — must not be classified OWNED."""
    decision = classify_ownership(
        normalize_url("https://notacme.com/product"),
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
    )
    assert decision.ownership_class != OwnershipClass.OWNED


def test_exact_competitor_domain_match_classifies_competitor() -> None:
    decision = classify_ownership(
        normalize_url("https://rival.com/product"),
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
    )
    assert decision.ownership_class == OwnershipClass.COMPETITOR
    assert decision.confidence == 1.0
    assert "competitor_domain" in decision.matched_rule


def test_competitor_subdomain_match_classifies_competitor() -> None:
    decision = classify_ownership(
        normalize_url("https://blog.rival.com/post"),
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
    )
    assert decision.ownership_class == OwnershipClass.COMPETITOR


def test_domain_in_both_owned_and_competitor_sets_is_never_owned() -> None:
    """Fail-closed discipline (task brief): a competitor citation is NEVER
    classified as owned. A caller-input conflict (same domain in both sets)
    must resolve to COMPETITOR, not OWNED."""
    conflicting = frozenset({"conflict.com"})
    decision = classify_ownership(
        normalize_url("https://conflict.com/x"),
        tenant_owned_domains=conflicting,
        competitor_domains=conflicting,
    )
    assert decision.ownership_class == OwnershipClass.COMPETITOR


def test_competitor_priority_holds_even_when_owned_checked_would_also_match() -> None:
    """A subdomain of a competitor domain that ALSO happens to be a
    subdomain of an owned domain (pathological caller input) must still
    resolve to COMPETITOR — never OWNED — under this module's fail-closed
    ordering."""
    owned = frozenset({"shared.example.com"})
    competitor = frozenset({"shared.example.com"})
    decision = classify_ownership(
        normalize_url("https://shared.example.com/x"),
        tenant_owned_domains=owned,
        competitor_domains=competitor,
    )
    assert decision.ownership_class == OwnershipClass.COMPETITOR


def test_known_aggregator_domain_classifies_third_party_with_high_confidence() -> None:
    decision = classify_ownership(
        normalize_url("https://en.wikipedia.org/wiki/Example"),
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
    )
    assert decision.ownership_class == OwnershipClass.THIRD_PARTY
    assert decision.confidence == pytest.approx(0.9)
    assert decision.matched_rule.startswith("calibrated_prior:known_aggregator")


def test_unmatched_generic_host_classifies_third_party_with_low_confidence() -> None:
    decision = classify_ownership(
        normalize_url("https://some-random-blog.example/post"),
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
    )
    assert decision.ownership_class == OwnershipClass.THIRD_PARTY
    assert decision.confidence == pytest.approx(0.3)
    assert decision.matched_rule == "calibrated_prior:generic"


def test_calibrated_prior_never_produces_owned_or_competitor() -> None:
    """The calibrated prior (stage 2) is reachable only when no rule
    matched — by construction it can only ever return THIRD_PARTY."""
    for raw in (
        "https://en.wikipedia.org/wiki/X",
        "https://totally-unknown-host.example/x",
    ):
        decision = classify_ownership(
            normalize_url(raw), tenant_owned_domains=frozenset(), competitor_domains=frozenset()
        )
        assert decision.ownership_class == OwnershipClass.THIRD_PARTY


def test_empty_owned_and_competitor_domains_never_raises_and_falls_to_prior() -> None:
    decision = classify_ownership(
        normalize_url("https://example.com/x"),
        tenant_owned_domains=frozenset(),
        competitor_domains=frozenset(),
    )
    assert decision.ownership_class == OwnershipClass.THIRD_PARTY


def test_empty_domain_entry_in_owned_set_raises_classification_error() -> None:
    with pytest.raises(OwnershipClassificationError):
        classify_ownership(
            normalize_url("https://example.com/x"),
            tenant_owned_domains=frozenset({""}),
            competitor_domains=frozenset(),
        )


def test_whitespace_only_domain_entry_in_competitor_set_raises() -> None:
    with pytest.raises(OwnershipClassificationError):
        classify_ownership(
            normalize_url("https://example.com/x"),
            tenant_owned_domains=frozenset(),
            competitor_domains=frozenset({"   "}),
        )


def test_confidence_is_always_in_closed_unit_interval() -> None:
    for raw in (
        "https://acme.com/x",
        "https://rival.com/x",
        "https://en.wikipedia.org/wiki/x",
        "https://random-host.example/x",
    ):
        decision = classify_ownership(
            normalize_url(raw),
            tenant_owned_domains=TENANT_OWNED_DOMAINS,
            competitor_domains=COMPETITOR_DOMAINS,
        )
        assert 0.0 <= decision.confidence <= 1.0


def test_ownership_decision_is_frozen() -> None:
    decision = classify_ownership(
        normalize_url("https://example.com/x"),
        tenant_owned_domains=frozenset(),
        competitor_domains=frozenset(),
    )
    with pytest.raises(AttributeError):
        decision.confidence = 0.9  # type: ignore[misc]
