"""Fail-closed claim-publishability evaluation — the core requirement.

Task instruction, verbatim: "a claim is publishable ONLY if it has at
least one supporting evidence record that is (a) present, (b) fresh (not
stale per a freshness policy), and (c) not blocked. If evidence is
unsupported / stale / blocked -> the claim's status becomes BLOCKED and it
is NOT publishable. No valid evidence -> not publishable."

This module is pure/deterministic — no wall-clock read, no I/O. The "now"
instant a freshness check is evaluated against is ALWAYS caller-supplied
(`evaluate_claim_publishability(..., now=...)`), matching this package's
"deterministic + offline; inject clock/ids; freshness compares against an
injected now" hard constraint.

`EvidenceFreshnessPolicy.max_age_seconds` (the actual staleness threshold)
is an OPEN decision — no spec or ADR fixes a numeric freshness bound for
claim/evidence (see this package's `README.md` "OPEN decisions" section).
This module does not invent that number as a hardcoded constant; it is
always an explicit, injectable policy value a caller supplies (production
default recorded as a caller/deployment concern outside this unit's
scope, not asserted here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from saena_schemas.domain.evidence_record_v1 import EvidenceRecord


class EvidenceLinkStatus(StrEnum):
    """This package's own domain-level annotation of one evidence record's
    standing WITHIN a specific ledger — layered on top of the generated
    `EvidenceRecord` schema, which has no such field itself (the generated
    model is a pure content DTO; link/lifecycle status is this ledger's own
    concern, exactly like `ContentRecordProjection.robots_allowed` in
    `saena_site_discovery` is a domain fact layered on top of a fetched
    record, not part of any upstream contract).
    """

    LINKED = "linked"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class EvidenceFreshnessPolicy:
    """Injectable staleness threshold. `max_age_seconds` is the maximum
    permitted age (relative to the caller-supplied `now`) of an
    `EvidenceRecord.freshness_checked_at` timestamp for that record to
    still count as fresh. See module docstring — the numeric value itself
    is an OPEN decision this package never hardcodes as a bare literal
    default; every caller must construct/inject one explicitly.
    """

    max_age_seconds: int

    def __post_init__(self) -> None:
        if self.max_age_seconds <= 0:
            msg = f"max_age_seconds must be a positive integer, got {self.max_age_seconds!r}"
            raise ValueError(msg)


def _parse_timestamp_utc(value: str) -> datetime:
    """Parse a `TimestampUtc`-contract-shaped string
    (`^[0-9]{4}-...Z$`) into an aware `datetime`."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_evidence_fresh(
    evidence: EvidenceRecord, *, policy: EvidenceFreshnessPolicy, now: datetime
) -> bool:
    """`True` iff `evidence.freshness_checked_at` is within
    `policy.max_age_seconds` of `now` AND not in the future (a
    `freshness_checked_at` after `now` is a data-integrity anomaly, treated
    as NOT fresh — fail closed rather than silently trusting it)."""
    checked_at = _parse_timestamp_utc(evidence.freshness_checked_at.root)
    age_seconds = (now - checked_at).total_seconds()
    if age_seconds < 0:
        return False
    return age_seconds <= policy.max_age_seconds


@dataclass(frozen=True, slots=True)
class ClaimPublishability:
    """The result of evaluating one claim's publishability against its
    linked evidence set. `blocking_reasons` is always empty when
    `publishable` is `True`, and always non-empty when `publishable` is
    `False` — every negative result carries at least one caller-readable
    (never customer-content-bearing) reason string.
    """

    claim_id: str
    publishable: bool
    blocking_reasons: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]


def evaluate_claim_publishability(
    *,
    claim_id: str,
    evidence_records: tuple[EvidenceRecord, ...],
    link_statuses: dict[str, EvidenceLinkStatus],
    policy: EvidenceFreshnessPolicy,
    now: datetime,
) -> ClaimPublishability:
    """Evaluate `claim_id`'s publishability against `evidence_records` (every
    `EvidenceRecord` in this ledger whose `.claim_id == claim_id` — callers
    filter before calling, this function does not itself query a store).

    Fail-closed decision table, evaluated per evidence record:
      - `link_statuses.get(evidence.evidence_id)` missing (never
        registered) or `BLOCKED` -> that record does not count as support.
      - stale (`is_evidence_fresh` is `False`) -> does not count as support.
      - otherwise (`LINKED` and fresh) -> counts as support.

    `publishable = True` iff at least one evidence record counts as
    support — "no valid evidence -> not publishable" is enforced as a
    strict `any(...)`, never an implicit pass-through. Absent evidence
    (`evidence_records == ()`) always yields `publishable=False` with the
    single reason `"no_evidence"` (case (a), "present" fails trivially).
    """
    if not evidence_records:
        return ClaimPublishability(
            claim_id=claim_id,
            publishable=False,
            blocking_reasons=("no_evidence",),
            supporting_evidence_ids=(),
        )

    supporting: list[str] = []
    reasons: set[str] = set()
    for evidence in evidence_records:
        status = link_statuses.get(evidence.evidence_id, EvidenceLinkStatus.BLOCKED)
        if status is EvidenceLinkStatus.BLOCKED:
            reasons.add("blocked")
            continue
        if not is_evidence_fresh(evidence, policy=policy, now=now):
            reasons.add("stale")
            continue
        supporting.append(evidence.evidence_id)

    publishable = len(supporting) > 0
    return ClaimPublishability(
        claim_id=claim_id,
        publishable=publishable,
        blocking_reasons=() if publishable else tuple(sorted(reasons)) or ("no_evidence",),
        supporting_evidence_ids=tuple(supporting),
    )


__all__ = [
    "ClaimPublishability",
    "EvidenceFreshnessPolicy",
    "EvidenceLinkStatus",
    "evaluate_claim_publishability",
    "is_evidence_fresh",
]
