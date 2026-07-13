"""Tests for saena_domain.experiment.ledger — hash, register, verify_ledger."""

from __future__ import annotations

import pytest
from saena_domain.experiment.errors import ConflictError, RejectedError
from saena_domain.experiment.ledger import (
    GENESIS,
    compute_content_fingerprint,
    compute_experiment_hash,
    register,
    verify_ledger,
)
from saena_domain.experiment.models import MetricDefinition

from .conftest import matched_cluster_arms, metric_definitions, registration

# --- compute_content_fingerprint: determinism / sensitivity / chain-position independence --


def test_fingerprint_is_deterministic_across_three_calls() -> None:
    reg = registration()
    h1 = compute_content_fingerprint(reg)
    h2 = compute_content_fingerprint(reg)
    h3 = compute_content_fingerprint(reg)
    assert h1 == h2 == h3
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 64


def test_fingerprint_is_deterministic_across_independently_built_equal_registrations() -> None:
    h1 = compute_content_fingerprint(registration())
    h2 = compute_content_fingerprint(registration())
    assert h1 == h2


def test_fingerprint_changes_when_a_field_changes() -> None:
    h_base = compute_content_fingerprint(registration())
    h_changed = compute_content_fingerprint(registration(repeat_count=6))
    assert h_base != h_changed


def test_fingerprint_changes_when_locale_changes() -> None:
    h_base = compute_content_fingerprint(registration())
    h_changed = compute_content_fingerprint(registration(locale="ko-KR"))
    assert h_base != h_changed


def test_fingerprint_changes_when_arms_change() -> None:
    h_base = compute_content_fingerprint(registration())
    h_changed = compute_content_fingerprint(registration(arms=matched_cluster_arms()))
    assert h_base != h_changed


def test_fingerprint_is_independent_of_canonical_and_previous_hash_and_itself() -> None:
    """Content fingerprint must NOT depend on chain position (previous_hash)
    or on the other hash-bearing fields — that chain-position independence
    is exactly what makes it safe/correct for idempotency comparison
    (register must treat the same content as a no-op regardless of where it
    would land in a ledger)."""
    reg = registration()
    stamped = reg.model_copy(
        update={
            "canonical_hash": "sha256:" + "9" * 64,
            "previous_hash": "sha256:" + "8" * 64,
            "content_fingerprint": "sha256:" + "7" * 64,
        }
    )
    assert compute_content_fingerprint(reg) == compute_content_fingerprint(stamped)


# --- compute_experiment_hash (chain-entry hash) ---------------------------------------
# determinism / sensitivity / previous_hash commitment


def test_chain_hash_is_deterministic_across_three_calls() -> None:
    reg = registration().model_copy(update={"previous_hash": "sha256:" + "1" * 64})
    h1 = compute_experiment_hash(reg)
    h2 = compute_experiment_hash(reg)
    h3 = compute_experiment_hash(reg)
    assert h1 == h2 == h3
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 64


def test_chain_hash_changes_when_a_content_field_changes() -> None:
    base = registration().model_copy(update={"previous_hash": "sha256:" + "1" * 64})
    changed = registration(repeat_count=6).model_copy(
        update={"previous_hash": "sha256:" + "1" * 64}
    )
    assert compute_experiment_hash(base) != compute_experiment_hash(changed)


def test_chain_hash_changes_when_only_previous_hash_changes() -> None:
    """The exact property the r4-03 fix adds: same content, different
    `previous_hash` (i.e. the same entry at a different chain position) MUST
    hash differently — otherwise a reordered/relinked entry could reuse its
    old chain hash and evade `verify_ledger`."""
    reg = registration()
    at_genesis = reg.model_copy(update={"previous_hash": None})
    at_position_two = reg.model_copy(update={"previous_hash": "sha256:" + "1" * 64})
    assert compute_experiment_hash(at_genesis) != compute_experiment_hash(at_position_two)


def test_chain_hash_is_independent_of_its_own_stored_canonical_hash_value() -> None:
    reg = registration().model_copy(update={"previous_hash": "sha256:" + "1" * 64})
    stamped = reg.model_copy(update={"canonical_hash": "sha256:" + "9" * 64})
    assert compute_experiment_hash(reg) == compute_experiment_hash(stamped)


# --- register: chain anchoring --------------------------------------------------------


