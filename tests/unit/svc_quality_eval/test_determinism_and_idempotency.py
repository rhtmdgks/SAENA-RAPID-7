"""Mission item 8 ("deterministic VerificationResult: same inputs ⇒
byte-identical result — test determinism explicitly — run the aggregate
twice, assert equal") and item 11 ("re-run idempotency: same patch ⇒ same
result, no side effects")."""

from __future__ import annotations

from factories import build_gate_input_bundle, build_quality_eval_request
from saena_quality_eval.canonical import canonical_json
from saena_quality_eval.engine import run_quality_evaluation


def test_running_the_aggregate_twice_on_the_same_request_object_is_byte_identical() -> None:
    request = build_quality_eval_request()
    first = run_quality_evaluation(request)
    second = run_quality_evaluation(request)

    assert canonical_json(first.verification_results) == canonical_json(second.verification_results)
    assert canonical_json(first.events) == canonical_json(second.events)
    assert first.forbids_promotion == second.forbids_promotion
    assert first.overall_status == second.overall_status


def test_two_separately_constructed_equal_requests_produce_byte_identical_results() -> None:
    """Determinism does not rely on object identity/caching: TWO
    independently built `QualityEvalRequest`s (fresh `GateInputBundle`
    instances each) from the same logical inputs produce byte-identical
    output."""
    first_request = build_quality_eval_request(gate_inputs=build_gate_input_bundle())
    second_request = build_quality_eval_request(gate_inputs=build_gate_input_bundle())
    assert first_request == second_request  # pure value objects, not identity

    first = run_quality_evaluation(first_request)
    second = run_quality_evaluation(second_request)
    assert canonical_json(first.verification_results) == canonical_json(second.verification_results)


def test_a_failing_run_is_also_byte_identical_across_re_runs() -> None:
    """Determinism holds on the FAILING path too, not just the happy path —
    re-running a failing patch's evaluation must not flip flakily between
    pass/fail or reorder failures."""
    gate_inputs = build_gate_input_bundle()
    request = build_quality_eval_request(gate_inputs=gate_inputs, artifact_base_commit="f" * 40)

    first = run_quality_evaluation(request)
    second = run_quality_evaluation(request)

    assert first.forbids_promotion is True
    assert canonical_json(first.verification_results) == canonical_json(second.verification_results)
    assert canonical_json(first.audit_records[0].to_dict()) == canonical_json(
        second.audit_records[0].to_dict()
    )


def test_rerun_has_no_observable_side_effect_on_the_input_bundle() -> None:
    """Re-running does not mutate `GateInputBundle`/`QualityEvalRequest` —
    both are frozen dataclasses, and this test asserts the SAME request
    object still equals a freshly-built equivalent after being evaluated
    twice (nothing about running the engine could have mutated it, since
    frozen dataclasses structurally forbid attribute reassignment; this
    test documents that guarantee rather than merely relying on it)."""
    request = build_quality_eval_request()
    reference = build_quality_eval_request()
    assert request == reference

    run_quality_evaluation(request)
    run_quality_evaluation(request)

    assert request == reference


def test_verification_results_are_returned_in_a_stable_gate_order() -> None:
    request = build_quality_eval_request()
    first = run_quality_evaluation(request)
    second = run_quality_evaluation(request)
    first_order = [r["gate_id"] for r in first.verification_results]
    second_order = [r["gate_id"] for r in second.verification_results]
    assert first_order == second_order
