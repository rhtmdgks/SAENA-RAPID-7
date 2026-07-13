"""`engine.run_quality_evaluation` end-to-end: full happy-path aggregate,
`ALL_GATE_IDS` coverage of the produced `VerificationResult` rows/events/
audit records, and the resource-limits/profile re-export tie-in to the
shared execution-domain layer this service builds on."""

from __future__ import annotations

from factories import PATCH_UNIT_ID, build_gate_input_bundle, build_quality_eval_request
from saena_domain.execution import JobKind, JobStatus, profile_for, resource_limits_for
from saena_quality_eval.engine import (
    QUALITY_EVAL_PROFILE,
    QUALITY_EVAL_RESOURCE_LIMITS,
    advance_job_status,
    next_job_status,
    run_quality_evaluation,
)
from saena_quality_eval.gate_ids import ALL_GATE_IDS, GateId


def test_happy_path_produces_one_verification_result_per_gate(quality_eval_request) -> None:
    outcome = run_quality_evaluation(quality_eval_request)
    gate_ids_seen = {result["gate_id"] for result in outcome.verification_results}
    assert gate_ids_seen == {str(gid) for gid in ALL_GATE_IDS}
    assert len(outcome.verification_results) == len(ALL_GATE_IDS)


def test_happy_path_passes_every_gate_and_does_not_forbid_promotion(quality_eval_request) -> None:
    outcome = run_quality_evaluation(quality_eval_request)
    assert outcome.overall_status == "passed"
    assert outcome.forbids_promotion is False
    assert all(result["status"] == "passed" for result in outcome.verification_results)


def test_every_verification_result_row_carries_the_same_patch_unit_id(quality_eval_request) -> None:
    outcome = run_quality_evaluation(quality_eval_request)
    assert all(result["patch_unit_id"] == PATCH_UNIT_ID for result in outcome.verification_results)


def test_happy_path_emits_one_passed_event_per_gate(quality_eval_request) -> None:
    outcome = run_quality_evaluation(quality_eval_request)
    assert len(outcome.events) == len(ALL_GATE_IDS)
    assert all(event_type == "quality.gate.passed.v1" for event_type, _payload in outcome.events)


def test_happy_path_produces_one_audit_record_per_gate_with_no_error_codes(
    quality_eval_request,
) -> None:
    outcome = run_quality_evaluation(quality_eval_request)
    assert len(outcome.audit_records) == len(ALL_GATE_IDS)
    assert all(record.error_codes == () for record in outcome.audit_records)


def test_gate_result_for_looks_up_a_single_gate_row(quality_eval_request) -> None:
    outcome = run_quality_evaluation(quality_eval_request)

    build_row = outcome.gate_result_for(GateId.BUILD)
    assert build_row["gate_id"] == "build"
    assert build_row["status"] == "passed"


def test_next_job_status_and_advance_job_status_track_promotion(quality_eval_request) -> None:
    outcome = run_quality_evaluation(quality_eval_request)
    assert next_job_status(outcome) == JobStatus.SUCCEEDED
    transition_outcome = advance_job_status(JobStatus.RUNNING, outcome)
    assert transition_outcome.status == JobStatus.SUCCEEDED
    assert transition_outcome.changed is True


def test_resource_limits_and_profile_reexport_match_the_shared_execution_layer() -> None:
    assert profile_for(JobKind.QUALITY_EVAL) == QUALITY_EVAL_PROFILE
    assert resource_limits_for(JobKind.QUALITY_EVAL) == QUALITY_EVAL_RESOURCE_LIMITS
    assert QUALITY_EVAL_PROFILE.read_only is True  # "no Git write" (ADR-0004)
    assert QUALITY_EVAL_PROFILE.service_account == "saena-quality-eval"


def test_two_independently_built_equivalent_gate_input_bundles_compare_equal() -> None:
    """`GateInputBundle` is a pure value object — two separately constructed
    bundles from equal field values compare equal (`==`), not just
    identical."""
    assert build_gate_input_bundle() == build_gate_input_bundle()


def test_request_fixture_and_default_factory_produce_the_same_request() -> None:
    assert build_quality_eval_request() == build_quality_eval_request()