def test_register_first_entry_anchors_to_genesis() -> None:
    ledger, entry = register((), registration())
    assert entry.previous_hash is GENESIS
    assert entry.canonical_hash == compute_experiment_hash(entry)
    assert entry.content_fingerprint == compute_content_fingerprint(registration())
    assert ledger == (entry,)


def test_register_second_entry_anchors_to_prior_canonical_hash() -> None:
    ledger, first = register((), registration(experiment_id="exp-1"))
    ledger, second = register(ledger, registration(experiment_id="exp-2"))
    assert second.previous_hash == first.canonical_hash
    assert ledger == (first, second)


def test_register_stores_content_fingerprint_distinct_from_canonical_hash() -> None:
    """The two identities must actually differ once `previous_hash` is
    non-GENESIS — otherwise the split is cosmetic, not real."""
    ledger, first = register((), registration(experiment_id="exp-1"))
    ledger, second = register(ledger, registration(experiment_id="exp-2"))
    assert second.content_fingerprint != second.canonical_hash
    assert second.content_fingerprint == compute_content_fingerprint(second)


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


# --- r4-03 adversarial suite: chain integrity under active tampering -------------------
#
# The mission's confirmed defect: the OLD `compute_experiment_hash` excluded
# `previous_hash` from its own hashed material, so an attacker could reorder
# ledger entries, relink `previous_hash` to match the new order, and reuse
# each entry's UNCHANGED `canonical_hash` — `verify_ledger` incorrectly
# passed. `test_old_vulnerability_reorder_and_relink_would_have_passed_verify`
# below pins the exact adversarial construction the mission specifies and
# proves the NEW (fixed) `verify_ledger` rejects it; the module docstring in
# `ledger.py` records the OLD-code pass-when-it-should-fail evidence
# (reproduced via a standalone script during r4-03 development — old
# `canonical_hash` never committed to `previous_hash`, so recompute-and-
# compare could never detect a reorder).


def _three_entry_ledger() -> tuple:
    state: tuple = ()
    for i in range(3):
        state, _ = register(state, registration(experiment_id=f"exp-{i}"))
    return state


def test_old_vulnerability_reorder_and_relink_would_have_passed_verify() -> None:
    """Adversarial reproducer (mission-required, recorded FIRST): build a
    valid 3-entry ledger, reorder two entries, re-link their `previous_hash`
    to the new order, and reuse each entry's EXISTING `canonical_hash`
    unchanged (simulating the attack the OLD hashing shape could not
    detect). Asserts the NEW `verify_ledger` correctly REJECTS this — this
    is the fixed-code assertion; the OLD-code equivalent of this exact
    construction was independently verified (outside pytest, see ledger.py
    module docstring) to return `(True, None)`, i.e. incorrectly pass."""
    e0, e1, e2 = _three_entry_ledger()

    # Swap e0 and e1, then relink previous_hash to the new order — reusing
    # each entry's ORIGINAL canonical_hash (the attacker never recomputes a
    # hash; that is exactly what a hash-forgery-free reorder attack means).
    reordered = (e1, e0, e2)
    relinked = []
    prev = GENESIS
    for entry in reordered:
        relinked.append(entry.model_copy(update={"previous_hash": prev}))
        prev = entry.canonical_hash
    tampered_ledger = tuple(relinked)

    ok, bad_index = verify_ledger(tampered_ledger)
    assert ok is False
    assert bad_index is not None


def test_adversarial_middle_entry_content_tamper_detected() -> None:
    e0, e1, e2 = _three_entry_ledger()
    tampered_e1 = e1.model_copy(update={"browser_policy": "mobile-emulated"})
    ok, bad_index = verify_ledger((e0, tampered_e1, e2))
    assert ok is False
    assert bad_index == 1


def test_adversarial_forged_canonical_hash_detected() -> None:
    e0, e1, e2 = _three_entry_ledger()
    forged = e0.model_copy(update={"canonical_hash": "sha256:" + "a" * 64})
    ok, bad_index = verify_ledger((forged, e1, e2))
    assert ok is False
    assert bad_index == 0


def test_adversarial_forged_previous_hash_detected() -> None:
    e0, e1, e2 = _three_entry_ledger()
    forged = e1.model_copy(update={"previous_hash": "sha256:" + "b" * 64})
    ok, bad_index = verify_ledger((e0, forged, e2))
    assert ok is False
    assert bad_index == 1


