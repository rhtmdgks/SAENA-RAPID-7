"""Evidence-registration enforcement (CLAUDE.md operating principle 11:
"증거 없는 완료 선언 금지" — no completion claim without registered evidence).

`verify_claim_evidence` is the harness-wide primitive: it REFUSES to score a
claim whose `evidence_id` is missing or not present in the fixture's own
declared evidence ledger (`evidence_registry`) by raising
`UnregisteredEvidenceError` rather than returning a partial/degraded score.
"Refuses to score" is enforced structurally here — every caller (the
`evidence_integrity` axis, and any other axis fixture that carries a
`material_claims` block, e.g. `handoff_completeness`) must catch this
exception and convert it into an unconditional fixture failure; it must
never swallow it into a lower-but-nonzero score.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class UnregisteredEvidenceError(ValueError):
    """A material claim referenced an `evidence_id` that is empty or absent
    from the fixture's registered evidence ledger — the harness refuses to
    score this claim at all (CLAUDE.md principle 11)."""


def verify_claim_evidence(claim: Mapping[str, Any], evidence_registry: Sequence[str]) -> str:
    """Return `claim["evidence_id"]` iff it is registered; raise
    `UnregisteredEvidenceError` otherwise.

    A claim with no `evidence_id` at all (or an empty string) is treated
    identically to one with an unregistered id — "unsupported claim" and
    "claim citing evidence nobody registered" are the same failure from
    this primitive's point of view (Algorithm §11.1 "Content fidelity":
    "every material claim → evidence ID, unsupported claim 0건").
    """
    claim_id = claim.get("claim_id", "<unknown>")
    evidence_id = claim.get("evidence_id")
    if not evidence_id:
        raise UnregisteredEvidenceError(
            f"claim {claim_id!r} carries no evidence_id — unsupported material claim"
        )
    if evidence_id not in evidence_registry:
        raise UnregisteredEvidenceError(
            f"claim {claim_id!r} cites evidence_id {evidence_id!r}, which is not present "
            "in this fixture's registered evidence set — refusing to score an unregistered "
            "claim (CLAUDE.md principle 11, no external lift without registered evidence)"
        )
    return evidence_id


__all__ = ["UnregisteredEvidenceError", "verify_claim_evidence"]
