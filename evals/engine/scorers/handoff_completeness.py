"""Axis 9 — handoff completeness: "VerificationResult + rollback manifest +
audit chain all present", scored over REAL `saena_hooks_runtime.hooks.
before_handoff` (B-department prompt package §11) + REAL
`saena_quality_eval.verification.build_verification_result` (every gate
result rendered here is validated against `domain/verification-result/v1`,
not just presence-checked) + REAL `saena_domain.audit.InMemoryAuditChain`
(the audit-chain leg — a tampered/broken chain fails this axis even when
every other handoff signal looks fine).
"""

from __future__ import annotations

from typing import Any

from saena_domain.audit import InMemoryAuditChain
from saena_domain.execution import JobError
from saena_hooks_runtime.hooks.before_handoff import (
    BeforeHandoffInput,
    CriticReview,
    QualityMatrixResult,
    RollbackManifest,
    before_handoff,
)
from saena_hooks_runtime.models import Decision, TimeoutBudget
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import GateResult
from saena_quality_eval.verification import build_verification_result

from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult


def _build_verification_results(fixture_input: dict[str, Any]) -> list[str]:
    """Render + validate one `VerificationResult` per reported gate. Returns
    validation error strings (empty iff every gate produced a
    contract-conformant payload)."""
    errors: list[str] = []
    for gate_name, status in fixture_input["quality_matrix"]["gates"].items():
        try:
            gate_id = GateId(gate_name)
        except ValueError:
            # Non-required gate names outside this engine's closed GateId
            # vocabulary (e.g. "links"/"a11y"/"fidelity" from the B-department
            # prompt-package §11 gate list) are before_handoff's own concern,
            # not saena_quality_eval's — skip contract rendering for those.
            continue
        gate_result = (
            GateResult(gate_id=gate_id, passed=True, failures=())
            if status == "PASS"
            else GateResult(
                gate_id=gate_id,
                passed=False,
                failures=(
                    JobError(
                        error_code="saena.internal.gate_failed",
                        summary=f"{gate_name} gate reported status {status}",
                        retryable=False,
                    ),
                ),
            )
        )
        try:
            build_verification_result(
                tenant_id=fixture_input["tenant_id"],
                run_id=fixture_input["run_id"],
                patch_unit_id=fixture_input["patch_unit_id"],
                worktree_commit=fixture_input["worktree_commit"],
                evaluated_at=fixture_input["evaluated_at"],
                gate_result=gate_result,
            )
        except Exception as exc:  # noqa: BLE001 - converted to a reason string, never swallowed
            errors.append(f"gate {gate_name}: VerificationResult validation failed ({exc})")
    return errors


def _verify_audit_chain(entries: list[dict[str, Any]]) -> str | None:
    chain = InMemoryAuditChain()
    for entry in entries:
        chain.append(
            action=entry["action"],
            recorded_at=entry["recorded_at"],
            scope=entry["scope"],
            trace_id=entry["trace_id"],
            payload=entry.get("payload", {}),
            tenant_id=entry.get("tenant_id"),
            run_id=entry.get("run_id"),
        )
    ok, bad_index = chain.verify()
    if not ok:
        return f"audit chain verification failed at entry index {bad_index}"
    if len(chain.entries) == 0:
        return "no audit chain entries recorded for this handoff"
    return None


def score(fixture: Fixture) -> ScoreResult:
    fixture_input = fixture.input

    vr_errors = _build_verification_results(fixture_input)
    audit_error = _verify_audit_chain(fixture_input.get("audit_entries", []))

    critic_raw = fixture_input.get("critic_review")
    rollback_raw = fixture_input.get("rollback_manifest")

    hook_input = BeforeHandoffInput(
        ts="2026-07-13T00:00:00Z",
        run_id=fixture_input["run_id"],
        tenant_id=fixture_input["tenant_id"],
        trace_id=fixture_input.get("trace_id", "a" * 32),
        quality_matrix=QualityMatrixResult(gates=fixture_input["quality_matrix"]["gates"]),
        critic_review=(CriticReview(**critic_raw) if critic_raw is not None else None),
        rollback_manifest=(RollbackManifest(**rollback_raw) if rollback_raw is not None else None),
        patch_commands=tuple(fixture_input.get("patch_commands", ())),
        budget=TimeoutBudget(elapsed_seconds=0.0, deadline_seconds=60.0),
    )
    hook_decision = before_handoff(hook_input)

    reasons: list[str] = list(vr_errors)
    if audit_error is not None:
        reasons.append(audit_error)

    expected_decision = Decision(fixture_input["expected_decision"])
    if hook_decision.decision != expected_decision:
        reasons.append(
            f"before_handoff returned {hook_decision.decision.value!r}, expected "
            f"{expected_decision.value!r} (remediation: {list(hook_decision.remediation)})"
        )

    # A fixture "passes" this axis iff ALL THREE legs hold together: the
    # before_handoff decision matched what the fixture declared, every
    # reported gate rendered a contract-conformant VerificationResult, and
    # the audit chain verifies with at least one entry — any single
    # collected reason fails the whole fixture (fail-closed, no partial
    # credit for "2 of 3 legs present").
    passed = not reasons
    return ScoreResult(passed=passed, score=1.0 if passed else 0.0, reasons=tuple(reasons))


__all__ = ["score"]
