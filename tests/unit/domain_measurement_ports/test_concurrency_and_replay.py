"""Hard idempotency guarantees under concurrency, replay, restart, rollback (w5-09).

These are the discriminating tests the directive names explicitly:

- concurrent-writer simulation: threads hammering the SAME key with a mix of
  identical + different payloads → exactly-one-winner (the FIRST accepted
  content), every conflicting write raises, the store is never corrupt.
- at-least-once replay: the same op applied twice → a single record.
- restart simulation: rebuilding a store from the journal of ACCEPTED ops →
  byte-identical state.
- transaction-rollback semantics: a failed atomic put leaves NO trace.
"""

from __future__ import annotations

import threading

import pytest
from measurement_factories import TENANT_A, make_confirmation, make_decision
from saena_domain.measurement.ports import (
    AppendOnlyViolationError,
    IdempotencyConflictError,
    InMemoryConfirmationStore,
    InMemoryOutcomeDecisionStore,
    PutOutcome,
    replay_confirmation_journal,
)

_KEY = "acme-co:run-0007:capsule-hot"


def test_concurrent_writers_exactly_one_winner_first_content() -> None:
    store = InMemoryConfirmationStore()
    n_threads = 40
    barrier = threading.Barrier(n_threads)
    # Half the writers submit payload A, half payload B. Exactly one payload
    # can win (whichever the store accepts first); every writer submitting the
    # OTHER payload must conflict. Writers submitting the winning payload after
    # it is stored get a DUPLICATE no-op.
    payload_a = {"v": "A"}
    payload_b = {"v": "B"}
    outcomes: list[object] = []
    conflicts: list[BaseException] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        payload = payload_a if idx % 2 == 0 else payload_b
        rec = make_confirmation(confirmation_key=_KEY, payload=payload)
        barrier.wait()
        try:
            result = store.put_confirmation(TENANT_A, _KEY, rec)
        except IdempotencyConflictError as exc:
            with lock:
                conflicts.append(exc)
        else:
            with lock:
                outcomes.append(result.outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # The store holds exactly one record for the key, and it is one of the two
    # payloads submitted — never a corrupt/interleaved value.
    stored = store.get(TENANT_A, _KEY)
    assert stored.payload["v"] in {"A", "B"}
    winner = stored.payload["v"]
    loser_count = sum(
        1 for i in range(n_threads) if (payload_a if i % 2 == 0 else payload_b)["v"] != winner
    )
    # Every writer of the losing payload conflicted; nobody of the winning
    # payload conflicted.
    assert len(conflicts) == loser_count
    # Exactly one STORED outcome (the first winning write); the rest of the
    # winning payload's writers saw DUPLICATE.
    assert outcomes.count(PutOutcome.STORED) == 1
    assert all(o in {PutOutcome.STORED, PutOutcome.DUPLICATE} for o in outcomes)


def test_concurrent_identical_writers_single_record_no_conflict() -> None:
    # Pure at-least-once storm: every writer submits byte-identical content.
    # No conflict may ever be raised; exactly one STORED, the rest DUPLICATE.
    store = InMemoryConfirmationStore()
    n = 50
    barrier = threading.Barrier(n)
    results: list[object] = []
    lock = threading.Lock()

    def worker() -> None:
        rec = make_confirmation(confirmation_key=_KEY, payload={"v": "same"})
        barrier.wait()
        result = store.put_confirmation(TENANT_A, _KEY, rec)
        with lock:
            results.append(result.outcome)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(PutOutcome.STORED) == 1
    assert results.count(PutOutcome.DUPLICATE) == n - 1


def test_concurrent_append_only_decisions_exactly_one_winner() -> None:
    store = InMemoryOutcomeDecisionStore()
    n = 30
    barrier = threading.Barrier(n)
    violations: list[BaseException] = []
    stored = 0
    lock = threading.Lock()

    def worker(idx: int) -> None:
        nonlocal stored
        d = make_decision(decision_key=("exp-race", "primary"), outcome=f"outcome-{idx % 3}")
        barrier.wait()
        try:
            result = store.append_decision(TENANT_A, d)
        except AppendOnlyViolationError as exc:
            with lock:
                violations.append(exc)
        else:
            with lock:
                if result.outcome is PutOutcome.STORED:
                    stored += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one decision is the append-only winner; every conflicting
    # overwrite attempt raised. Duplicates of the winning content are no-ops.
    assert stored == 1
    listed = store.list_decisions(TENANT_A)
    assert len(listed) == 1


def test_at_least_once_replay_single_record() -> None:
    store = InMemoryConfirmationStore()
    rec = make_confirmation()
    for _ in range(5):  # redelivered 5x
        store.put_confirmation(TENANT_A, rec.confirmation_key, rec)
    # A single stored record; a journal of accepted ops has exactly one entry.
    assert len(store.snapshot(TENANT_A)) == 1
    assert len(store.journal()) == 1  # only the FIRST accepted op journaled


def test_restart_from_journal_rebuilds_identical_state() -> None:
    # Apply a workload, capture the journal of ACCEPTED ops, then rebuild a
    # fresh store by replaying that journal — state must be byte-identical.
    store = InMemoryConfirmationStore()
    recs = [make_confirmation(confirmation_key=f"k-{i}", payload={"i": i}) for i in range(6)]
    for rec in recs:
        store.put_confirmation(TENANT_A, rec.confirmation_key, rec)
        store.put_confirmation(TENANT_A, rec.confirmation_key, rec)  # replay noise
    journal = store.journal()
    assert len(journal) == len(recs)  # replays did not add journal entries

    rebuilt = replay_confirmation_journal(journal)
    assert rebuilt.snapshot(TENANT_A) == store.snapshot(TENANT_A)
    # Replaying twice (at-least-once journal delivery) is also idempotent.
    rebuilt_twice = replay_confirmation_journal(journal + journal)
    assert rebuilt_twice.snapshot(TENANT_A) == store.snapshot(TENANT_A)


def test_rollback_failed_atomic_put_leaves_no_trace() -> None:
    # A conflicting put must not leave any partial state: not a half-written
    # record, not a journal entry, not a phantom key.
    store = InMemoryConfirmationStore()
    original = make_confirmation(payload={"v": "orig"})
    store.put_confirmation(TENANT_A, original.confirmation_key, original)
    journal_before = store.journal()
    snapshot_before = store.snapshot(TENANT_A)
    with pytest.raises(IdempotencyConflictError):
        store.put_confirmation(
            TENANT_A, original.confirmation_key, make_confirmation(payload={"v": "new"})
        )
    # Nothing changed: journal, snapshot, and the resolvable record are all
    # exactly as before the failed put.
    assert store.journal() == journal_before
    assert store.snapshot(TENANT_A) == snapshot_before
    assert store.get(TENANT_A, original.confirmation_key) == original
