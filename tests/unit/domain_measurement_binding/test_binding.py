"""Tests for saena_domain.measurement.binding — measurement-time immutability.

Structure: one ACCEPT-path proof per shape, then per-guard adversarial rejects
(each mutating exactly ONE field from the clean fixture), plus the
cross-tenant existence-oracle indistinguishability proof and a bidirectional
contamination matrix (asset design AND matched-cluster design).
`test_guard_mutation.py` proves each guard is load-bearing (its removal flips
a test here).

Weight enforcement is an explicit `WeightsPolicy` (critic #2, w5-04 rework):
`bind_experiment` REQUIRES `weights=` — a forgotten kwarg is a loud
`TypeError`, never a silent fail-open; `WeightsPolicy.not_registered()` is the
only opt-out and is pinned below as a deliberate declaration.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError
from saena_domain.experiment.ledger import compute_experiment_hash
from saena_domain.experiment.models import ExperimentArm, MetricDefinition
from saena_domain.measurement.binding import (
    BindingNotFoundError,
    BindingRejectedError,
    BoundExperiment,
    MeasurementMetricInput,
    Observation,
    WeightsPolicy,
    bind_experiment,
    compute_metric_fingerprint,
)

from .conftest import (
    REGISTERED_ASSET_HASH,
    anchored_registration,
    clean_observations,
    matching_cell,
    registered_metric_inputs,
    registered_weights,
    submission,
)

#: Shorthand for tests where weights are NOT the property under test — a
#: deliberate, visible opt-out (the registration fixtures carry no weights).
NOT_REGISTERED = WeightsPolicy.not_registered()


# --- ACCEPT path ----------------------------------------------------------------------


def test_bind_accepts_a_clean_submission() -> None:
    reg = anchored_registration()
    bound = bind_experiment(reg, submission(reg), weights=NOT_REGISTERED)
    assert isinstance(bound, BoundExperiment)
    assert bound.experiment_id == reg.experiment_id
    assert bound.tenant_id == reg.tenant_id
    assert bound.anchored_hash == reg.canonical_hash


def test_bind_accepts_with_enforced_registered_weights() -> None:
    reg = anchored_registration()
    bound = bind_experiment(
        reg, submission(reg), weights=WeightsPolicy.enforce(registered_weights())
    )
    assert isinstance(bound, BoundExperiment)


def test_bound_experiment_carries_registered_cell_and_arms_readonly() -> None:
    reg = anchored_registration()
    bound = bind_experiment(reg, submission(reg), weights=NOT_REGISTERED)
    assert bound.registered_cell == matching_cell()
    assert ("arm-treatment", "treatment") in bound.arm_roles
    assert ("arm-control", "control") in bound.arm_roles
    assert set(bound.metric_ids) == {"citation_presence", "prominence_rank"}
    assert bound.observations == clean_observations()


def test_bound_experiment_is_frozen() -> None:
    reg = anchored_registration()
    bound = bind_experiment(reg, submission(reg), weights=NOT_REGISTERED)
    with pytest.raises(ValidationError):
        bound.experiment_id = "mutated"


def test_bind_is_deterministic_three_calls_same_result() -> None:
    reg = anchored_registration()
    results = [bind_experiment(reg, submission(reg), weights=NOT_REGISTERED) for _ in range(3)]
    assert results[0] == results[1] == results[2]


def _matched_cluster_arms(
    baseline_ref: str | None = "qc-a", matched_ref: str | None = "qc-b"
) -> tuple[ExperimentArm, ...]:
    return (
        ExperimentArm(arm_id="arm-baseline", role="baseline", query_cluster_ref=baseline_ref),
        ExperimentArm(arm_id="arm-matched", role="matched_cluster", query_cluster_ref=matched_ref),
    )


def test_bind_accepts_matched_cluster_design() -> None:
    reg = anchored_registration(arms=_matched_cluster_arms())
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-baseline",
            cell=matching_cell(),
            query_cluster_ref="qc-a",
        ),
        Observation(
            observation_id="obs-2",
            arm_id="arm-matched",
            cell=matching_cell(),
            query_cluster_ref="qc-b",
        ),
    )
    bound = bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert isinstance(bound, BoundExperiment)


# --- WeightsPolicy: explicit, non-forgettable enforcement state ------------------------


def test_omitting_weights_kwarg_is_a_loud_typeerror() -> None:
    """The fail-open-by-omission path is closed: a caller that forgets weight
    enforcement does NOT silently bind — it cannot call at all (ALG §3.6:190,
    critic #2 should-fix)."""
    reg = anchored_registration()
    with pytest.raises(TypeError):
        bind_experiment(reg, submission(reg))  # type: ignore[call-arg]


def test_not_registered_is_a_deliberate_opt_out_only() -> None:
    """`WeightsPolicy.not_registered()` skips weight comparison — pinned here
    as the DELIBERATE opt-out for engagements that registered no weights (the
    registration model carries none). It is the only way to bind without a
    registered-weights mapping."""
    reg = anchored_registration()
    off_weights = tuple(
        m.model_copy(update={"weight": 42.0}) for m in registered_metric_inputs(reg)
    )
    bound = bind_experiment(
        reg, submission(reg, metrics=off_weights), weights=WeightsPolicy.not_registered()
    )
    assert isinstance(bound, BoundExperiment)


def test_weights_policy_has_exactly_two_modes() -> None:
    assert WeightsPolicy.enforce({"m": 1.0}).mode == "enforce"
    assert WeightsPolicy.not_registered().mode == "not_registered"
    with pytest.raises(ValidationError):
        WeightsPolicy(mode="maybe")  # type: ignore[arg-type]


def test_weights_policy_registered_weight_for() -> None:
    policy = WeightsPolicy.enforce({"a": 1.0, "b": 0.5})
    assert policy.registered_weight_for("a") == 1.0
    assert policy.registered_weight_for("b") == 0.5
    assert policy.registered_weight_for("ghost") is None


# --- Guard 1: registration integrity (post_registration_mutation) ---------------------


def test_post_registration_mutation_rejected() -> None:
    """A registration whose content was altered after anchoring no longer
    hashes to the anchored value → reject. We anchor the honest registration,
    then hand `bind` a MUTATED registration but the ORIGINAL anchored hash."""
    reg = anchored_registration()
    honest_anchor = reg.canonical_hash
    # Mutate a hashed content field but KEEP the stored content_fingerprint so
    # the conflict guard passes and the integrity guard is the one that fires:
    # the recomputed chain hash no longer matches the anchored hash.
    mutated = reg.model_copy(update={"code_version_hash": "sha256:" + "f" * 64})
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(
            mutated,
            submission(
                mutated,
                anchored_hash=honest_anchor,
                content_fingerprint=mutated.content_fingerprint,
            ),
            weights=NOT_REGISTERED,
        )
    assert exc.value.reason == "post_registration_mutation"


def test_integrity_uses_the_real_w4_hash_function() -> None:
    """The guard must accept exactly the value compute_experiment_hash yields —
    proving it re-derives via the W4 function, not a private reimplementation."""
    reg = anchored_registration()
    assert reg.canonical_hash == compute_experiment_hash(reg)
    bind_experiment(
        reg,
        submission(reg, anchored_hash=compute_experiment_hash(reg)),
        weights=NOT_REGISTERED,
    )


def test_wrong_anchored_hash_rejected() -> None:
    reg = anchored_registration()
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(
            reg, submission(reg, anchored_hash="sha256:" + "0" * 64), weights=NOT_REGISTERED
        )
    assert exc.value.reason == "post_registration_mutation"


# --- Guard 2: conflicting registration ------------------------------------------------


def test_same_id_different_content_fingerprint_rejected() -> None:
    reg = anchored_registration()
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(
            reg,
            submission(reg, content_fingerprint="sha256:" + "1" * 64),
            weights=NOT_REGISTERED,
        )
    assert exc.value.reason == "conflicting_registration"


def test_conflicting_registration_checked_before_integrity() -> None:
    """content-fingerprint conflict is reported as conflicting_registration,
    not masked by a downstream reject."""
    reg = anchored_registration()
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(
            reg,
            submission(
                reg,
                content_fingerprint="sha256:" + "2" * 64,
                anchored_hash="sha256:" + "0" * 64,
            ),
            weights=NOT_REGISTERED,
        )
    assert exc.value.reason == "conflicting_registration"


# --- Guard 3: metric mutation ---------------------------------------------------------


def test_unknown_metric_id_rejected() -> None:
    reg = anchored_registration()
    metrics = (
        *registered_metric_inputs(reg),
        MeasurementMetricInput(
            metric_id="unregistered_metric",
            metric_hash="sha256:" + "a" * 64,
            weight=1.0,
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, metrics=metrics), weights=NOT_REGISTERED)
    assert exc.value.reason == "metric_mutation"
    assert exc.value.field == "unregistered_metric"


def test_altered_metric_definition_same_id_rejected() -> None:
    """Reusing a registered metric_id but with a hash of an ALTERED definition."""
    reg = anchored_registration()
    altered_hash = compute_metric_fingerprint(
        MetricDefinition(metric_id="citation_presence", description="TAMPERED description")
    )
    metrics = (
        MeasurementMetricInput(metric_id="citation_presence", metric_hash=altered_hash, weight=1.0),
        registered_metric_inputs(reg)[1],
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, metrics=metrics), weights=NOT_REGISTERED)
    assert exc.value.reason == "metric_mutation"
    assert exc.value.field == "citation_presence"


