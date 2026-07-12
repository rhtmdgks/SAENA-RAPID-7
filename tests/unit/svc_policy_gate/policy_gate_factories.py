"""Factory helpers for `tests/unit/svc_policy_gate`."""

from __future__ import annotations

from typing import Any


def make_authorize_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "command",
        "action": "execute",
        "resource": ["pytest"],
        "approver_actor_id": "alice",
    }
    base.update(overrides)
    return base


def make_plan_check_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "contract_hash": "sha256:" + "a" * 64,
        "proposer_actor_id": "proposer-1",
        "approver_actor_id": "approver-1",
        "evidence_ledger_hash": "sha256:" + "b" * 64,
        "approved_scope": ["services/foundation/policy-gate-service/**"],
        "scope_max_globs": 5,
        "diff_max_files": 10,
        "diff_max_lines": 500,
        "hypothesis_risks": ["low"],
        "diff_stats": None,
    }
    base.update(overrides)
    return base
