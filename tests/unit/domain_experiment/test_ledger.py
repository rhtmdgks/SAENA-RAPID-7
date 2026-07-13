"""Tests for saena_domain.experiment.ledger — hash, register, verify_ledger."""

from __future__ import annotations

import pytest
from saena_domain.experiment.errors import ConflictError, RejectedError
from saena_domain.experiment.ledger import (
    GENESIS,
    compute_experiment_hash,
    register,
    verify_ledger,
)
from saena_domain.experiment.models import MetricDefinition

from .conftest import matched_cluster_arms, metric_definitions, registration

# --- compute_experiment_hash: determinism / sensitivity ------------------------------


def test_hash_is_deterministic_across_three_calls() -> None:
    reg = registration()
    h1 = compute_experiment_hash(reg)
    h2 = compute_experiment_hash(reg)
    h3 = compute_experiment_hash(reg)
    assert h1 == h2 == h3
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 64


def test_hash_is_deterministic_across_independently_built_equal_registrations() -> None:
    h1 = compute_experiment_hash(registration())
    h2 = compute_experiment_hash(registration())
    assert h1 == h2


def test_hash_changes_when_a_field_changes() -> None:
    h_base = compute_experiment_hash(registration())
    h_changed = compute_experiment_hash(registration(repeat_count=6))
    assert h_base != h_changed


def test_hash_changes_when_locale_changes() -> None:
    h_base = compute_experiment_hash(registration())
    h_changed = compute_experiment_hash(registration(locale="ko-KR"))
    assert h_base != h_changed


def test_hash_changes_when_arms_change() -> None:
    h_base = compute_experiment_hash(registration())
    h_changed = compute_experiment_hash(registration(arms=matched_cluster_arms()))
    assert h_base != h_changed


def test_hash_is_independent_of_canonical_and_previous_hash_fields() -> None:
    reg = registration()
    stamped = reg.model_copy(
        update={"canonical_hash": "sha256:" + "9" * 64, "previous_hash": "sha256:" + "8" * 64}
    )
    assert compute_experiment_hash(reg) == compute_experiment_hash(stamped)


# --- register: chain anchoring --------------------------------------------------------


def test_register_first_entry_anchors_to_genesis() -> None:
    ledger, entry = register((), registration())
    assert entry.previous_hash is GENESIS
    assert entry.canonical_hash == compute_experiment_hash(registration())
    assert ledger == (entry,)


def test_register_second_entry_anchors_to_prior_canonical_hash() -> None:
    ledger, first = register((), registration(experiment_id="exp-1"))
    ledger, second = register(ledger, registration(experiment_id="exp-2"))
    assert second.previous_hash == first.canonical_hash
    assert ledger == (first, second)


# --- register: idempotency / conflict / rejection -------------------------------------


def test_register_duplicate_identical_content_is_idempotent_no_double_append() -> None:
    ledger, first = register((), registration())
    ledger2, replay = register(ledger, registration())
    assert ledger2 == ledger
    assert len(ledger2) == 1
    assert replay is first


def test_register_replay_is_safe_to_call_multiple_times() -> None:
    ledger, first = register((), registration())
    for _ in range(3):
        ledger, entry = register(ledger, registration())
        assert len(ledger) == 1
        assert entry is first


def test_register_duplicate_id_changed_arms_raises_rejected_error() -> None:
    ledger, _ = register((), registration())
    with pytest.raises(RejectedError):
        register(ledger, registration(arms=matched_cluster_arms()))


def test_register_duplicate_id_changed_metric_definitions_raises_rejected_error() -> None:
    ledger, _ = register((), registration())
    changed_metrics = (
        *metric_definitions(),
        MetricDefinition(metric_id="extra_metric", description="an extra registered metric"),
    )
    with pytest.raises(RejectedError):
        register(ledger, registration(metric_definitions=changed_metrics))


def test_register_duplicate_id_changed_non_design_field_raises_conflict_error() -> None:
    ledger, _ = register((), registration())
    with pytest.raises(ConflictError):
        register(ledger, registration(repeat_count=99))


def test_rejected_and_conflict_errors_carry_only_experiment_id() -> None:
    ledger, _ = register((), registration())
    try:
        register(ledger, registration(arms=matched_cluster_arms()))
    except RejectedError as exc:
        assert exc.experiment_id == "exp-2026-0713-0001"
    else:
        pytest.fail("expected RejectedError")


# --- verify_ledger: tamper detection ---------------------------------------------------


def test_verify_ledger_intact_chain_returns_true_none() -> None:
    ledger, _ = register((), registration(experiment_id="exp-1"))
    ledger, _ = register(ledger, registration(experiment_id="exp-2"))
    assert verify_ledger(ledger) == (True, None)


def test_verify_ledger_detects_mutated_field() -> None:
    ledger, entry = register((), registration(experiment_id="exp-1"))
    tampered = entry.model_copy(update={"repeat_count": 999})
    tampered_ledger = (tampered,)
    ok, bad_index = verify_ledger(tampered_ledger)
    assert ok is False
    assert bad_index == 0


def test_verify_ledger_detects_broken_previous_hash_link() -> None:
    ledger, first = register((), registration(experiment_id="exp-1"))
    ledger, second = register(ledger, registration(experiment_id="exp-2"))
    tampered_second = second.model_copy(update={"previous_hash": "sha256:" + "f" * 64})
    tampered_ledger = (first, tampered_second)
    ok, bad_index = verify_ledger(tampered_ledger)
    assert ok is False
    assert bad_index == 1


def test_verify_ledger_empty_chain_is_valid() -> None:
    assert verify_ledger(()) == (True, None)


def test_verify_ledger_detects_tamper_in_middle_entry_of_three() -> None:
    ledger, _ = register((), registration(experiment_id="exp-1"))
    ledger, _ = register(ledger, registration(experiment_id="exp-2"))
    ledger, _ = register(ledger, registration(experiment_id="exp-3"))
    mutated_middle = ledger[1].model_copy(update={"locale": "ja-JP"})
    tampered_ledger = (ledger[0], mutated_middle, ledger[2])
    ok, bad_index = verify_ledger(tampered_ledger)
    assert ok is False
    assert bad_index == 1