def test_kpi_weight_tampering_rejected() -> None:
    reg = anchored_registration()
    tampered = tuple(
        m.model_copy(update={"weight": 99.0}) if m.metric_id == "prominence_rank" else m
        for m in registered_metric_inputs(reg)
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(
            reg,
            submission(reg, metrics=tampered),
            weights=WeightsPolicy.enforce(registered_weights()),
        )
    assert exc.value.reason == "metric_mutation"
    assert exc.value.field == "prominence_rank"


def test_metric_absent_from_enforced_weights_map_rejected() -> None:
    """A metric present in the submission but absent from the enforced
    registered-weights mapping is a weight mutation."""
    reg = anchored_registration()
    partial_weights = {"citation_presence": 1.0}  # prominence_rank missing
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(
            reg,
            submission(reg, metrics=registered_metric_inputs(reg)),
            weights=WeightsPolicy.enforce(partial_weights),
        )
    assert exc.value.reason == "metric_mutation"


# --- Guard 4: cell mismatch (each field) ----------------------------------------------


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("locale", "ko-KR"),
        ("browser_policy", "mobile-strict"),
        ("query_cluster_ref", "qc-other"),
        ("repeat_count", 9),
    ],
)
def test_cell_mismatch_each_field_named(field: str, bad_value: object) -> None:
    reg = anchored_registration()
    bad_cell = matching_cell().model_copy(update={field: bad_value})
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-treatment",
            cell=bad_cell,
            asset_hash=REGISTERED_ASSET_HASH,
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "cell_mismatch"
    assert exc.value.field == field


