"""saena_domain.qeeg — Question–Entity–Evidence Graph read-only projection
engine (w4-11).

Scope (exclusive paths, this patch unit ONLY):
    packages/domain/src/saena_domain/qeeg/** (this module),
    the QEEG read-projection adapter inside
    services/intelligence/claim-evidence-service/src/saena_claim_evidence/
    (qeeg_projection.py — ADDS a projection/read-model file; does NOT
    modify the existing write-model core: ledger.py/evaluation.py/store.py),
    tests/unit/domain_qeeg/** and QEEG tests under
    tests/unit/svc_claim_evidence/**.

QEEG (design spec §3.2): "질문이 어떤 엔티티와 claim을 요구하고, 그 claim이
어떤 근거와 자산으로 입증되는지 표현한다" — which entity/claim a question
requires, and which evidence supports that claim. Physical projection
owner = claim-evidence-service (ADR-0007;
`docs/architecture/data-ownership.md:29`). READ-ONLY CQRS
(`docs/architecture/data-ownership.md` "Cross-cutting read model 규칙"):
this package never writes back to any source ledger/store; it only builds
an in-memory queryable view by REPLAYING already-decided facts
(`ClaimFact`/`EvidenceFact`) derived from the claim-evidence ledger's own
append-only entries.

Core design, one paragraph: `models.py` defines the projection's own
PII-free fact/state shapes (`ClaimFact`, `EvidenceFact`,
`QeegProjectionState`, `QeegClaimView`) — deliberately independent of
`saena_claim_evidence`'s concrete `ExtractedClaim`/`EvidenceRecord`
pydantic types, so this package has no dependency on any specific
write-model's schema (the adapter that bridges the two lives in
`saena_claim_evidence.qeeg_projection`, this unit's OTHER exclusive path).
`replay.py` is the deterministic fold engine:
`apply_claim_fact`/`apply_evidence_fact` each take a `QeegProjectionState`
and one fact and return a NEW state (never mutate in place); `replay`
folds an entire ordered fact sequence over `empty_projection` from
scratch. Determinism + idempotent replay (task hard constraints): the
same fact sequence, folded any number of times or via any mix of
incremental `apply_*`/from-scratch `replay` calls, always yields
structurally-`==` `QeegProjectionState` values — proven directly by
`apply_claim_fact`/`apply_evidence_fact` never depending on wall-clock
time, randomness, or any state outside their two explicit arguments, and
by their own no-op-on-byte-identical-refold branches. Tenant scoping:
every fact carries `tenant_id`; folding a fact whose `tenant_id` does not
match the target `QeegProjectionState.tenant_id` raises
`CrossTenantProjectionAccessError` — fail-closed, default-DENY, no
implicit cross-tenant merge.

Also explicitly OUT of scope (CLAUDE.md Engine scope v1 / wave4-plan.md
"Forbidden in W4" / this unit's own task instruction): no
outcome/DiD/causal/lift computation, no absorption-analysis, no
strategy-card, no scoring/outcome analytics of any kind. This package
computes and stores exactly the same publishability facts the
claim-evidence write-model already decided (`ClaimFact.publishable`/
`blocking_reasons`, folded in as-is) — it never independently evaluates or
overrides them.

Public API:
    ClaimFact / EvidenceFact
    QeegClaimView / QeegProjectionState / QeegLinkStatus
    apply_claim_fact / apply_evidence_fact / replay / empty_projection
    claims_by_entity / evidence_by_claim / publishability_of
    QeegProjectionError and every specific error subclass
"""

from __future__ import annotations

from saena_domain.qeeg.errors import (
    CrossTenantProjectionAccessError,
    QeegProjectionError,
    UnknownClaimError,
    UnknownEntityError,
)
from saena_domain.qeeg.models import (
    ClaimFact,
    EvidenceFact,
    QeegClaimView,
    QeegLinkStatus,
    QeegProjectionState,
)
from saena_domain.qeeg.replay import (
    apply_claim_fact,
    apply_evidence_fact,
    claims_by_entity,
    empty_projection,
    evidence_by_claim,
    publishability_of,
    replay,
)

__all__ = [
    "ClaimFact",
    "CrossTenantProjectionAccessError",
    "EvidenceFact",
    "QeegClaimView",
    "QeegLinkStatus",
    "QeegProjectionError",
    "QeegProjectionState",
    "UnknownClaimError",
    "UnknownEntityError",
    "apply_claim_fact",
    "apply_evidence_fact",
    "claims_by_entity",
    "empty_projection",
    "evidence_by_claim",
    "publishability_of",
    "replay",
]
