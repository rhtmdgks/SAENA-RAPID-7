"""Ownership classification — rule-based classifier + fixed calibrated prior
(w4-05).

Design authority: `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md`
§3.6 학습 단계 P0 row: "규칙 기반 + calibrated prior" — "안전한 후보
선별·초기 실행", 출시 기준 "데이터 부족 시 과장 방지" (never overstate a
classification the classifier is not confident about). This module is P0
scope ONLY: no model training, no ML inference at runtime — "calibrated
prior" here means a fixed, documented probability/weight table
(`_CALIBRATED_PRIOR`), not a trained/learned parameter.

Classification is a strict two-stage pipeline:

    1. Rule-based domain match (deterministic, exact/suffix host match
       against caller-supplied `tenant_owned_domains`/`competitor_domains`
       sets) — decides `OwnershipClass` outright when a match is found.
    2. Calibrated prior (only reached when NO rule matched) — a fixed
       weight table keyed by structural URL/host signals (see
       `_CALIBRATED_PRIOR` below) assigns a `THIRD_PARTY` classification
       with a documented, bounded `confidence` in `[0.0, 1.0)`. The prior
       NEVER outputs `OWNED` or `COMPETITOR` — those two classes are only
       ever rule-derived (see fail-closed discipline below), matching the
       P0 "안전한 후보 선별" mandate: an unmatched, uncertain citation is
       always THIRD_PARTY with a documented, non-overstated confidence,
       never guessed into a more consequential class.

Fail-closed ownership discipline (task brief, "same ownership discipline as
entity-resolution"): a competitor-domain match is checked BEFORE an
owned-domain match and always wins on conflict — a URL whose host matches
BOTH `tenant_owned_domains` and `competitor_domains` (a caller input error,
since a real domain cannot be simultaneously first-party and a competitor's)
is classified `COMPETITOR`, never `OWNED`. A competitor citation can NEVER
be classified `OWNED` by any code path in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from saena_citation_intelligence.errors import OwnershipClassificationError

# P0 calibrated prior — FIXED, documented weight table (task brief:
# "a fixed, documented probability/weight table"). Keyed by a coarse,
# deterministic structural signal derived from the host only (no ML
# features, no learned parameters). Every value is a confidence in the
# THIRD_PARTY classification that stage 2 always returns — never adjusted
# at runtime, never fit against observed data. Revising these numbers is a
# P0-scope documentation change (this table), not a model-training event.
#
#   "known_aggregator": platform/publisher domains with a well-known
#       syndication/aggregation role (Reddit, Wikipedia, YouTube, ...) —
#       reliably third-party, high confidence.
#   "generic": every other unmatched host — still third-party (P0 never
#       promotes an unmatched host to OWNED/COMPETITOR) but LOW confidence,
#       per the design spec's explicit "데이터 부족 시 과장 방지" mandate:
#       an unrecognized host is not confidently anything beyond "not one of
#       the caller's known owned/competitor domains".
_CALIBRATED_PRIOR: dict[str, float] = {
    "known_aggregator": 0.9,
    "generic": 0.3,
}

# Fixed, documented allow-list of known third-party aggregator/publisher
# domains (P0 calibrated-prior input signal only — never promoted to OWNED
# or COMPETITOR by this table; a caller's own `competitor_domains` set
# always takes priority over this list, per the fail-closed ordering in
# `classify_ownership`). Suffix-matched, same as tenant/competitor domains.
_KNOWN_AGGREGATOR_DOMAINS: frozenset[str] = frozenset(
    {
        "wikipedia.org",
        "reddit.com",
        "youtube.com",
        "linkedin.com",
        "medium.com",
        "quora.com",
    }
)


class OwnershipClass(StrEnum):
    """Closed classification vocabulary for a normalized citation host.

    `OWNED` and `COMPETITOR` are reachable ONLY via an exact/suffix rule
    match against caller-supplied domain sets (stage 1) — the calibrated
    prior (stage 2) can only ever produce `THIRD_PARTY`.
    """

    OWNED = "owned"
    COMPETITOR = "competitor"
    THIRD_PARTY = "third_party"


@dataclass(frozen=True, slots=True)
class OwnershipDecision:
    """Immutable classification result for one normalized citation host.

    `confidence` is always `1.0` for a rule-derived decision (`OWNED`/
    `COMPETITOR` — exact domain-set membership is certain, not probabilistic)
    and always the `_CALIBRATED_PRIOR`-table value for a `THIRD_PARTY`
    decision reached via stage 2 (never `1.0` — the prior's whole point is to
    never overstate confidence in an unmatched host).
    """

    ownership_class: OwnershipClass
    confidence: float
    matched_rule: str


def _host_of(normalized_uri: str) -> str:
    """Extract the host component from an already-normalized citation URI
    (`scheme://host[:port]/path`, no query/fragment — see `normalization.
    normalize_url`). Pure string slicing, no re-parsing via `urlsplit`
    needed since the input shape is already this module's own guaranteed
    output contract.
    """
    after_scheme = normalized_uri.split("://", 1)[-1]
    authority = after_scheme.split("/", 1)[0]
    return authority.split(":", 1)[0]


def _suffix_matches(host: str, domains: frozenset[str]) -> str | None:
    """Return the matching domain from `domains` if `host` equals it or is a
    subdomain of it (suffix match on a `.`-boundary — `shop.example.com`
    matches `example.com` but `notexample.com` does NOT), else `None`.
    """
    for domain in domains:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def _validate_domain_set(domains: frozenset[str], *, field_name: str) -> None:
    for domain in domains:
        if not domain or not domain.strip():
            raise OwnershipClassificationError(
                f"{field_name} contains an empty/whitespace-only domain entry",
                context={"field_name": field_name},
            )


def classify_ownership(
    normalized_uri: str,
    *,
    tenant_owned_domains: frozenset[str],
    competitor_domains: frozenset[str],
) -> OwnershipDecision:
    """Classify `normalized_uri`'s host as owned/competitor/third-party.

    `tenant_owned_domains`/`competitor_domains` are caller-supplied,
    tenant-scoped domain sets (this module performs NO lookup of its own —
    the caller owns sourcing these, e.g. from `entity-resolution-service`'s
    entity graph per the wave4-plan DAG's declared upstream dependency).

    Ordering (fail-closed — see module docstring): competitor match is
    checked FIRST. A host matching both sets is `COMPETITOR`.

    Raises `OwnershipClassificationError` if either domain set contains an
    empty/whitespace-only entry (malformed classifier input, distinct from
    a normal "no match" outcome).
    """
    _validate_domain_set(tenant_owned_domains, field_name="tenant_owned_domains")
    _validate_domain_set(competitor_domains, field_name="competitor_domains")

    host = _host_of(normalized_uri)

    competitor_match = _suffix_matches(host, competitor_domains)
    if competitor_match is not None:
        return OwnershipDecision(
            ownership_class=OwnershipClass.COMPETITOR,
            confidence=1.0,
            matched_rule=f"competitor_domain:{competitor_match}",
        )

    owned_match = _suffix_matches(host, tenant_owned_domains)
    if owned_match is not None:
        return OwnershipDecision(
            ownership_class=OwnershipClass.OWNED,
            confidence=1.0,
            matched_rule=f"tenant_owned_domain:{owned_match}",
        )

    aggregator_match = _suffix_matches(host, _KNOWN_AGGREGATOR_DOMAINS)
    if aggregator_match is not None:
        return OwnershipDecision(
            ownership_class=OwnershipClass.THIRD_PARTY,
            confidence=_CALIBRATED_PRIOR["known_aggregator"],
            matched_rule=f"calibrated_prior:known_aggregator:{aggregator_match}",
        )

    return OwnershipDecision(
        ownership_class=OwnershipClass.THIRD_PARTY,
        confidence=_CALIBRATED_PRIOR["generic"],
        matched_rule="calibrated_prior:generic",
    )


__all__ = ["OwnershipClass", "OwnershipDecision", "classify_ownership"]
