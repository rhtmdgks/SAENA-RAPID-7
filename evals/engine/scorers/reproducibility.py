"""Axis 6 — reproducibility: "same seed/inputs ⇒ identical result — assert
byte-equality" (Algorithm §11.3 reproducibility completion criterion),
scored over REAL `saena_quality_eval.verification.build_verification_result`
(pure, no wall-clock — `evaluated_at` is caller-supplied) plus REAL
`saena_domain.audit.canonical.canonical_json`/`sha256_hex` for the
byte-equality assertion itself.

Fixture `input` supplies TWO gate-evaluation call argument sets
(`run_a`/`run_b`) that a correct, deterministic engine must render as the
IDENTICAL canonical-JSON string; a `false_positive_guard` fixture
deliberately varies one field between the two calls (simulating a
wall-clock/non-determinism leak) and asserts this axis DETECTS the
divergence rather than reporting spurious reproducibility.
"""

from __future__ import annotations

from typing import Any

from saena_domain.audit.canonical import canonical_json, sha256_hex
from saena_domain.execution import JobError
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import GateResult
from saena_quality_eval.verification import build_verification_result

from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult


def _build_gate_result(raw: dict[str, Any]) -> GateResult:
    gate_id = GateId(raw["gate_id"])
    if raw["passed"]:
        return GateResult(gate_id=gate_id, passed=True, failures=())
    failure_raw = raw["failure"]
    failure = JobError(
        error_code=failure_raw["error_code"],
        summary=failure_raw["summary"],
        retryable=bool(failure_raw.get("retryable", False)),
        redacted_detail=dict(failure_raw.get("redacted_detail", {})),
    )
    return GateResult(gate_id=gate_id, passed=False, failures=(failure,))


def _render(run: dict[str, Any]) -> str:
    gate_result = _build_gate_result(run["gate"])
    payload = build_verification_result(
        tenant_id=run["tenant_id"],
        run_id=run["run_id"],
        patch_unit_id=run["patch_unit_id"],
        worktree_commit=run["worktree_commit"],
        evaluated_at=run["evaluated_at"],
        gate_result=gate_result,
    )
    return canonical_json(payload)


def score(fixture: Fixture) -> ScoreResult:
    run_a = fixture.input["run_a"]
    run_b = fixture.input["run_b"]

    canonical_a = _render(run_a)
    canonical_b = _render(run_b)
    # Repeat run_a a second time: proves the SAME inputs, called twice in the
    # SAME process, byte-identically reproduce (not just "run_a happens to
    # equal run_b by fixture construction").
    canonical_a_replay = _render(run_a)

    hash_a = sha256_hex(canonical_a)
    hash_a_replay = sha256_hex(canonical_a_replay)
    hash_b = sha256_hex(canonical_b)

    if hash_a != hash_a_replay or canonical_a != canonical_a_replay:
        return ScoreResult(
            passed=False,
            score=0.0,
            reasons=(
                "run_a replayed with identical inputs produced a DIFFERENT canonical "
                "byte representation — the harness itself is non-deterministic",
            ),
        )

    byte_identical = canonical_a == canonical_b and hash_a == hash_b
    expect_identical = fixture.input["expect_identical"]

    if byte_identical != expect_identical:
        return ScoreResult(
            passed=False,
            score=0.0,
            reasons=(
                f"run_a/run_b byte-equality was {byte_identical}, fixture expected "
                f"{expect_identical}",
            ),
        )
    return ScoreResult(passed=True, score=1.0, reasons=())


__all__ = ["score"]
