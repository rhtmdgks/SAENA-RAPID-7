"""ReasonCode vocabulary completeness + closed-enum discipline (H7)."""

from __future__ import annotations

from saena_domain.measurement.reason_codes import ReasonCode

#: Every code this patch unit's directive requires AT MINIMUM.
REQUIRED_CODES: frozenset[str] = frozenset(
    {
        "missing_baseline",
        "missing_control",
        "treatment_control_contamination",
        "post_registration_metric_mutation",
        "cell_mismatch",
        "insufficient_repeats",
        "deployment_unconfirmed",
        "deployment_late",
        "missing_raw_evidence_ref",
        "asset_hash_conflict",
        "single_layer_only",
        "no_control_adjusted_lift",
        "negative_or_inconclusive_lift",
        "non_finite_input",
        "window_incomplete",
        "observation_adapter_drift",
        "grs_policy_missing",
        "evidence_hash_mismatch",
        "conflicting_confirmation",
        "identity_mismatch",
        "duplicate_evidence_basis",
    }
)


def test_all_required_codes_present() -> None:
    present = {code.value for code in ReasonCode}
    missing = REQUIRED_CODES - present
    assert not missing, f"missing required reason codes: {sorted(missing)}"


def test_values_are_unique() -> None:
    values = [code.value for code in ReasonCode]
    assert len(values) == len(set(values))


def test_str_enum_serialises_to_wire_value() -> None:
    assert ReasonCode.SINGLE_LAYER_ONLY == "single_layer_only"
    assert ReasonCode.DUPLICATE_EVIDENCE_BASIS.value == "duplicate_evidence_basis"
