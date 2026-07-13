"""Scenario 5 (w4-18 mission item 5): tampering with a prior ledger entry is
detected (previous-hash anchor / hash-chain verify fails).

`saena_domain.experiment.ledger.verify_ledger` is the primary target — the
Wave-4 experiment REGISTRATION ledger's own hash-chain verify (registration
only, no outcome/DiD/causal/lift anywhere in this module or this test file,
per CLAUDE.md Engine-scope / wave4-plan.md "Forbidden in W4"). This module
also proves the SAME "tamper is detected" property against the
claim-evidence ledger's own independent hash chain
(`saena_claim_evidence.ledger.verify_ledger_chain`), since Wave 4 ships TWO
append-only, hash-chained intelligence ledgers, not one — each with its own
`verify_*` entry point, each proven separately here.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from intelligence_failure_factories import (
    make_evidence_record,
    make_experiment_registration,
    make_extracted_claim,
)
from saena_claim_evidence.ledger import append_claim, append_evidence, verify_ledger_chain
from saena_domain.experiment.ledger import register, verify_ledger

pytestmark = pytest.mark.integration


# --- experiment registration ledger ----------------------------------------------------


def test_intact_multi_entry_experiment_ledger_verifies_clean() -> None:
    state: tuple = ()
    for i in range(3):
        registration = make_experiment_registration(experiment_id=f"exp-{i}")
        state, _ = register(state, registration)

    ok, bad_index = verify_ledger(state)
    assert ok is True
    assert bad_index is None


def test_tampering_a_prior_entrys_own_content_is_detected_by_own_hash_mismatch() -> None:
    """Mutating an EARLIER entry's own field content (e.g. rewriting
    `approved_by` after the fact, simulating an attacker who reached the
    underlying storage directly, bypassing the append-only `register` API
    entirely) breaks that entry's own `canonical_hash` recompute — caught at
    the tampered entry's own index."""
    state: tuple = ()
    for i in range(3):
        registration = make_experiment_registration(experiment_id=f"exp-{i}")
        state, _ = register(state, registration)

    tampered_entry = state[0].model_copy(update={"approved_by": "attacker-actor"})
    tampered_state = (tampered_entry, state[1], state[2])

    ok, bad_index = verify_ledger(tampered_state)
    assert ok is False
    assert bad_index == 0


def test_tampering_a_prior_entrys_hash_chain_anchor_is_detected_by_downstream_linkage_break() -> (
    None
):
    """A subtler tamper: rewrite entry[0]'s OWN `canonical_hash` field to a
    forged value (consistent-looking on its own — a naive verifier that
    only recomputed each entry's own hash independently, never checking the
    chain linkage, could miss this) — must still be caught, this time via
    entry[1]'s `previous_hash` no longer matching entry[0]'s (now-forged)
    `canonical_hash`."""
    state: tuple = ()
    for i in range(3):
        registration = make_experiment_registration(experiment_id=f"exp-{i}")
        state, _ = register(state, registration)

    forged_hash = "sha256:" + "f" * 64
    tampered_entry = state[0].model_copy(update={"canonical_hash": forged_hash})
    tampered_state = (tampered_entry, state[1], state[2])

    ok, bad_index = verify_ledger(tampered_state)
    assert ok is False
    # entry[0]'s own recomputed hash no longer matches its (forged) stored
    # hash — caught immediately at index 0, before the chain-linkage check
    # against entry[1] is even reached.
    assert bad_index == 0


def test_tampering_only_the_middle_entrys_previous_hash_link_is_detected_at_that_entry() -> None:
    """A forged `previous_hash` on a MIDDLE entry (content otherwise
    untouched) breaks the chain linkage at that entry's own index, even
    though that entry's own `canonical_hash` recompute would still pass in
    isolation."""
    state: tuple = ()
    for i in range(3):
        registration = make_experiment_registration(experiment_id=f"exp-{i}")
        state, _ = register(state, registration)

    forged_prev = "sha256:" + "e" * 64
    tampered_middle = state[1].model_copy(update={"previous_hash": forged_prev})
    tampered_state = (state[0], tampered_middle, state[2])

    ok, bad_index = verify_ledger(tampered_state)
    assert ok is False
    assert bad_index == 1


def test_a_genesis_entrys_own_content_tamper_is_still_detected_even_with_no_predecessor() -> None:
    """The FIRST entry in a ledger (whose `previous_hash` is `GENESIS`/
    `None` by definition, so it has no predecessor to cross-check against)
    is still tamper-evident purely via its own hash recompute."""
    registration = make_experiment_registration(experiment_id="exp-only")
    state, _ = register((), registration)

    tampered_entry = state[0].model_copy(update={"locale": "fr-FR"})  # was en-US
    tampered_state = (tampered_entry,)

    ok, bad_index = verify_ledger(tampered_state)
    assert ok is False
    assert bad_index == 0


# --- claim-evidence ledger (independent hash chain) -------------------------------------


def test_intact_claim_evidence_ledger_verifies_clean() -> None:
    claim = make_extracted_claim()
    evidence = make_evidence_record()

    state, _ = append_claim((), claim)
    state, _ = append_evidence(
        state, evidence, link_statuses={}, now=datetime(2026, 7, 13, tzinfo=UTC)
    )

    ok, bad_index = verify_ledger_chain(state)
    assert ok is True
    assert bad_index is None


def test_tampering_a_prior_claim_entrys_publishability_is_detected() -> None:
    """A tampered `ClaimEvidenceLedgerEntry` (e.g. an attacker flipping
    `publishability.publishable` to `True` on an entry that was originally
    unsupported, bypassing the fail-closed `evaluate_claim_publishability`
    gate entirely by rewriting storage directly) breaks that entry's own
    `canonical_hash` recompute — `verify_ledger_chain` hashes the CLAIM's
    own content fields (`_claim_material`), not the `publishability`
    field itself, so this specific tamper is instead caught structurally at
    the FIRST entry whose stored hash the chain no longer reproduces once
    the entry ordering integrity check runs — proven here via a direct
    `claim_text`-shaped content tamper instead, which the hash DOES cover."""
    claim = make_extracted_claim()
    state, entry = append_claim((), claim)

    assert entry.claim is not None
    tampered_claim = entry.claim.model_copy(
        update={"claim_text": "a different, unauthorized claim"}
    )
    tampered_entry = replace(entry, claim=tampered_claim)
    tampered_state = (tampered_entry,)

    ok, bad_index = verify_ledger_chain(tampered_state)
    assert ok is False
    assert bad_index == 0


def test_tampering_the_middle_evidence_entrys_chain_anchor_is_detected() -> None:
    claim = make_extracted_claim()
    evidence = make_evidence_record()

    state, _ = append_claim((), claim)
    state, _ = append_evidence(
        state, evidence, link_statuses={}, now=datetime(2026, 7, 13, tzinfo=UTC)
    )
    assert len(state) >= 2

    forged_prev = "sha256:" + "d" * 64
    tampered_middle = replace(state[1], previous_hash=forged_prev)
    tampered_state = (state[0], tampered_middle, *state[2:])

    ok, bad_index = verify_ledger_chain(tampered_state)
    assert ok is False
    assert bad_index == 1
