"""Axis 1 — patch correctness: "patch applies, critical tests+build pass",
scored over REAL `saena_quality_eval` outputs (Algorithm §11.1 "patch
correctness: critical tests 및 build 100% 통과").

Critical gates (mission item 1): `GateId.BUILD` and `GateId.TESTS` — a patch
that fails either is never correct, regardless of every other gate's
outcome. Every OTHER `GateId` in the fixture's `gates` list is still run
through `saena_quality_eval.verification.build_verification_result` (so a
malformed/non-contract-conformant gate result is still caught — that
function raises `VerificationResultValidationError` on a payload that does
not validate against `domain/verification-result/v1`), but a non-critical
gate's failure does not, by itself, fail this axis (`false_negative_guard`
fixture `patch-correctness-non-critical-gate-failure-still-passes.yaml`
proves this discrimination: a naive "any gate fails -> fail" scorer would
wrongly fail that fixture).
"""

from __future__ import annotations

from typing import Any

from saena_domain.execution import JobError
from saena_quality_eval.errors import VerificationResultValidationError
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import GateResult
from saena_quality_eval.verification import build_verification_result

from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult

CRITICAL_GATE_IDS: frozenset[GateId] = frozenset({GateId.BUILD, GateId.TESTS})


def _build_gate_result(raw: dict[str, Any]) -> GateResult:
    gate_id = GateId(raw["gate_id"])
    passed = bool(raw["passed"])
    if passed:
        return GateResult(gate_id=gate_id, passed=True, failures=())
    failure_raw = raw["failure"]
    failure = JobError(
        error_code=failure_raw["error_code"],
        summary=failure_raw["summary"],
        retryable=bool(failure_raw.get("retryable", False)),
    )
    return GateResult(gate_id=gate_id, passed=False, failures=(failure,))


def score(fixture: Fixture) -> ScoreResult:
    tenant_id = fixture.input["tenant_id"]
    run_id = fixture.input["run_id"]
    patch_unit_id = fixture.input["patch_unit_id"]
    worktree_commit = fixture.input["worktree_commit"]
    evaluated_at = fixture.input["evaluated_at"]
    gates_raw: list[dict[str, Any]] = fixture.input["gates"]

    reasons: list[str] = []
    critical_gate_ids_seen: set[GateId] = set()
    all_critical_passed = True

    for raw in gates_raw:
        gate_result = _build_gate_result(raw)
        try:
            build_verification_result(
                tenant_id=tenant_id,
                run_id=run_id,
                patch_unit_id=patch_unit_id,
                worktree_commit=worktree_commit,
                evaluated_at=evaluated_at,
                gate_result=gate_result,
            )
        except VerificationResultValidationError as exc:
            reasons.append(
                f"gate {gate_result.gate_id}: produced a non-conformant VerificationResult ({exc})"
            )
            return ScoreResult(passed=False, score=0.0, reasons=tuple(reasons))

        if gate_result.gate_id in CRITICAL_GATE_IDS:
            critical_gate_ids_seen.add(gate_result.gate_id)
            if not gate_result.passed:
                all_critical_passed = False
                reasons.append(
                    f"critical gate {gate_result.gate_id} failed: {gate_result.failures[0].summary}"
                )
        elif not gate_result.passed:
            reasons.append(
                f"non-critical gate {gate_result.gate_id} failed (does not block "
                "patch_correctness): " + gate_result.failures[0].summary
            )

    missing_critical = CRITICAL_GATE_IDS - critical_gate_ids_seen
    if missing_critical:
        reasons.append(
            f"critical gate(s) {sorted(missing_critical)} were never reported — "
            "fail-closed (an unreported critical gate is not given the benefit of the doubt)"
        )
        return ScoreResult(passed=False, score=0.0, reasons=tuple(reasons))

    passed = all_critical_passed
    score_value = 1.0 if passed else 0.0
    return ScoreResult(passed=passed, score=score_value, reasons=tuple(reasons))


__all__ = ["CRITICAL_GATE_IDS", "score"]
