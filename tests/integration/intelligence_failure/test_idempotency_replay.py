"""Scenario 1 (w4-18 mission item 1): re-delivering the same observation/
claim/citation event (same idempotency_key) does not double-write; replaying
the claim-evidence ledger twice yields an identical QEEG projection (no
double-count).

Three independent "same idempotency key redelivered" proofs, one per
intelligence write-model this unit's own exclusive path can reach without a
container:

1. `saena_claim_evidence.ledger.append_claim`/`append_evidence` — byte-
   identical re-append (the ledger's OWN notion of "idempotency key" is the
   claim_id/evidence_id + content) is a no-op replay, never a duplicate
   ledger entry (`ledger.py`'s own module docstring: "no-op replay never
   mutates in place, always appends or returns the existing entry").
2. `saena_analytics_clickhouse.store.ClickHouseAnalyticsStore.append_*` —
   explicit `(tenant_id, idempotency_key)` dedup, proven against the
   in-memory fake executor (see `store.py`'s own module docstring:
   "duplicate-event idempotency" mission deliverable).
3. `saena_domain.bus.IdempotentConsumer` — the generic outbox/consumer
   redelivery-dedup mechanism, proven with a `patch.unit.completed.v1`
   envelope as the vehicle (see `intelligence_failure_factories.
   make_patch_unit_completed_envelope`'s own docstring for why this reuses
   an already-registered channel rather than inventing a new contract).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from intelligence_failure_factories import (
    RUN_ID,
    TENANT_A,
    make_evidence_record,
    make_experiment_registration,
    make_extracted_claim,
    make_observation_row,
    make_patch_unit_completed_envelope,
    new_fake_clickhouse_executor,
    run_async,
)
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore
from saena_claim_evidence.ledger import append_claim, append_evidence
from saena_domain.bus import IdempotentConsumer, InMemoryPublisher, OutboxDrainer
from saena_domain.experiment.ledger import register
from saena_domain.persistence.memory import InMemoryIdempotencyStore, InMemoryOutbox

pytestmark = pytest.mark.integration


def test_claim_ledger_replayed_append_is_a_no_op_not_a_duplicate_entry() -> None:
    claim = make_extracted_claim()

    state_1, entry_1 = append_claim((), claim)
    assert len(state_1) == 1

    # redelivery of the exact same claim (byte-identical content) — must
    # never grow the ledger a second time.
    state_2, entry_2 = append_claim(state_1, claim)

    assert state_2 is state_1
    assert len(state_2) == 1
    assert entry_2 is entry_1


def test_evidence_ledger_replayed_append_is_a_no_op_not_a_duplicate_entry() -> None:
    claim = make_extracted_claim()
    evidence = make_evidence_record()
    state, _ = append_claim((), claim)

    link_statuses: dict[str, object] = {}
    now = datetime(2026, 7, 13, tzinfo=UTC)

    state_1, entry_1 = append_evidence(
        state,
        evidence,
        link_statuses=link_statuses,
        now=now,
    )
    # claim + evidence + one re-evaluated claim entry (publishability flips
    # to True once its first supporting evidence lands — see `ledger.
    # append_evidence`'s own docstring "re-evaluate ... append a fresh
    # publishability-updated entry").
    assert len(state_1) == 3

    # redelivery of the exact same evidence — the SAME `link_statuses` dict
    # threaded through, mirroring how a real caller reuses one store-owned
    # map across calls (see `saena_claim_evidence.store.
    # InMemoryClaimEvidenceStore`).
    state_2, entry_2 = append_evidence(
        state_1,
        evidence,
        link_statuses=link_statuses,
        now=now,
    )

    # the evidence itself is not re-appended a second time, and
    # publishability is already unchanged from the first append, so NO
    # re-evaluation entry is appended either — ledger length is untouched.
    assert len(state_2) == len(state_1)
    assert entry_2.evidence is not None
    assert entry_1.evidence is not None
    assert entry_2.evidence.evidence_id == entry_1.evidence.evidence_id


def test_experiment_ledger_replayed_register_is_a_no_op_not_a_duplicate_entry() -> None:
    registration = make_experiment_registration()

    state_1, entry_1 = register((), registration)
    assert len(state_1) == 1

    # redelivery of the exact same registration content.
    state_2, entry_2 = register(state_1, registration)

    assert state_2 is state_1
    assert len(state_2) == 1
    assert entry_2.canonical_hash == entry_1.canonical_hash


def test_clickhouse_observation_append_redelivered_twice_inserts_exactly_once() -> None:
    executor = new_fake_clickhouse_executor()
    store = ClickHouseAnalyticsStore(executor)
    row = make_observation_row()

    first = store.append_observation(row)
    second = store.append_observation(row)  # exact redelivery, same idempotency_key

    assert first is True
    assert second is False
    stored = store.get_observations(TENANT_A)
    assert len(stored) == 1
    assert stored[0].idempotency_key == row.idempotency_key


def test_clickhouse_append_with_same_idempotency_key_but_different_id_still_dedups() -> None:
    """The dedup key is `(tenant_id, idempotency_key)` — NOT the row's own
    `id` — matching an at-least-once transport's own redelivery semantics
    (the same logical event, retried, may or may not carry an identical
    internal `id` depending on the producer's own retry implementation;
    this store's contract is defined purely on `idempotency_key`)."""
    executor = new_fake_clickhouse_executor()
    store = ClickHouseAnalyticsStore(executor)
    row_1 = make_observation_row(id="obs-1")
    row_2 = make_observation_row(id="obs-2")  # different `id`, same idempotency_key

    first = store.append_observation(row_1)
    second = store.append_observation(row_2)

    assert first is True
    assert second is False
    assert len(store.get_observations(TENANT_A)) == 1


def test_bus_idempotent_consumer_redelivered_envelope_runs_handler_exactly_once() -> None:
    async def scenario() -> None:
        store = InMemoryIdempotencyStore()
        consumer = IdempotentConsumer(store)
        envelope = make_patch_unit_completed_envelope(tenant_id=TENANT_A, run_id=RUN_ID)
        handled: list[dict[str, object]] = []

        async def handler(env: dict[str, object]) -> None:
            handled.append(env)

        first_ran = await consumer.process(envelope, handler)
        second_ran = await consumer.process(dict(envelope), handler)

        assert first_ran is True
        assert second_ran is False
        assert len(handled) == 1

    run_async(scenario())


def test_outbox_drain_never_republishes_an_already_published_intelligence_event() -> None:
    publisher = InMemoryPublisher()

    async def scenario() -> None:
        outbox = InMemoryOutbox()
        envelope = make_patch_unit_completed_envelope(tenant_id=TENANT_A, run_id=RUN_ID)
        outbox.record(envelope)

        drainer = OutboxDrainer(outbox, publisher)

        first_drain = await drainer.drain_once()
        assert first_drain.published == (envelope["event_id"],)

        second_drain = await drainer.drain_once()
        assert second_drain.published == ()
        assert second_drain.retried_pending == ()

    run_async(scenario())
    assert len(publisher.published) == 1
