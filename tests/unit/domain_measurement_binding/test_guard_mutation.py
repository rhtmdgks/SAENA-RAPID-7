"""Guard-mutation coverage: removing each guard must flip a passing test.

Each test neutralizes exactly ONE guard (by monkeypatching its helper to a
no-op) and asserts that a submission which SHOULD be rejected now slips through
to a `BoundExperiment`. That proves the guard is the sole thing standing
between the adversarial input and acceptance — i.e. deleting the guard from
`binding.py` would make the corresponding adversarial test in `test_binding.py`
stop failing. If a guard were dead code, its no-op patch here would leave the
reject in place (raised by some OTHER guard) and the test would fail.
"""

from __future__ import annotations

import pytest
from saena_domain.experiment.ledger import compute_content_fingerprint
from saena_domain.experiment.models import ExperimentArm, MetricDefinition
from saena_domain.measurement import binding as binding_mod
from saena_domain.measurement.binding import (
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
    matching_cell,
    registered_metric_inputs,
    registered_weights,
    submission,
)

NOT_REGISTERED = WeightsPolicy.not_registered()


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


# --- Guard 1: registration integrity --------------------------------------------------


def test_removing_integrity_guard_lets_bad_hash_through(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = anchored_registration()
    bad = submission(reg, anchored_hash="sha256:" + "0" * 64)

    # sanity: guard present ⇒ reject
    with pytest.raises(binding_mod.BindingRejectedError):
        bind_experiment(reg, bad, weights=NOT_REGISTERED)

    monkeypatch.setattr(binding_mod, "_verify_registration_integrity", _noop)
    assert isinstance(bind_experiment(reg, bad, weights=NOT_REGISTERED), BoundExperiment)


# --- Guard 2: conflicting registration ------------------------------------------------


def test_removing_conflict_guard_lets_content_conflict_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = anchored_registration()
    # A different content_fingerprint but the HONEST anchored hash, so the only
    # guard standing between this submission and acceptance is the conflict
    # guard (the integrity guard still passes on the honest anchor).
    conflicting = submission(reg, content_fingerprint="sha256:" + "1" * 64)

    with pytest.raises(binding_mod.BindingRejectedError):
        bind_experiment(reg, conflicting, weights=NOT_REGISTERED)

    monkeypatch.setattr(binding_mod, "_reject_conflicting_registration", _noop)
    assert isinstance(bind_experiment(reg, conflicting, weights=NOT_REGISTERED), BoundExperiment)


# --- Guard 3: metric mutation ---------------------------------------------------------


def test_removing_metric_guard_lets_unknown_metric_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = anchored_registration()
    metrics = (
        *registered_metric_inputs(reg),
        MeasurementMetricInput(
            metric_id="ghost_metric", metric_hash="sha256:" + "a" * 64, weight=1.0
        ),
    )
    bad = submission(reg, metrics=metrics)

    with pytest.raises(binding_mod.BindingRejectedError):
        bind_experiment(reg, bad, weights=NOT_REGISTERED)

    monkeypatch.setattr(binding_mod, "_reject_metric_mutation", _noop)
    assert isinstance(bind_experiment(reg, bad, weights=NOT_REGISTERED), BoundExperiment)


def test_removing_metric_guard_lets_weight_tampering_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = anchored_registration()
    tampered = tuple(m.model_copy(update={"weight": 99.0}) for m in registered_metric_inputs(reg))
    bad = submission(reg, metrics=tampered)
    enforced = WeightsPolicy.enforce(registered_weights())

    with pytest.raises(binding_mod.BindingRejectedError):
        bind_experiment(reg, bad, weights=enforced)

    monkeypatch.setattr(binding_mod, "_reject_metric_mutation", _noop)
    assert isinstance(bind_experiment(reg, bad, weights=enforced), BoundExperiment)


# --- Guard 4: cell mismatch -----------------------------------------------------------


def test_removing_cell_guard_lets_cell_mismatch_through(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = anchored_registration()
    bad_cell = matching_cell().model_copy(update={"locale": "ko-KR"})
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-treatment",
            cell=bad_cell,
            asset_hash=REGISTERED_ASSET_HASH,
        ),
    )
    bad = submission(reg, observations=obs)

    with pytest.raises(binding_mod.BindingRejectedError):
        bind_experiment(reg, bad, weights=NOT_REGISTERED)

    monkeypatch.setattr(binding_mod, "_reject_cell_mismatch", _noop)
    assert isinstance(bind_experiment(reg, bad, weights=NOT_REGISTERED), BoundExperiment)


