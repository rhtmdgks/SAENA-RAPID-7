"""`evaluate_claim_publishability` — fail-closed core requirement."""

from __future__ import annotations

from datetime import timedelta

import pytest
from claim_evidence_factories import NOW, build_evidence, stale_timestamp
from saena_claim_evidence import (
    EvidenceFreshnessPolicy,
    EvidenceLinkStatus,
    evaluate_claim_publishability,
)

POLICY = EvidenceFreshnessPolicy(max_age_seconds=3600)


def test_no_evidence_is_not_publishable() -> None:
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(),
        link_statuses={},
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("no_evidence",)
    assert result.supporting_evidence_ids == ()


def test_fresh_linked_evidence_is_publishable() -> None:
    evidence = build_evidence(freshness_checked_at=NOW)
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(evidence,),
        link_statuses={"evidence-0001": EvidenceLinkStatus.LINKED},
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is True
    assert result.blocking_reasons == ()
    assert result.supporting_evidence_ids == ("evidence-0001",)


def test_stale_evidence_is_not_publishable() -> None:
    evidence = build_evidence(freshness_checked_at=stale_timestamp(older_than=timedelta(hours=2)))
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(evidence,),
        link_statuses={"evidence-0001": EvidenceLinkStatus.LINKED},
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("stale",)


def test_blocked_evidence_is_not_publishable() -> None:
    evidence = build_evidence(freshness_checked_at=NOW)
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(evidence,),
        link_statuses={"evidence-0001": EvidenceLinkStatus.BLOCKED},
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("blocked",)


def test_unknown_link_status_defaults_to_blocked_fail_closed() -> None:
    """An evidence record with no entry at all in `link_statuses` must be
    treated as BLOCKED (fail closed), never silently treated as LINKED."""
    evidence = build_evidence(freshness_checked_at=NOW)
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(evidence,),
        link_statuses={},
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("blocked",)


def test_one_fresh_linked_record_among_several_bad_ones_is_still_publishable() -> None:
    fresh = build_evidence(evidence_id="evidence-fresh", freshness_checked_at=NOW)
    stale = build_evidence(
        evidence_id="evidence-stale",
        freshness_checked_at=stale_timestamp(older_than=timedelta(hours=2)),
    )
    blocked = build_evidence(evidence_id="evidence-blocked", freshness_checked_at=NOW)
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(fresh, stale, blocked),
        link_statuses={
            "evidence-fresh": EvidenceLinkStatus.LINKED,
            "evidence-stale": EvidenceLinkStatus.LINKED,
            "evidence-blocked": EvidenceLinkStatus.BLOCKED,
        },
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is True
    assert result.supporting_evidence_ids == ("evidence-fresh",)


def test_all_bad_records_reports_every_distinct_reason() -> None:
    stale = build_evidence(
        evidence_id="evidence-stale",
        freshness_checked_at=stale_timestamp(older_than=timedelta(hours=2)),
    )
    blocked = build_evidence(evidence_id="evidence-blocked", freshness_checked_at=NOW)
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(stale, blocked),
        link_statuses={
            "evidence-stale": EvidenceLinkStatus.LINKED,
            "evidence-blocked": EvidenceLinkStatus.BLOCKED,
        },
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("blocked", "stale")


def test_evidence_checked_in_the_future_is_treated_as_not_fresh() -> None:
    """A `freshness_checked_at` after `now` is a data-integrity anomaly —
    fail closed rather than silently trusting it."""
    from_the_future = build_evidence(freshness_checked_at=NOW + timedelta(hours=1))
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(from_the_future,),
        link_statuses={"evidence-0001": EvidenceLinkStatus.LINKED},
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("stale",)


def test_freshness_policy_rejects_non_positive_max_age() -> None:
    with pytest.raises(ValueError, match="positive"):
        EvidenceFreshnessPolicy(max_age_seconds=0)
    with pytest.raises(ValueError, match="positive"):
        EvidenceFreshnessPolicy(max_age_seconds=-1)


def test_evidence_exactly_at_the_boundary_is_fresh() -> None:
    evidence = build_evidence(freshness_checked_at=stale_timestamp(older_than=timedelta(hours=1)))
    result = evaluate_claim_publishability(
        claim_id="claim-0001",
        evidence_records=(evidence,),
        link_statuses={"evidence-0001": EvidenceLinkStatus.LINKED},
        policy=POLICY,
        now=NOW,
    )
    assert result.publishable is True
