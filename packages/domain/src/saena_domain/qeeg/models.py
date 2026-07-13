"""QEEG (Question–Entity–Evidence Graph) read-only projection state (w4-11).

QEEG (design spec §3.2 "Question–Entity–Evidence Graph"): "질문이 어떤
엔티티와 claim을 요구하고, 그 claim이 어떤 근거와 자산으로 입증되는지
표현한다" — which entity/claim a question requires, and which evidence
supports that claim. Physical projection owner = claim-evidence-service
(ADR-0007; `docs/architecture/data-ownership.md:29`), READ-ONLY CQRS
(`docs/architecture/data-ownership.md` "Cross-cutting read model 규칙":
"프로젝션은 쓰기 권한 없음 — 수정은 반드시 원 소유 서비스의 command API
경유").

This module is deliberately decoupled from `saena_claim_evidence`'s
concrete `ExtractedClaim`/`EvidenceRecord` pydantic types (a
service-owned, w4-04 write-model concern) — it operates on plain,
JSON-serializable "fact" dicts, mirroring
`saena_claim_evidence.ledger._claim_material`/`_evidence_material`'s own
"a deterministic dict is the unit of identity/content comparison"
discipline. The `saena_claim_evidence.qeeg_projection` module (w4-11's
OTHER exclusive path) is the adapter that folds real
`ClaimEvidenceLedgerEntry` objects into the fold functions here — keeping
this package importable/testable without a `saena_schemas` domain-model
dependency for its OWN internal replay algorithm, and reusable by any
other future claim/evidence-shaped event source.

Determinism / replay contract (task hard constraint): folding the exact
same ordered sequence of `ClaimFact`/`EvidenceFact` events into an empty
`QeegProjectionState`, twice, independently, yields two
`QeegProjectionState` values that compare `==` (frozen dataclasses of
frozen dataclasses/tuples/dicts-as-tuples — see `__eq__` derives from
field equality). Folding is also idempotent: re-folding an
already-observed `ClaimFact`/`EvidenceFact` (byte-identical content) is a
safe no-op, never double-counted (mirrors `saena_claim_evidence.ledger`'s
own append-only no-op-replay discipline at the write-model layer).

Tenant scoping: every `ClaimFact`/`EvidenceFact` carries its own
`tenant_id`; a `QeegProjectionState` is always built (via `replay`) for
exactly ONE `tenant_id`, and folding a fact whose `tenant_id` does not
match raises `CrossTenantProjectionAccessError` (fail-closed,
default-DENY — never silently absorbed into the wrong tenant's view).

No PII: this module never stores or derives from `claim_text`/`excerpt`
free-text content — only identifiers, status/publishability enums, and
counts. Callers (e.g. `saena_claim_evidence.qeeg_projection`) are
responsible for not passing free-text fields into `ClaimFact`/
`EvidenceFact` in the first place; this module has no field for them to
begin with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class QeegLinkStatus(StrEnum):
    """Projection-local mirror of `saena_claim_evidence.evaluation.
    EvidenceLinkStatus` — duplicated here (rather than imported) to keep
    this module free of a `saena_claim_evidence` dependency (the reverse
    direction — `saena_claim_evidence` depends on `saena_domain`, never
    the other way — is the only allowed one, `.importlinter`
    `dependency-policy`: "services -> saena_domain / saena_schemas /
    saena_shared"). The adapter module maps
    `saena_claim_evidence.evaluation.EvidenceLinkStatus` values to this
    enum 1:1 by `.value`.
    """

    LINKED = "linked"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ClaimFact:
    """One claim-ledger-entry's worth of REPLAYABLE, PII-free fact material
    — the projection's own event shape, folded in ledger/event order by
    `apply_claim_fact`. Deliberately excludes `claim_text` (no PII/customer
    content in the projection — task hard constraint).
    """

    tenant_id: str
    project_id: str
    claim_id: str
    entity_id: str
    status: str
    publishable: bool
    blocking_reasons: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceFact:
    """One evidence-ledger-entry's worth of REPLAYABLE, PII-free fact
    material — folded in ledger/event order by `apply_evidence_fact`.
    Deliberately excludes `excerpt`/`source_uri` free-text/URL content (no
    PII/customer content in the projection).
    """

    tenant_id: str
    project_id: str
    evidence_id: str
    claim_id: str
    link_status: QeegLinkStatus


@dataclass(frozen=True, slots=True)
class QeegClaimView:
    """The projection's current (latest-replayed) view of one claim."""

    claim_id: str
    entity_id: str
    status: str
    publishable: bool
    blocking_reasons: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QeegProjectionState:
    """Immutable, tenant-scoped QEEG read-model snapshot.

    Every `replay`/`apply_*_fact` call returns a NEW `QeegProjectionState`
    rather than mutating an existing one (mirrors
    `saena_claim_evidence.ledger.ClaimEvidenceLedgerState`'s "returns a new
    tuple" / `saena_domain.experiment.ledger.LedgerState`'s identical
    contract) — nothing here is ever mutated in place, which is what makes
    "rebuild from scratch by replaying the same events" and "the live,
    incrementally-folded state" provably equal (same fold function, same
    inputs, same order => identical output, structural `==`).

    Internal storage uses `tuple[tuple[str, X], ...]` (sorted-by-key
    tuples-of-pairs) rather than plain `dict` fields so the dataclass stays
    hashable/structurally-`==`-comparable and trivially reconstructable —
    `claims`/`entity_claims`/`claim_evidence` are exposed as read-only
    `Mapping`-like accessors via the query functions in `replay.py`, never
    mutated directly by callers.
    """

    tenant_id: str
    claims: tuple[tuple[str, QeegClaimView], ...] = field(default_factory=tuple)
    entity_claims: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)


__all__ = [
    "ClaimFact",
    "EvidenceFact",
    "QeegClaimView",
    "QeegLinkStatus",
    "QeegProjectionState",
]
