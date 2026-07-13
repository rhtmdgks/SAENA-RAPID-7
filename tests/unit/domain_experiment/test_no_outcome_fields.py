"""Pinned regression: saena_domain.experiment has NO outcome/effect/causal field.

Wave 4 w4-09 scope is REGISTRATION ONLY. Outcome computation (observed metric
values, effect sizes, lift, DiD/Bayesian uplift, significance) is Wave 5
(experiment-attribution-service outcome projection per ADR-0007 D-3). This
test asserts the absence of any such field/name in the public model surface
so a future edit that accidentally adds one fails CI immediately rather than
silently drifting this module out of its registration-only scope.
"""

from __future__ import annotations

import saena_domain.experiment as experiment_pkg
from saena_domain.experiment.models import (
    FORBIDDEN_OUTCOME_TOKENS,
    ExperimentArm,
    ExperimentRegistration,
    MetricDefinition,
)

_MODELS = (ExperimentRegistration, ExperimentArm, MetricDefinition)


def test_no_model_field_name_contains_an_outcome_token() -> None:
    for model in _MODELS:
        for field_name in model.model_fields:
            lowered = field_name.lower()
            offenders = [tok for tok in FORBIDDEN_OUTCOME_TOKENS if tok in lowered]
            assert not offenders, f"{model.__name__}.{field_name} looks outcome-shaped: {offenders}"


def test_forbidden_outcome_tokens_is_non_empty_and_covers_expected_terms() -> None:
    # Pins the token list itself against silent shrinkage.
    for expected in ("lift", "outcome", "causal", "did", "delta", "effect"):
        assert expected in FORBIDDEN_OUTCOME_TOKENS


def test_public_api_exports_no_outcome_computation_function() -> None:
    # `FORBIDDEN_OUTCOME_TOKENS` itself is the design-time guard constant (its
    # name legitimately contains "outcome") — excluded from its own check.
    for name in experiment_pkg.__all__:
        if name == "FORBIDDEN_OUTCOME_TOKENS":
            continue
        lowered = name.lower()
        offenders = [tok for tok in FORBIDDEN_OUTCOME_TOKENS if tok in lowered]
        assert not offenders, (
            f"saena_domain.experiment.__all__ entry {name!r} is outcome-shaped: {offenders}"
        )


def test_experiment_registration_has_exactly_the_specified_fields() -> None:
    expected = {
        "experiment_id",
        "tenant_id",
        "run_id",
        "arms",
        "metric_definitions",
        "query_cluster_ref",
        "locale",
        "browser_policy",
        "repeat_count",
        "asset_hash",
        "code_version_hash",
        "created_by",
        "approved_by",
        "created_at",
        "canonical_hash",
        "previous_hash",
        "content_fingerprint",
    }
    assert set(ExperimentRegistration.model_fields) == expected