# --- Guard 5: contamination -----------------------------------------------------------


def test_removing_contamination_guard_lets_cross_arm_reuse_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    bad = submission(reg, observations=obs)

    with pytest.raises(binding_mod.BindingRejectedError):
        bind_experiment(reg, bad, weights=NOT_REGISTERED)

    monkeypatch.setattr(binding_mod, "_reject_contamination", _noop)
    assert isinstance(bind_experiment(reg, bad, weights=NOT_REGISTERED), BoundExperiment)


def test_removing_contamination_guard_lets_asset_hash_conflict_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = anchored_registration()
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-treatment",
            cell=matching_cell(),
            asset_hash="sha256:" + "9" * 64,
        ),
    )
    bad = submission(reg, observations=obs)

    with pytest.raises(binding_mod.BindingRejectedError):
        bind_experiment(reg, bad, weights=NOT_REGISTERED)

    monkeypatch.setattr(binding_mod, "_reject_contamination", _noop)
    assert isinstance(bind_experiment(reg, bad, weights=NOT_REGISTERED), BoundExperiment)


def test_removing_contamination_guard_lets_matched_cluster_leak_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matched-cluster design: the cluster-ownership contamination reject is
    load-bearing too (critic #1 should-fix)."""
    arms = (
        ExperimentArm(arm_id="arm-baseline", role="baseline", query_cluster_ref="qc-a"),
        ExperimentArm(arm_id="arm-matched", role="matched_cluster", query_cluster_ref="qc-b"),
    )
    reg = anchored_registration(arms=arms)
    obs = (
        Observation(
            observation_id="obs-1",
            arm_id="arm-matched",
            cell=matching_cell(),
            query_cluster_ref="qc-a",  # baseline's registered cluster — a leak
        ),
    )
    bad = submission(reg, observations=obs)

    with pytest.raises(binding_mod.BindingRejectedError):
        bind_experiment(reg, bad, weights=NOT_REGISTERED)

    monkeypatch.setattr(binding_mod, "_reject_contamination", _noop)
    assert isinstance(bind_experiment(reg, bad, weights=NOT_REGISTERED), BoundExperiment)


# --- Guard 6: cross-tenant (existence oracle) -----------------------------------------


def test_cross_tenant_guard_is_load_bearing() -> None:
    """No monkeypatch: prove the tenant check is what denies access — a
    matching tenant on the same registration/submission is accepted, a
    mismatched tenant is denied. Removing the `tenant_id != ...` clause would
    make the mismatched case accept."""
    reg = anchored_registration()
    assert isinstance(
        bind_experiment(reg, submission(reg), weights=NOT_REGISTERED), BoundExperiment
    )
    with pytest.raises(binding_mod.BindingNotFoundError):
        bind_experiment(reg, submission(reg, tenant_id="other-tenant"), weights=NOT_REGISTERED)


# --- metric fingerprint helper (public, reused by callers) ----------------------------


def test_compute_metric_fingerprint_is_deterministic_and_sensitive() -> None:
    m = MetricDefinition(metric_id="citation_presence", description="cited in response")
    assert compute_metric_fingerprint(m) == compute_metric_fingerprint(m)
    altered = MetricDefinition(metric_id="citation_presence", description="changed")
    assert compute_metric_fingerprint(m) != compute_metric_fingerprint(altered)
    assert compute_metric_fingerprint(m).startswith("sha256:")


def test_content_fingerprint_helper_import_smoke() -> None:
    # keeps the compute_content_fingerprint import exercised (used in conftest)
    reg = anchored_registration()
    assert compute_content_fingerprint(reg).startswith("sha256:")
