"""Factory helpers for `tests/integration/gate_contract` — see package
docstring for what this suite proves.
"""

from __future__ import annotations

from saena_plan_contract.gate_client import GateCheckRequest

TENANT_ID = "acme-corp"

#: A schema-valid `evidence_ledger_hash` (`Sha256Ref` pattern
#: `^sha256:[0-9a-f]{64}$`) — matches the value
#: `tests/contract/fixtures/change-plan/valid/single-patch-unit.json` already
#: uses, so these gate-contract tests build requests shaped like a real
#: proposed ChangePlan's own H-3 facts, not arbitrary literals.
EVIDENCE_LEDGER_HASH = "sha256:" + "a" * 64

SCOPE_MAX_GLOBS = 5
DIFF_MAX_FILES = 10
DIFF_MAX_LINES = 500

PROPOSER_ACTOR_ID = "actor-proposer-0001"
APPROVER_ACTOR_ID = "actor-approver-0001"


def make_request(
    *,
    contract_hash: str = "sha256:" + "b" * 64,
    tenant_id: str = TENANT_ID,
    high_risk: bool = False,
    approved_scope: tuple[str, ...] = ("apps/web/docs/*",),
    proposer_actor_id: str | None = PROPOSER_ACTOR_ID,
    approver_actor_id: str | None = APPROVER_ACTOR_ID,
    evidence_ledger_hash: str | None = EVIDENCE_LEDGER_HASH,
    scope_max_globs: int | None = SCOPE_MAX_GLOBS,
    diff_max_files: int | None = DIFF_MAX_FILES,
    diff_max_lines: int | None = DIFF_MAX_LINES,
    hypothesis_risks: tuple[str, ...] = ("low",),
) -> GateCheckRequest:
    """A schema-valid, `PlanCheckRequestBody`-satisfying `GateCheckRequest`
    by default — individual tests override only the field(s) needed to
    exercise a specific gate outcome (deny / high-risk / fail-closed /
    caller-gap missing-field guard)."""
    return GateCheckRequest(
        contract_hash=contract_hash,
        tenant_id=tenant_id,
        high_risk=high_risk,
        approved_scope=approved_scope,
        proposer_actor_id=proposer_actor_id,
        approver_actor_id=approver_actor_id,
        evidence_ledger_hash=evidence_ledger_hash,
        scope_max_globs=scope_max_globs,
        diff_max_files=diff_max_files,
        diff_max_lines=diff_max_lines,
        hypothesis_risks=hypothesis_risks,
    )


__all__ = [
    "APPROVER_ACTOR_ID",
    "DIFF_MAX_FILES",
    "DIFF_MAX_LINES",
    "EVIDENCE_LEDGER_HASH",
    "PROPOSER_ACTOR_ID",
    "SCOPE_MAX_GLOBS",
    "TENANT_ID",
    "make_request",
]