# --- Guard 5: contamination + asset-hash (asset design) --------------------------------


def test_treatment_cell_appearing_in_control_is_contamination() -> None:
    """Same query-cell reference under both treatment and control."""
    reg = anchored_registration()
    shared = "sha256:" + "7" * 64
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-treatment",
            cell=matching_cell(),
            query_cluster_ref=shared,
        ),
        Observation(
            observation_id="obs-2",
            arm_id="arm-control",
            cell=matching_cell(),
            query_cluster_ref=shared,
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "contamination"


def test_control_cell_appearing_in_treatment_is_contamination_reverse() -> None:
    """Reverse direction: emit control first, treatment second, same ref."""
    reg = anchored_registration()
    shared = "sha256:" + "8" * 64
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-control",
            cell=matching_cell(),
            query_cluster_ref=shared,
        ),
        Observation(
            observation_id="obs-2",
            arm_id="arm-treatment",
            cell=matching_cell(),
            query_cluster_ref=shared,
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "contamination"


def test_same_observation_id_claimed_by_two_arms_is_contamination() -> None:
    reg = anchored_registration()
    obs = (
        Observation(
            observation_id="dup",
            arm_id="arm-treatment",
            cell=matching_cell(),
            asset_hash=REGISTERED_ASSET_HASH,
        ),
        Observation(
            observation_id="dup",
            arm_id="arm-control",
            cell=matching_cell(),
            asset_hash=REGISTERED_ASSET_HASH,
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "contamination"
    assert exc.value.field == "dup"


def test_observation_referencing_unregistered_arm_is_contamination() -> None:
    reg = anchored_registration()
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-ghost",
            cell=matching_cell(),
            asset_hash=REGISTERED_ASSET_HASH,
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "contamination"
    assert exc.value.field == "arm-ghost"


def test_observed_asset_hash_differing_from_registered_is_asset_hash_conflict() -> None:
    reg = anchored_registration()
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-treatment",
            cell=matching_cell(),
            asset_hash="sha256:" + "9" * 64,
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "asset_hash_conflict"
    assert exc.value.field == "arm-treatment"


# --- Guard 5b: contamination (matched-cluster design; critic #1 should-fix) ------------


def test_matched_design_observation_claiming_other_arms_cluster_is_contamination() -> None:
    """An observation under arm-matched claiming the BASELINE arm's registered
    cluster (qc-a) is a cross-arm leak."""
    reg = anchored_registration(arms=_matched_cluster_arms())
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-matched",
            cell=matching_cell(),
            query_cluster_ref="qc-a",
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "contamination"
    assert exc.value.field == "arm-matched"


def test_matched_design_baseline_claiming_matched_cluster_is_contamination_reverse() -> None:
    """Reverse direction: baseline observation claiming the matched arm's
    registered cluster (qc-b)."""
    reg = anchored_registration(arms=_matched_cluster_arms())
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-baseline",
            cell=matching_cell(),
            query_cluster_ref="qc-b",
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "contamination"
    assert exc.value.field == "arm-baseline"


def test_matched_design_same_cluster_claimed_by_two_arms_is_contamination() -> None:
    """When arm-level registered refs cannot discriminate (baseline registered
    no cluster ref), the per-cluster ownership map still rejects the same
    cluster observed under two different arms."""
    reg = anchored_registration(arms=_matched_cluster_arms(baseline_ref=None, matched_ref="qc-x"))
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-baseline",
            cell=matching_cell(),
            query_cluster_ref="qc-x",
        ),
        Observation(
            observation_id="obs-2",
            arm_id="arm-matched",
            cell=matching_cell(),
            query_cluster_ref="qc-x",
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "contamination"
    assert exc.value.field == "qc-x"


def test_matched_design_cluster_ownership_is_bidirectional() -> None:
    """Reverse claim order: matched arm observes first, baseline second."""
    reg = anchored_registration(arms=_matched_cluster_arms(baseline_ref=None, matched_ref="qc-x"))
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-matched",
            cell=matching_cell(),
            query_cluster_ref="qc-x",
        ),
        Observation(
            observation_id="obs-2",
            arm_id="arm-baseline",
            cell=matching_cell(),
            query_cluster_ref="qc-x",
        ),
    )
    with pytest.raises(BindingRejectedError) as exc:
        bind_experiment(reg, submission(reg, observations=obs), weights=NOT_REGISTERED)
    assert exc.value.reason == "contamination"
    assert exc.value.field == "qc-x"


# --- Guard 6: cross-tenant existence-oracle -------------------------------------------


def test_cross_tenant_denied_as_not_found() -> None:
    reg = anchored_registration()
    with pytest.raises(BindingNotFoundError) as exc:
        bind_experiment(reg, submission(reg, tenant_id="attacker-co"), weights=NOT_REGISTERED)
    assert exc.value.reason == "not_found"


def test_absent_registration_is_not_found() -> None:
    reg = anchored_registration()
    with pytest.raises(BindingNotFoundError) as exc:
        bind_experiment(None, submission(reg), weights=NOT_REGISTERED)
    assert exc.value.reason == "not_found"


def test_cross_tenant_and_absent_are_indistinguishable() -> None:
    """The existence-oracle test: an attacker probing another tenant's
    experiment_id must get a byte-identical error shape to a genuinely-absent
    registration — same type, same reason, same string, same absent field."""
    reg = anchored_registration()

    cross_tenant = _capture(
        lambda: bind_experiment(
            reg, submission(reg, tenant_id="attacker-co"), weights=NOT_REGISTERED
        )
    )
    absent = _capture(
        lambda: bind_experiment(
            None, submission(reg, tenant_id="attacker-co"), weights=NOT_REGISTERED
        )
    )

    assert type(cross_tenant) is type(absent)
    assert cross_tenant.reason == absent.reason == "not_found"
    assert cross_tenant.field is absent.field is None
    assert str(cross_tenant) == str(absent)


def test_cross_tenant_does_not_leak_via_a_more_specific_reject() -> None:
    """Even when the submission ALSO carries a content conflict / bad hash /
    contamination, a wrong tenant is denied as not_found FIRST — no
    downstream reject can fire and reveal the registration exists."""
    reg = anchored_registration()
    poisoned = submission(
        reg,
        tenant_id="attacker-co",
        content_fingerprint="sha256:" + "1" * 64,
        anchored_hash="sha256:" + "0" * 64,
    )
    with pytest.raises(BindingNotFoundError) as exc:
        bind_experiment(reg, poisoned, weights=NOT_REGISTERED)
    assert exc.value.reason == "not_found"


def _capture(fn: Callable[[], object]) -> BindingNotFoundError:
    try:
        fn()
    except BindingNotFoundError as e:
        return e
    raise AssertionError("expected BindingNotFoundError")


# --- No-outcome-field discipline ------------------------------------------------------


def test_bound_experiment_has_no_outcome_fields() -> None:
    """Binding admits inputs; it never carries an outcome/effect/lift field
    (wave5-plan.md: DiD computation is downstream, w5-05)."""
    from saena_domain.experiment.models import FORBIDDEN_OUTCOME_TOKENS

    field_names = set(BoundExperiment.model_fields)
    for name in field_names:
        lowered = name.lower()
        for token in FORBIDDEN_OUTCOME_TOKENS:
            assert token not in lowered, f"{name} contains forbidden outcome token {token}"


# --- redaction discipline -------------------------------------------------------------


def test_reject_error_never_echoes_raw_registration_content() -> None:
    reg = anchored_registration()
    metrics = (
        *registered_metric_inputs(reg),
        MeasurementMetricInput(
            metric_id="unregistered_metric", metric_hash="sha256:" + "a" * 64, weight=1.0
        ),
    )
    try:
        bind_experiment(reg, submission(reg, metrics=metrics), weights=NOT_REGISTERED)
    except BindingRejectedError as e:
        message = str(e)
        # the message names the offending reference + reason only
        assert "unregistered_metric" in message
        assert reg.code_version_hash not in message
        assert reg.approved_by not in message
