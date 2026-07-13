"""``saena_strategy_skill_bank`` — B-verified-only skill-bank intake boundary
(W5, w5-16).

Scope (exclusive paths, this patch unit ONLY):
    services/experimentation/strategy-skill-bank-service/** (this package),
    tests/unit/svc_strategy_skill_bank/**

## Fail-closed intake boundary ONLY — this is the whole scope

This package implements the wave5-plan.md deliverable-3 / exit-E7 intake
boundary: it decides whether a candidate strategy card is ADMITTED into a
``CANDIDATE`` pool, or REJECTED with a named reason. Nothing else.

Explicitly OUT of scope for this unit (wave5-plan.md Non-scope: "Strategy-card
auto-approval/global sharing; production skill-bank learning loop (W5 =
fail-closed intake boundary ONLY)"):
- No approve/promote/publish/share/learn operation exists anywhere in this
  package — ``IntakeGuard``'s only public method is ``evaluate`` (plus the
  wire-payload convenience wrapper ``evaluate_payload``). There is no state
  store, no cross-tenant transfer, no global skill-bank write path.
- No production learning loop, no card ranking/scoring beyond admit/reject,
  no cross-tenant aggregation logic.

Core design, one paragraph: ``IntakeGuard.evaluate`` admits a candidate
(``IntakeCandidate``) into ``CandidatePool.PRODUCTION`` or
``CandidatePool.TEST`` ONLY when (a) the asserted B-gate verdict
(``saena_domain.measurement.b_gate.BVerdict``) is exactly ``PASS``, (b) the
candidate's ``evidence_bundle_manifest_hash`` is verified — via
``saena_domain.measurement.evidence.verify_manifest`` — against a supplied
``EvidenceBundleManifest`` whose own recomputed hash matches the claim (a
bare hash with no verifiable manifest is REJECT(unverifiable_evidence)), (c)
the outcome's provenance is production-valid or explicitly a test fixture
(and a test fixture can ONLY land in the test pool, never production), and
(d) the payload carries no tenant-identifying or raw-content field (an
aggregate-only denylist scan mirroring
``saena_domain.measurement.evidence.guard_evidence_fields``'s discipline).
Every other input shape is REJECT — fail-closed, with a named
``IntakeRejectReason``, never a silent widening.

Public API:
    IntakeDecisionStatus / CandidatePool / SourceOutcomeProvenance
    SourceOutcomeAssertion / IntakeCandidate / IntakeRejectReason
    IntakeDecision / IntakeGuard
"""

from __future__ import annotations

from saena_strategy_skill_bank.intake import (
    CandidatePool,
    IntakeCandidate,
    IntakeDecision,
    IntakeDecisionStatus,
    IntakeGuard,
    IntakeRejectReason,
    SourceOutcomeAssertion,
    SourceOutcomeProvenance,
)

__all__ = [
    "CandidatePool",
    "IntakeCandidate",
    "IntakeDecision",
    "IntakeDecisionStatus",
    "IntakeGuard",
    "IntakeRejectReason",
    "SourceOutcomeAssertion",
    "SourceOutcomeProvenance",
]
