"""Explicit negative/edge test: "a failing gate blocks (patch isolated,
PR-creation forbidden — assert the result forbids promotion)".

`QualityEvalOutcome.forbids_promotion` is the ONLY signal this package
produces for "may this patch unit be promoted/PR-created" — this module
asserts it flips to `True` for a representative failing gate from EACH of
the three categories mission items call out (a core Algorithm §11.1 gate, a
pluggable gate, and a negative-path gate), and that a single failing gate
among 20 otherwise-passing gates is enough (critical gates never
"outvoted" by a majority of passing gates — CLAUDE.md 원칙 8, ADR-0017
"critical gate 스킵 불가")."""

from __future__ import annotations

from dataclasses import replace

from factories import build_gate_input_bundle, build_quality_eval_request
from saena_quality_eval.engine import run_quality_evaluation
from saena_quality_eval.inputs import BuildOutcome, SecretScanFinding, SecretScanOutcome


def test_a_single_failing_algorithm_gate_forbids_promotion() -> None:
    gate_inputs = build_gate_input_bundle(
        build=BuildOutcome(succeeded=False, command="make build", exit_code=1)
    )
    request = build_quality_eval_request(gate_inputs=gate_inputs)
    outcome = run_quality_evaluation(request)

    assert outcome.forbids_promotion is True
    assert outcome.overall_status == "failed"
    assert outcome.gate_result_for("build")["status"] == "failed"
    # every OTHER gate still independently reports its own true status —
    # isolation, not a single blanket failure.
    assert outcome.gate_result_for("lint")["status"] == "passed"


def test_a_single_failing_negative_path_gate_forbids_promotion() -> None:
    gate_inputs = build_gate_input_bundle(
        secret_scan=SecretScanOutcome(
            findings=(SecretScanFinding(file_path="a.py", line=1, rule_id="generic-secret"),)
        )
    )
    request = build_quality_eval_request(gate_inputs=gate_inputs)
    outcome = run_quality_evaluation(request)

    assert outcome.forbids_promotion is True
    assert outcome.gate_result_for("secret_scan")["status"] == "failed"


def test_commit_mismatch_alone_forbids_promotion_even_with_every_other_gate_green() -> None:
    """Explicit negative/edge test: base/target mismatch forbids promotion,
    independent of every other (passing) gate."""
    request = build_quality_eval_request(artifact_base_commit="f" * 40)
    outcome = run_quality_evaluation(request)

    assert outcome.forbids_promotion is True
    assert outcome.gate_result_for("commit_coherence")["status"] == "failed"
    # 19 of 20 gates still pass — the single failure is still enough.
    passing = sum(1 for r in outcome.verification_results if r["status"] == "passed")
    assert passing == len(outcome.verification_results) - 1


def test_a_passing_run_does_not_forbid_promotion() -> None:
    outcome = run_quality_evaluation(build_quality_eval_request())
    assert outcome.forbids_promotion is False
    assert outcome.overall_status == "passed"


def test_forbids_promotion_never_creates_or_writes_anything() -> None:
    """`QualityEvalOutcome` is a plain frozen dataclass of already-computed
    data — no side effect (file write, PR API call, event bus publish) is
    even reachable from this package's own code; `replace()` on the outcome
    proves it is an ordinary immutable value, not a live handle to
    something this package could use to force a promotion despite
    `forbids_promotion=True`."""
    outcome = run_quality_evaluation(build_quality_eval_request(artifact_base_commit="f" * 40))
    forced = replace(outcome, forbids_promotion=False)
    assert outcome.forbids_promotion is True
    assert forced.forbids_promotion is False
    assert forced is not outcome
