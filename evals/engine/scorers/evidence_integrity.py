"""Axis 7 — evidence/citation integrity: "every material claim carries a
valid evidence_id; unsupported ⇒ fail" (Algorithm §11.1 "Content fidelity"),
scored over `evals.engine.evidence_registry` (CLAUDE.md principle 11).

Fixture `input` supplies `evidence_registry` (the fixture's own registered
evidence ledger — the ONLY evidence ids this axis will accept) and `claims`
(each `{claim_id, evidence_id, text}`). The FIRST claim whose evidence_id
is missing or unregistered makes the harness REFUSE to score the whole
fixture (`UnregisteredEvidenceError` -> unconditional fail, never a partial
credit for the claims that DID carry valid evidence) — "no unregistered
evidence" is fail-closed at the fixture level, not averaged away.
"""

from __future__ import annotations

from evals.engine.evidence_registry import UnregisteredEvidenceError, verify_claim_evidence
from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult


def score(fixture: Fixture) -> ScoreResult:
    registry = tuple(fixture.input["evidence_registry"])
    claims = fixture.input["claims"]

    if not claims:
        return ScoreResult(
            passed=False, score=0.0, reasons=("no material claims supplied to verify",)
        )

    for claim in claims:
        try:
            verify_claim_evidence(claim, registry)
        except UnregisteredEvidenceError as exc:
            return ScoreResult(
                passed=False,
                score=0.0,
                reasons=(f"harness refuses to score this fixture: {exc}",),
            )

    return ScoreResult(passed=True, score=1.0, reasons=())


__all__ = ["score"]
