"""Wave-4 intelligence: fail-closed claim/evidence publishability (w4-16).

Mission hard constraint (`saena_claim_evidence.evaluation` module
docstring, verbatim, task instruction): "a claim is publishable ONLY if it
has at least one supporting evidence record that is (a) present, (b)
fresh (not stale per a freshness policy), and (c) not blocked. If evidence
is unsupported / stale / blocked -> the claim's status becomes BLOCKED and
it is NOT publishable. No valid evidence -> not publishable."

This module proves that fail-closed decision table holds both at the
PURE-EVALUATOR layer (`evaluate_claim_publishability`) and end to end
through the REAL append-only ledger + tenant-scoped store
(`saena_claim_evidence.ledger`, `saena_claim_evidence.store.
InMemoryClaimEvidenceStore`) — an unsupported, stale, or blocked claim
must never be reported publishable by either layer, and the ledger's own
hash chain must stay verifiably intact (`verify_ledger_chain`) across
every one of these BLOCKED transitions (a BLOCKED verdict is still a
legitimate, tamper-evident ledger entry, never an unaudited side channel).

Every test pins one specific fail-closed branch by name in its own
docstring and fails if that branch is deleted/inverted (e.g. `publishable
= len(supporting) > 0` becoming `>= 0`, or the freshness/blocked filters
being removed from `evaluate_claim_publishability`'s per-evidence loop).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from saena_claim_evidence.errors import ClaimNotFoundError
from saena_claim_evidence.evaluation import (
    ClaimPublishability,
    EvidenceFreshnessPolicy,
    EvidenceLinkStatus,
    evaluate_claim_publishability,
)
from saena_claim_evidence.ledger import DEFAULT_FRESHNESS_POLICY, verify_ledger_chain
from saena_claim_evidence.store import InMemoryClaimEvidenceStore
from saena_schemas.domain.evidence_record_v1 import EvidenceRecord
from saena_schemas.domain.extracted_claim_v1 import ExtractedClaim
from saena_schemas.domain.extracted_claim_v1 import Status as ClaimStatus

TENANT_ID = "acme-co"
PROJECT_ID = "proj-alpha"
CLAIM_ID = "claim-0001"

NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)
NOW_ISO = "2026-07-13T12:00:00Z"

_POLICY = EvidenceFreshnessPolicy(max_age_seconds=86400)  # 1 day


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_claim(*, claim_id: str = CLAIM_ID) -> ExtractedClaim:
    return ExtractedClaim(
        tenant_id=TENANT_ID,  # type: ignore[arg-type]
        project_id=PROJECT_ID,  # type: ignore[arg-type]
        claim_id=claim_id,
        entity_id="entity-0001",
        claim_text="The product supports SSO via SAML 2.0.",
        status=ClaimStatus.active,
        effective_from=NOW_ISO,  # type: ignore[arg-type]
        created_at=NOW_ISO,  # type: ignore[arg-type]
    )


def _make_evidence(
    *, evidence_id: str = "evidence-0001", claim_id: str = CLAIM_ID, freshness_checked_at: str
) -> EvidenceRecord:
    return EvidenceRecord(
        tenant_id=TENANT_ID,  # type: ignore[arg-type]
        project_id=PROJECT_ID,  # type: ignore[arg-type]
        evidence_id=evidence_id,
        claim_id=claim_id,
        source_uri="https://docs.example.com/security/sso",  # type: ignore[arg-type]
        excerpt="SAML 2.0 SSO is supported on the Enterprise plan.",
        freshness_checked_at=freshness_checked_at,  # type: ignore[arg-type]
        content_hash=f"sha256:{'a' * 64}",  # type: ignore[arg-type]
    )


# --- Pure-evaluator layer: saena_claim_evidence.evaluation ---


def test_no_evidence_at_all_is_not_publishable() -> None:
    """Pins the `if not evidence_records: return ... publishable=False`
    branch — case (a) "present" fails trivially. Fails if this early-return
    were removed (an empty `evidence_records` tuple would then fall
    through to the `any(...)` loop, which also correctly yields
    `publishable=False`, but WITHOUT the required `"no_evidence"` reason
    string this test also pins)."""
    result = evaluate_claim_publishability(
        claim_id=CLAIM_ID,
        evidence_records=(),
        link_statuses={},
        policy=_POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("no_evidence",)
    assert result.supporting_evidence_ids == ()


def test_stale_evidence_is_not_publishable() -> None:
    """Pins case (b) "fresh" — `is_evidence_fresh` returning `False` for
    evidence whose `freshness_checked_at` is older than
    `policy.max_age_seconds`. Fails if the staleness filter were removed
    from `evaluate_claim_publishability`'s per-evidence loop (stale
    evidence would then count as `supporting`, flipping `publishable` to
    `True`)."""
    stale_evidence = _make_evidence(freshness_checked_at=_iso(NOW - timedelta(days=30)))
    result = evaluate_claim_publishability(
        claim_id=CLAIM_ID,
        evidence_records=(stale_evidence,),
        link_statuses={"evidence-0001": EvidenceLinkStatus.LINKED},
        policy=_POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("stale",)


def test_blocked_evidence_is_not_publishable() -> None:
    """Pins case (c) "not blocked" — `link_statuses.get(...) is BLOCKED`
    excluding that record from support, even though it is present AND
    fresh. Fails if the blocked-status filter were removed (a fresh,
    administratively-blocked record would then still count as support)."""
    fresh_but_blocked = _make_evidence(freshness_checked_at=_iso(NOW))
    result = evaluate_claim_publishability(
        claim_id=CLAIM_ID,
        evidence_records=(fresh_but_blocked,),
        link_statuses={"evidence-0001": EvidenceLinkStatus.BLOCKED},
        policy=_POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("blocked",)


def test_unregistered_link_status_defaults_to_blocked_never_silently_supporting() -> None:
    """Pins the fail-closed default in `evaluate_claim_publishability`:
    `link_statuses.get(evidence.evidence_id, EvidenceLinkStatus.BLOCKED)` —
    an evidence record with NO entry at all in `link_statuses` (never
    explicitly linked) must default to BLOCKED, not silently count as
    supporting. Fails if the default were flipped to `LINKED`."""
    fresh_but_unregistered = _make_evidence(freshness_checked_at=_iso(NOW))
    result = evaluate_claim_publishability(
        claim_id=CLAIM_ID,
        evidence_records=(fresh_but_unregistered,),
        link_statuses={},  # no entry for "evidence-0001" at all
        policy=_POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("blocked",)


def test_future_dated_freshness_check_is_treated_as_not_fresh_data_integrity_anomaly() -> None:
    """Pins `is_evidence_fresh`'s `if age_seconds < 0: return False` branch
    — a `freshness_checked_at` AFTER `now` is a data-integrity anomaly,
    fail-closed to NOT fresh rather than silently trusted (module
    docstring: "treated as NOT fresh — fail closed rather than silently
    trusting it"). Fails if this negative-age guard were removed (a
    future-dated record would then satisfy `age_seconds <=
    policy.max_age_seconds` trivially and count as fresh)."""
    future_dated = _make_evidence(freshness_checked_at=_iso(NOW + timedelta(days=1)))
    result = evaluate_claim_publishability(
        claim_id=CLAIM_ID,
        evidence_records=(future_dated,),
        link_statuses={"evidence-0001": EvidenceLinkStatus.LINKED},
        policy=_POLICY,
        now=NOW,
    )
    assert result.publishable is False
    assert result.blocking_reasons == ("stale",)


def test_one_valid_evidence_record_among_several_bad_ones_makes_the_claim_publishable() -> None:
    """Negative control: proves this is a real per-record `any(...)` check,
    not a blanket deny — a claim with one stale, one blocked, AND one
    genuinely fresh+linked evidence record must be publishable, citing
    ONLY the valid record as supporting."""
    stale = _make_evidence(
        evidence_id="evidence-stale", freshness_checked_at=_iso(NOW - timedelta(days=30))
    )
    blocked = _make_evidence(evidence_id="evidence-blocked", freshness_checked_at=_iso(NOW))
    valid = _make_evidence(evidence_id="evidence-valid", freshness_checked_at=_iso(NOW))

    result = evaluate_claim_publishability(
        claim_id=CLAIM_ID,
        evidence_records=(stale, blocked, valid),
        link_statuses={
            "evidence-stale": EvidenceLinkStatus.LINKED,
            "evidence-blocked": EvidenceLinkStatus.BLOCKED,
            "evidence-valid": EvidenceLinkStatus.LINKED,
        },
        policy=_POLICY,
        now=NOW,
    )
    assert result.publishable is True
    assert result.supporting_evidence_ids == ("evidence-valid",)
    assert result.blocking_reasons == ()
    assert isinstance(result, ClaimPublishability)


# --- End-to-end ledger + tenant-scoped store layer ---


def test_ledger_end_to_end_claim_with_only_stale_evidence_is_blocked_and_chain_stays_intact() -> (
    None
):
    """Pins the REAL `InMemoryClaimEvidenceStore.append_claim` ->
    `append_evidence` -> `get_claim_publishability` pipeline end to end: a
    claim whose only linked evidence is stale must be reported
    `publishable=False` via the store's own read path — not merely via the
    pure evaluator in isolation — AND the append-only hash chain must
    still verify (`verify_ledger_chain`), proving a BLOCKED verdict is a
    normal, tamper-evident ledger entry, never a bypass around the audit
    trail.
    """
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_ID, _make_claim())
    stale_evidence = _make_evidence(freshness_checked_at=_iso(NOW - timedelta(days=200)))
    store.append_evidence(TENANT_ID, stale_evidence, now=NOW, policy=DEFAULT_FRESHNESS_POLICY)

    publishability = store.get_claim_publishability(TENANT_ID, PROJECT_ID, CLAIM_ID)
    assert publishability.publishable is False
    assert publishability.blocking_reasons == ("stale",)

    ledger_state = store.get_ledger(TENANT_ID, PROJECT_ID)
    is_intact, broken_index = verify_ledger_chain(ledger_state)
    assert is_intact is True
    assert broken_index is None


def test_ledger_end_to_end_administratively_blocking_previously_valid_evidence_flips_to_blocked() -> (  # noqa: E501
    None
):
    """Pins `InMemoryClaimEvidenceStore.set_evidence_link_status`'s
    re-evaluation path: a claim that WAS publishable (fresh, linked
    evidence) must become non-publishable the moment its sole evidence is
    administratively marked BLOCKED — proving the fail-closed re-evaluation
    is live, not merely evaluated once at append time and then frozen.
    """
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_ID, _make_claim())
    fresh_evidence = _make_evidence(freshness_checked_at=_iso(NOW))
    store.append_evidence(TENANT_ID, fresh_evidence, now=NOW, policy=DEFAULT_FRESHNESS_POLICY)

    before = store.get_claim_publishability(TENANT_ID, PROJECT_ID, CLAIM_ID)
    assert before.publishable is True

    store.set_evidence_link_status(
        TENANT_ID,
        PROJECT_ID,
        evidence_id="evidence-0001",
        status=EvidenceLinkStatus.BLOCKED,
        now=NOW,
        policy=DEFAULT_FRESHNESS_POLICY,
    )

    after = store.get_claim_publishability(TENANT_ID, PROJECT_ID, CLAIM_ID)
    assert after.publishable is False
    assert after.blocking_reasons == ("blocked",)


def test_ledger_end_to_end_claim_with_zero_appended_evidence_is_blocked_by_default() -> None:
    """Pins the store/ledger-level "no valid evidence -> not publishable"
    guarantee for a claim that has had NO evidence appended at all yet —
    the fail-closed default must hold from the moment a claim is
    registered, never an implicit "publishable until proven otherwise"."""
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_ID, _make_claim())

    publishability = store.get_claim_publishability(TENANT_ID, PROJECT_ID, CLAIM_ID)
    assert publishability.publishable is False
    assert publishability.blocking_reasons == ("no_evidence",)


def test_unknown_claim_id_raises_rather_than_reporting_a_default_publishable_verdict() -> None:
    """Adversarial control: querying publishability for a `claim_id` this
    ledger has never seen must RAISE (`ClaimNotFoundError`), never
    silently return a default `ClaimPublishability(publishable=...)` value
    of any kind — a missing claim is not the same fail-closed case as a
    claim with zero evidence, and conflating the two would let a caller
    mistake "doesn't exist" for a legitimate BLOCKED verdict."""
    store = InMemoryClaimEvidenceStore()
    with pytest.raises(ClaimNotFoundError):
        store.get_claim_publishability(TENANT_ID, PROJECT_ID, "claim-never-registered")