def test_adversarial_reorder_two_entries_without_relink_detected() -> None:
    """Simplest reorder: swap positions, do NOT touch previous_hash at all
    (previous_hash values now point at the wrong predecessors)."""
    e0, e1, e2 = _three_entry_ledger()
    ok, bad_index = verify_ledger((e1, e0, e2))
    assert ok is False
    assert bad_index == 0


def test_adversarial_reorder_with_full_previous_hash_relink_detected() -> None:
    """The full mission-specified attack shape, isolated as its own named
    test (in addition to the reproducer above): reorder + relink every
    previous_hash in the new ledger to look chain-consistent."""
    e0, e1, e2 = _three_entry_ledger()
    reordered = (e2, e0, e1)
    relinked = []
    prev = GENESIS
    for entry in reordered:
        relinked.append(entry.model_copy(update={"previous_hash": prev}))
        prev = entry.canonical_hash
    ok, bad_index = verify_ledger(tuple(relinked))
    assert ok is False
    assert bad_index is not None


def test_adversarial_middle_entry_deletion_and_relink_detected() -> None:
    """Delete e1, relink e2's previous_hash directly to e0's canonical_hash
    (reusing e2's original canonical_hash unchanged)."""
    e0, e1, e2 = _three_entry_ledger()
    relinked_e2 = e2.model_copy(update={"previous_hash": e0.canonical_hash})
    ok, bad_index = verify_ledger((e0, relinked_e2))
    assert ok is False
    assert bad_index == 1


def test_adversarial_splice_entry_from_another_ledger_and_relink_detected() -> None:
    """Take an entry from a WHOLLY SEPARATE ledger, splice it into this
    ledger's chain, and relink previous_hash to fit — the spliced entry's
    own canonical_hash was computed against a different ledger's chain
    position/content, so it cannot satisfy this ledger's chain-hash
    recompute even with previous_hash rewritten to fit."""
    e0, _e1, e2 = _three_entry_ledger()

    other_state: tuple = ()
    other_state, foreign_entry = register(other_state, registration(experiment_id="foreign-exp"))

    spliced_foreign = foreign_entry.model_copy(update={"previous_hash": e0.canonical_hash})
    relinked_e2 = e2.model_copy(update={"previous_hash": spliced_foreign.canonical_hash})

    ok, bad_index = verify_ledger((e0, spliced_foreign, relinked_e2))
    assert ok is False
    assert bad_index == 1


def test_adversarial_genesis_change_detected() -> None:
    """Rewrite the genesis entry's `previous_hash` away from GENESIS/None —
    must be caught at index 0 even though it has no real predecessor."""
    e0, e1, e2 = _three_entry_ledger()
    forged_genesis = e0.model_copy(update={"previous_hash": "sha256:" + "c" * 64})
    ok, bad_index = verify_ledger((forged_genesis, e1, e2))
    assert ok is False
    assert bad_index == 0


def test_intact_ledger_replay_determinism_across_three_verify_calls() -> None:
    ledger = _three_entry_ledger()
    results = [verify_ledger(ledger) for _ in range(3)]
    assert results == [(True, None)] * 3


def test_intact_ledger_replay_determinism_across_three_independent_builds() -> None:
    """Rebuilding the SAME sequence of registrations from scratch three
    times produces byte-identical, independently-verifying ledgers."""
    results = []
    for _ in range(3):
        state = _three_entry_ledger()
        results.append((state, verify_ledger(state)))

    first_state, first_result = results[0]
    for state, result in results[1:]:
        assert result == first_result == (True, None)
        assert [e.canonical_hash for e in state] == [e.canonical_hash for e in first_state]
        assert [e.previous_hash for e in state] == [e.previous_hash for e in first_state]


def test_byte_identical_registration_is_idempotent_no_op_end_to_end() -> None:
    """Full end-to-end idempotency proof through the fixed `register`: a
    byte-identical re-registration (including replay against a
    multi-entry, non-genesis ledger position) is a true no-op — same
    ledger identity, same stored entry, still verifies clean."""
    ledger, _ = register((), registration(experiment_id="exp-0"))
    ledger, target = register(ledger, registration(experiment_id="exp-1"))
    ledger, _ = register(ledger, registration(experiment_id="exp-2"))

    replayed_ledger, replayed_entry = register(ledger, registration(experiment_id="exp-1"))

    assert replayed_ledger == ledger
    assert replayed_entry is target
    assert verify_ledger(replayed_ledger) == (True, None)
