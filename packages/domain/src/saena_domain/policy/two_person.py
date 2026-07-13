"""H-7 two-person approval evaluation.

security-model.md H-7: "승인 원자성 해체 (H-7): per-patch-unit secret lease +
Git write token 분리, 고위험 unit 2인 승인." High risk is derived from
ChangePlan.hypotheses[].risk == "high" (change-plan.schema.json Risk enum);
the contract has no plan-level risk field, so "high-risk plan" is defined here
as: any hypothesis carries risk == "high". This derivation is a policy
interpretation, not a schema-declared field — flagged as an OPEN ITEM in the
final report.

approval-decision.schema.json $comment is explicit that dual approval is
represented as *two separate ApprovalDecision instances sharing the same
contract_hash* (idempotency key = contract_hash + approver_actor_id per
contract-catalog.md), not a multi-approver array inside one instance. This
module's evaluate_h7_two_person_approval therefore operates over a sequence of
decision records already keyed by approver_actor_id.

actor_id equality (dedup + proposer-vs-approver) is evaluated via
canonical_actor_id (identity.py) — identifiers.schema.json leaves actor_id
format OPEN, so raw `==` would let case/whitespace variants of the same
identity count as distinct approvers and defeat both the quorum count and the
self-approval ban (critic MUST-FIX 2).
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.policy.identity import canonical_actor_id


@dataclass(frozen=True, slots=True)
class ApproverRecord:
    """Minimal projection of an ApprovalDecision needed for H-7 evaluation."""

    approver_actor_id: str
    decision: str  # "approved" | "rejected" (approval-decision.schema.json Decision enum)


def evaluate_h7_two_person_approval(
    *,
    proposer_actor_id: str,
    approvals: tuple[ApproverRecord, ...],
    high_risk: bool,
) -> bool:
    """Return True iff the approval set satisfies H-7 for this plan.

    Rules (H-7 + ADR-0003 authority path):
    - approver actor_id must never equal proposer_actor_id, for ALL plans
      (self-approval forbidden regardless of risk), compared via
      canonical_actor_id (NFKC + strip + casefold — actor_id format is OPEN
      per identifiers.schema.json, so raw string equality is unsafe).
    - a given approver_actor_id may only count once, even if it appears more
      than once in `approvals` under different casing/whitespace
      (duplicate/replayed/case-variant submissions collapse to the same
      canonical identity — "same approver twice" must not satisfy the
      2-distinct-approver rule).
    - low/medium risk plans: >=1 distinct, non-proposer, "approved" approver.
    - high risk plans (H-7): >=2 DISTINCT non-proposer "approved" approvers.
    """
    canonical_proposer = canonical_actor_id(proposer_actor_id)
    distinct_valid_approvers: set[str] = set()
    for record in approvals:
        if record.decision != "approved":
            continue
        canonical_approver = canonical_actor_id(record.approver_actor_id)
        if canonical_approver == canonical_proposer:
            continue
        distinct_valid_approvers.add(canonical_approver)

    required = 2 if high_risk else 1
    return len(distinct_valid_approvers) >= required
