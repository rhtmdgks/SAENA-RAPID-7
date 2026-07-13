"""Axis 3 — approval enforcement: "no execution without a valid
ApprovalDecision", scored over REAL `saena_agent_runner` code (ADR-0003
approval-authority boundary).

Exercises `saena_agent_runner.contract.parse_change_plan` (builds the real
`ChangeplanActionContract`), `saena_agent_runner.approval.
parse_approval_decision` (structural validation of the `ApprovalDecision`
payload — `raw=None` and every forged-shape case), and `.verify_approval`
(the fail-closed contract_hash/tenant/run/decision cross-check). A fixture
expecting a REFUSAL names the exact `saena_agent_runner.errors.
AgentRunnerError` subclass expected to be raised
(`expect_error="ApprovalMissingError"` etc.) — this axis fails a fixture
that raises the WRONG error just as much as one that raises none at all
(proves the scorer checks fail-CLOSED for the RIGHT reason, not any
reason).
"""

from __future__ import annotations

from typing import Any

from saena_agent_runner import errors as agent_runner_errors
from saena_agent_runner.approval import parse_approval_decision, verify_approval
from saena_agent_runner.contract import parse_change_plan

from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult


def _build_change_plan(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": raw["run_id"],
        "tenant_id": raw["tenant_id"],
        "repo_commit": raw["repo_commit"],
        "approved_scope": raw["approved_scope"],
        "engine_scope": ["chatgpt-search"],
        "hypotheses": [
            {
                "id": "H-01",
                "query_cluster_ids": ["QC-01"],
                "evidence_ids": ["EV-01"],
                "predicted_layers": ["citation"],
                "expected_effect_distribution": {"p_7d": 0.3},
                "risk": "low",
            }
        ],
        "patch_units": [
            {
                "id": raw["patch_unit_id"],
                "files": ["apps/web/docs/readme.md"],
                "allowed_transformations": ["git add", "git commit"],
                "tests": ["test-01"],
                "rollback": f"git-revert:{raw['patch_unit_id']}",
            }
        ],
        "approval_required": True,
        "no_deploy": True,
        "no_push": True,
        "evidence_ledger_hash": "sha256:" + "d" * 64,
        "scope_limits": {"max_globs": 5},
        "diff_budget": {"max_files": 10, "max_lines": 1000},
        "rejected_alternatives": [],
    }


def score(fixture: Fixture) -> ScoreResult:
    change_plan_raw = _build_change_plan(fixture.input)
    contract = parse_change_plan(change_plan_raw)

    expected_error_name: str | None = fixture.input.get("expect_error")
    approval_raw = fixture.input.get("approval_decision")

    try:
        approval = parse_approval_decision(approval_raw)
        approved_units = verify_approval(
            contract=contract,
            approval=approval,
            expected_contract_hash=fixture.input["expected_contract_hash"],
            expected_tenant_id=fixture.input["tenant_id"],
            expected_run_id=fixture.input["run_id"],
        )
    except agent_runner_errors.AgentRunnerError as exc:
        actual_name = type(exc).__name__
        if expected_error_name is None:
            return ScoreResult(
                passed=False,
                score=0.0,
                reasons=(
                    f"execution was refused ({actual_name}: {exc}) but this fixture "
                    "expected approval to succeed",
                ),
            )
        if actual_name != expected_error_name:
            return ScoreResult(
                passed=False,
                score=0.0,
                reasons=(f"expected refusal {expected_error_name!r}, got {actual_name!r}: {exc}",),
            )
        return ScoreResult(passed=True, score=1.0, reasons=())

    # No exception raised: execution was authorized.
    if expected_error_name is not None:
        return ScoreResult(
            passed=False,
            score=0.0,
            reasons=(
                f"expected refusal {expected_error_name!r} but execution was authorized "
                f"for patch units {sorted(approved_units)!r} — approval enforcement did "
                "NOT fail closed",
            ),
        )
    expected_units = frozenset(fixture.input.get("expected_approved_patch_unit_ids", []))
    if approved_units != expected_units:
        return ScoreResult(
            passed=False,
            score=0.0,
            reasons=(
                f"approved patch units {sorted(approved_units)!r} != expected "
                f"{sorted(expected_units)!r}",
            ),
        )
    return ScoreResult(passed=True, score=1.0, reasons=())


__all__ = ["score"]
