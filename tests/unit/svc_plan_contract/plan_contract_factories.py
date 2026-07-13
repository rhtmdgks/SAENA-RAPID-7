"""Factory helpers for `tests/unit/svc_plan_contract`.

Reuses `tests/contract/fixtures/change-plan/valid/*.json` (the same
contract-test fixture corpus `tests/contract/validate/test_change_plan.py`
validates against) rather than hand-rolling a parallel ChangePlan literal —
single source of truth for "what a schema-valid ChangePlan looks like".
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

TENANT_ID = "acme-corp"
PROPOSER_ACTOR_ID = "actor-proposer-0001"
APPROVER_1 = "actor-approver-0001"
APPROVER_2 = "actor-approver-0002"
DECIDED_AT = "2026-07-12T10:00:00Z"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "contract" / "fixtures" / "change-plan" / "valid"


def load_change_plan_fixture(name: str, *, tenant_id: str = TENANT_ID) -> dict[str, Any]:
    """Load `tests/contract/fixtures/change-plan/valid/{name}` and override
    `tenant_id` to `tenant_id` (fixtures use assorted tenant_id values not
    all matching this test suite's own `TENANT_ID` convention)."""
    payload = json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))
    payload["tenant_id"] = tenant_id
    return payload


def high_risk_change_plan(*, tenant_id: str = TENANT_ID) -> dict[str, Any]:
    payload = load_change_plan_fixture("with-rejected-alternatives.json", tenant_id=tenant_id)
    payload["hypotheses"][0]["risk"] = "high"
    return payload


def mutate_scope(change_plan: dict[str, Any], extra_glob: str) -> dict[str, Any]:
    """Return a deep copy of `change_plan` with an extra `approved_scope`
    entry — produces a DIFFERENT `contract_hash` (content-addressed)."""
    mutated = copy.deepcopy(change_plan)
    mutated["approved_scope"] = [*mutated["approved_scope"], extra_glob]
    return mutated


def decision_body(
    contract_hash: str,
    *,
    approver_actor_id: str = APPROVER_1,
    decision: str = "approved",
    run_id: str = "run-0001",
    patch_unit_id: str = "PU-01",
    decided_at: str = DECIDED_AT,
    tenant_id: str = TENANT_ID,
) -> dict[str, Any]:
    return {
        "contract_hash": contract_hash,
        "tenant_id": tenant_id,
        "run_id": run_id,
        "approver_actor_id": approver_actor_id,
        "decision": decision,
        "patch_unit_decisions": [{"patch_unit_id": patch_unit_id, "decision": decision}],
        "signature": "sig-abc",
        "signature_algorithm": "ed25519",
        "decided_at": decided_at,
    }


__all__ = [
    "APPROVER_1",
    "APPROVER_2",
    "DECIDED_AT",
    "PROPOSER_ACTOR_ID",
    "TENANT_ID",
    "decision_body",
    "high_risk_change_plan",
    "load_change_plan_fixture",
    "mutate_scope",
]
