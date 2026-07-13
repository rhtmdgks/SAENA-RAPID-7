"""Factory helpers for `tests/integration/approval_flow` and
`tests/e2e/approval`.

Reuses `tests/contract/fixtures/change-plan/valid/*.json` — the SAME fixture
corpus `tests/unit/svc_plan_contract/plan_contract_factories.py` and
`tests/contract/validate/test_change_plan.py` already validate against —
rather than hand-rolling a parallel ChangePlan literal, single source of
truth for "what a schema-valid ChangePlan looks like".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TENANT_A = "acme-corp"
TENANT_B = "globex-corp"

PROPOSER = "actor-proposer-0001"
APPROVER_1 = "actor-approver-0001"
APPROVER_2 = "actor-approver-0002"
DECIDED_AT = "2026-07-12T10:00:00Z"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "contract" / "fixtures" / "change-plan" / "valid"


def load_change_plan_fixture(name: str, *, tenant_id: str = TENANT_A) -> dict[str, Any]:
    payload = json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))
    payload["tenant_id"] = tenant_id
    return payload


def high_risk_change_plan(*, tenant_id: str = TENANT_A) -> dict[str, Any]:
    payload = load_change_plan_fixture("with-rejected-alternatives.json", tenant_id=tenant_id)
    payload["hypotheses"][0]["risk"] = "high"
    return payload


def decision_body(
    contract_hash: str,
    *,
    approver_actor_id: str = APPROVER_1,
    decision: str = "approved",
    run_id: str = "run-0001",
    patch_unit_id: str = "PU-01",
    decided_at: str = DECIDED_AT,
    tenant_id: str = TENANT_A,
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
    "PROPOSER",
    "TENANT_A",
    "TENANT_B",
    "decision_body",
    "high_risk_change_plan",
    "load_change_plan_fixture",
]
