"""`ledger.append_claim`/`append_evidence` — append-only + hash chain."""

from __future__ import annotations

from datetime import timedelta

import pytest
from claim_evidence_factories import NOW, build_claim, build_evidence
from saena_claim_evidence import (
    DEFAULT_FRESHNESS_POLICY,
    ClaimNotFoundError,
    DuplicateClaimIdError,
    DuplicateEvidenceIdError,
    EvidenceClaimMismatchError,
    EvidenceFreshnessPolicy,
    EvidenceLinkStatus,
    UnknownEvidenceLinkError,
    append_claim,
    append_evidence,
    set_evidence_link_status,
    verify_ledger_chain,
)

POLICY = EvidenceFreshnessPolicy(max_age_seconds=3600)


def test_append_claim_returns_new_tuple_not_mutated_input() -> None:
    ledger = ()
    claim = build_claim()
    new_ledger, entry = append_claim(ledger, claim)

    assert ledger == ()
    assert len(new_ledger) == 1
    assert new_ledger[0] is entry


def test_genesis_entry_has_no_previous_hash() -> None:
    ledger, entry = append_claim((), build_claim())
    assert entry.previous_hash is None


def test_second_entry_chains_to_first() -> None:
    ledger, first = append_claim((), build_claim())
    evidence = build_evidence()
    ledger, second = append_evidence(ledger, evidence, link_statuses={}, now=NOW, policy=POLICY)
    assert second.previous_hash == first.canonical_hash


def test_append_claim_idempotent_replay_is_a_noop() -> None:
    ledger, first = append_claim((), build_claim())
    ledger2, second = append_claim(ledger, build_claim())

    assert ledger2 == ledger
    assert second is first


def test_append_claim_rejects_duplicate_id_with_different_content() -> None:
    ledger, _ = append_claim((), build_claim())
    with pytest.raises(DuplicateClaimIdError):
        append_claim(ledger, build_claim(claim_text="A materially different claim."))


def test_append_evidence_rejects_unknown_claim_id() -> None:
    with pytest.raises(EvidenceClaimMismatchError):
        append_evidence(
            (),
            build_evidence(claim_id="claim-does-not-exist"),
            link_statuses={},
            now=NOW,
            policy=POLICY,
        )


def test_append_evidence_idempotent_replay_is_a_noop() -> None:
    ledger, _ = append_claim((), build_claim())
    ledger, first = append_evidence(
        ledger, build_evidence(), link_statuses={}, now=NOW, policy=POLICY
    )
    ledger2, second = append_evidence(
        ledger, build_evidence(), link_statuses={}, now=NOW, policy=POLICY
    )

    assert ledger2 == ledger
    assert second is first


def test_append_evidence_rejects_duplicate_id_with_different_content() -> None:
    ledger, _ = append_claim((), build_claim())
    ledger, _ = append_evidence(ledger, build_evidence(), link_statuses={}, now=NOW, policy=POLICY)

    with pytest.raises(DuplicateEvidenceIdError):
        append_evidence(
            ledger,
            build_evidence(excerpt="A completely different excerpt string."),
            link_statuses={},
            now=NOW,
            policy=POLICY,
        )


def test_verify_ledger_chain_reports_intact_for_a_healthy_ledger() -> None:
    ledger, _ = append_claim((), build_claim())
    ledger, _ = append_evidence(ledger, build_evidence(), link_statuses={}, now=NOW, policy=POLICY)

    ok, index = verify_ledger_chain(ledger)
    assert ok is True
    assert index is None


def test_verify_ledger_chain_detects_a_forged_previous_hash() -> None:
    ledger, _ = append_claim((), build_claim())
    ledger, _ = append_evidence(ledger, build_evidence(), link_statuses={}, now=NOW, policy=POLICY)

    tampered_last = ledger[-1].__class__(
        kind=ledger[-1].kind,
        tenant_id=ledger[-1].tenant_id,
        project_id=ledger[-1].project_id,
        claim=ledger[-1].claim,
        evidence=ledger[-1].evidence,
        publishability=ledger[-1].publishability,
        canonical_hash=ledger[-1].canonical_hash,
        previous_hash="sha256:" + "0" * 64,
    )
    tampered_ledger = (*ledger[:-1], tampered_last)

    ok, index = verify_ledger_chain(tampered_ledger)
    assert ok is False
    assert index == len(tampered_ledger) - 1


def test_verify_ledger_chain_detects_a_mutated_entry_content() -> None:
    ledger, first = append_claim((), build_claim())

    tampered_first = first.__class__(
        kind=first.kind,
        tenant_id=first.tenant_id,
        project_id=first.project_id,
        claim=build_claim(claim_text="Tampered claim text that was never really hashed."),
        evidence=first.evidence,
        publishability=first.publishability,
        canonical_hash=first.canonical_hash,
        previous_hash=first.previous_hash,
    )
    tampered_ledger = (tampered_first,)

    ok, index = verify_ledger_chain(tampered_ledger)
    assert ok is False
    assert index == 0


def test_ledger_entry_rejects_invalid_kind() -> None:
    from saena_claim_evidence import ClaimEvidenceLedgerEntry

    with pytest.raises(ValueError, match="kind must be"):
        ClaimEvidenceLedgerEntry(
            kind="not-a-real-kind",
            tenant_id="acme-co",
            project_id="project-0001",
            claim=None,
            evidence=None,
            publishability=None,
            canonical_hash="sha256:" + "a" * 64,
            previous_hash=None,
        )


