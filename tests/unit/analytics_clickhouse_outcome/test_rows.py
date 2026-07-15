"""Unit tests for `saena_analytics_clickhouse.rows.MeasurementOutcomeRow`
(w5-11) — row building + field validation."""

from __future__ import annotations

import datetime as dt

import pytest
from analytics_clickhouse_outcome_factories import make_measurement_outcome_row
from saena_analytics_clickhouse.errors import RowValidationError
from saena_analytics_clickhouse.rows import (
    MEASUREMENT_OUTCOME_B_VERDICTS,
    MEASUREMENT_OUTCOME_LAYERS,
    MeasurementOutcomeRow,
)


class TestValidRowConstruction:
    def test_default_fixture_builds(self) -> None:
        row = make_measurement_outcome_row()
        assert row.tenant_id == "acme-co"
        assert row.b_verdict == "pass"
        assert row.outcome_layer == "discovery"

    def test_explicit_valid_ingested_at_is_accepted(self) -> None:
        ingested = dt.datetime(2026, 7, 8, 1, tzinfo=dt.UTC)
        row = make_measurement_outcome_row(ingested_at=ingested)
        assert row.ingested_at == ingested

    def test_naive_ingested_at_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(ingested_at=dt.datetime(2026, 7, 8))  # noqa: DTZ001

    def test_optional_fields_default_to_none(self) -> None:
        row = make_measurement_outcome_row(
            evidence_basis_id=None, net_of_control_lift=None, raw_lift=None
        )
        assert row.evidence_basis_id is None
        assert row.net_of_control_lift is None
        assert row.raw_lift is None
        assert row.ingested_at is None

    @pytest.mark.parametrize("verdict", MEASUREMENT_OUTCOME_B_VERDICTS)
    def test_every_declared_b_verdict_is_accepted(self, verdict: str) -> None:
        row = make_measurement_outcome_row(b_verdict=verdict)
        assert row.b_verdict == verdict

    @pytest.mark.parametrize("layer", MEASUREMENT_OUTCOME_LAYERS)
    def test_every_declared_outcome_layer_is_accepted(self, layer: str) -> None:
        row = make_measurement_outcome_row(outcome_layer=layer)
        assert row.outcome_layer == layer

    def test_reason_codes_may_be_empty(self) -> None:
        row = make_measurement_outcome_row(reason_codes=())
        assert row.reason_codes == ()

    def test_reason_codes_may_carry_multiple_codes(self) -> None:
        row = make_measurement_outcome_row(reason_codes=("code_a", "code_b"))
        assert row.reason_codes == ("code_a", "code_b")

    def test_is_frozen(self) -> None:
        row = make_measurement_outcome_row()
        with pytest.raises(AttributeError):
            row.b_verdict = "fail"  # type: ignore[misc]


class TestFieldValidation:
    def test_missing_tenant_id_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(tenant_id="")

    def test_missing_id_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(id="")

    def test_missing_idempotency_key_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(idempotency_key="")

    def test_naive_occurred_at_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(occurred_at=dt.datetime(2026, 7, 1))  # noqa: DTZ001

    def test_naive_window_started_at_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(window_started_at=dt.datetime(2026, 7, 1))  # noqa: DTZ001

    def test_naive_window_ended_at_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(window_ended_at=dt.datetime(2026, 7, 8))  # noqa: DTZ001

    def test_window_ended_before_started_rejected(self) -> None:
        start = dt.datetime(2026, 7, 8, tzinfo=dt.UTC)
        end = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(window_started_at=start, window_ended_at=end)

    def test_window_ended_equal_started_is_accepted(self) -> None:
        t = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
        row = make_measurement_outcome_row(window_started_at=t, window_ended_at=t)
        assert row.window_started_at == row.window_ended_at

    def test_missing_experiment_id_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(experiment_id="")

    def test_missing_registration_canonical_hash_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(registration_canonical_hash="")

    def test_unknown_b_verdict_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(b_verdict="maybe")

    def test_unknown_outcome_layer_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(outcome_layer="conversion")

    def test_conversion_layer_is_explicitly_excluded(self) -> None:
        """wave5-plan.md Non-scope: conversion is FORBIDDEN as a 7-day
        success metric — it must not be a valid `outcome_layer` value."""
        assert "conversion" not in MEASUREMENT_OUTCOME_LAYERS
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(outcome_layer="conversion")

    def test_negative_sample_count_treatment_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(sample_count_treatment=-1)

    def test_negative_sample_count_control_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(sample_count_control=-1)

    def test_zero_sample_counts_are_accepted(self) -> None:
        row = make_measurement_outcome_row(
            sample_count_treatment=0, sample_count_control=0, insufficient_data=True
        )
        assert row.sample_count_treatment == 0
        assert row.sample_count_control == 0

    def test_missing_evidence_bundle_manifest_hash_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(evidence_bundle_manifest_hash="")

    def test_missing_grs_policy_version_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(grs_policy_version="")

    def test_missing_grs_policy_hash_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(grs_policy_hash="")

    def test_missing_grs_policy_provenance_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(grs_policy_provenance="")

    def test_reason_code_element_too_long_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(reason_codes=("x" * 129,))

    def test_reason_code_empty_element_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_measurement_outcome_row(reason_codes=("",))


class TestFieldSetIsComplete:
    def test_no_field_named_lift_beyond_the_two_declared_summary_floats(self) -> None:
        """Mission decision check: only `net_of_control_lift`/`raw_lift` may
        carry an effect-magnitude-shaped name — no third, undocumented lift
        field should exist on the row."""
        field_names = {f for f in MeasurementOutcomeRow.__dataclass_fields__}
        lift_fields = {f for f in field_names if "lift" in f}
        assert lift_fields == {"net_of_control_lift", "raw_lift"}