def test_ledger_entry_requires_claim_payload_for_claim_kind() -> None:
    from saena_claim_evidence import ClaimEvidenceLedgerEntry

    with pytest.raises(ValueError, match="must carry a non-None claim"):
        ClaimEvidenceLedgerEntry(
            kind="claim",
            tenant_id="acme-co",
            project_id="project-0001",
            claim=None,
            evidence=None,
            publishability=None,
            canonical_hash="sha256:" + "a" * 64,
            previous_hash=None,
        )


def test_ledger_entry_requires_evidence_payload_for_evidence_kind() -> None:
    from saena_claim_evidence import ClaimEvidenceLedgerEntry

    with pytest.raises(ValueError, match="must carry a non-None evidence"):
        ClaimEvidenceLedgerEntry(
            kind="evidence",
            tenant_id="acme-co",
            project_id="project-0001",
            claim=None,
            evidence=None,
            publishability=None,
            canonical_hash="sha256:" + "a" * 64,
            previous_hash=None,
        )


class TestPublishabilityReevaluationOnMutation:
    """The core mutation-triggered-reevaluation requirement: a claim already
    marked publishable must flip to NOT publishable the moment its
    supporting evidence becomes stale/blocked/unlinked, and this must be
    recorded as a new, appended ledger entry (never an in-place edit)."""

    def test_set_evidence_link_status_to_blocked_flips_claim_to_unpublishable(self) -> None:
        link_statuses: dict[str, EvidenceLinkStatus] = {}
        ledger, _ = append_claim((), build_claim())
        ledger, _ = append_evidence(
            ledger, build_evidence(), link_statuses=link_statuses, now=NOW, policy=POLICY
        )
        assert ledger[-1].publishability.publishable is True
        pre_length = len(ledger)

        ledger = set_evidence_link_status(
            ledger,
            evidence_id="evidence-0001",
            status=EvidenceLinkStatus.BLOCKED,
            link_statuses=link_statuses,
            now=NOW,
            policy=POLICY,
        )

        assert len(ledger) == pre_length + 1  # a new entry was appended, nothing edited in place
        assert ledger[-1].kind == "claim"
        assert ledger[-1].publishability.publishable is False
        assert ledger[-1].publishability.blocking_reasons == ("blocked",)
        # the prior claim entry (index 2: claim / evidence / re-evaluated-publishable
        # claim) is untouched — append-only, no in-place edit.
        assert ledger[2].kind == "claim"
        assert ledger[2].publishability.publishable is True

    def test_set_evidence_link_status_back_to_linked_restores_publishability(self) -> None:
        link_statuses: dict[str, EvidenceLinkStatus] = {}
        ledger, _ = append_claim((), build_claim())
        ledger, _ = append_evidence(
            ledger, build_evidence(), link_statuses=link_statuses, now=NOW, policy=POLICY
        )
        ledger = set_evidence_link_status(
            ledger,
            evidence_id="evidence-0001",
            status=EvidenceLinkStatus.BLOCKED,
            link_statuses=link_statuses,
            now=NOW,
            policy=POLICY,
        )
        assert ledger[-1].publishability.publishable is False

        ledger = set_evidence_link_status(
            ledger,
            evidence_id="evidence-0001",
            status=EvidenceLinkStatus.LINKED,
            link_statuses=link_statuses,
            now=NOW,
            policy=POLICY,
        )
        assert ledger[-1].publishability.publishable is True

    def test_no_new_entry_appended_when_publishability_is_unchanged(self) -> None:
        """Re-setting the SAME status must not append redundant ledger noise."""
        link_statuses: dict[str, EvidenceLinkStatus] = {"evidence-0001": EvidenceLinkStatus.LINKED}
        ledger, _ = append_claim((), build_claim())
        ledger, _ = append_evidence(
            ledger, build_evidence(), link_statuses=link_statuses, now=NOW, policy=POLICY
        )
        pre_length = len(ledger)

        ledger = set_evidence_link_status(
            ledger,
            evidence_id="evidence-0001",
            status=EvidenceLinkStatus.LINKED,
            link_statuses=link_statuses,
            now=NOW,
            policy=POLICY,
        )
        assert len(ledger) == pre_length

    def test_claim_becomes_unpublishable_when_its_only_evidence_goes_stale(self) -> None:
        link_statuses: dict[str, EvidenceLinkStatus] = {}
        ledger, _ = append_claim((), build_claim())
        ledger, _ = append_evidence(
            ledger, build_evidence(), link_statuses=link_statuses, now=NOW, policy=POLICY
        )
        assert ledger[-1].publishability.publishable is True

        later = NOW + timedelta(hours=2)
        ledger = set_evidence_link_status(
            ledger,
            evidence_id="evidence-0001",
            status=EvidenceLinkStatus.LINKED,  # status itself unchanged; time moved forward
            link_statuses=link_statuses,
            now=later,
            policy=POLICY,
        )
        assert ledger[-1].publishability.publishable is False
        assert ledger[-1].publishability.blocking_reasons == ("stale",)

    def test_set_evidence_link_status_unknown_evidence_id_raises(self) -> None:
        ledger, _ = append_claim((), build_claim())
        with pytest.raises(UnknownEvidenceLinkError):
            set_evidence_link_status(
                ledger,
                evidence_id="evidence-never-appended",
                status=EvidenceLinkStatus.BLOCKED,
                link_statuses={},
                now=NOW,
                policy=POLICY,
            )

    def test_reevaluate_raises_claim_not_found_for_unknown_claim(self) -> None:
        from saena_claim_evidence.ledger import _reevaluate

        with pytest.raises(ClaimNotFoundError):
            _reevaluate(
                (),
                claim_id="claim-does-not-exist",
                link_statuses={},
                policy=POLICY,
                now=NOW,
            )


def test_default_freshness_policy_is_positive() -> None:
    assert DEFAULT_FRESHNESS_POLICY.max_age_seconds > 0
