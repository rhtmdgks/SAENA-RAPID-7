"""F-9 repoint (w5-20 deliverable 3): the fraud scenario proven against the
REAL integrated `saena_domain.measurement.did` + `b_gate` engine, not the W3
provisional evaluator (`tests/security/measurement_fraud.py`).

## Adopt-and-supersede (see `did.py`'s own module docstring, "F-9 evaluator
mapping" section, for the authoritative statement of this relationship)

The W3 F-9 evaluator (`tests/security/measurement_fraud.py::
evaluate_b_layer_success`) was a provisional, harness-owned checker built
before any measurement module existed, gating on one opaque scalar per
signal: `net_of_control_lift = treatment_raw_delta - control_raw_delta`,
denying success when any signal's lift is `<= 0.0` across `>= 2` independent
signals. `saena_domain.measurement.did.compute_did` **supersedes** that
evaluator's measurement semantics while **adopting** its scalar exactly (its
own docstring's `test_d_fraud_parity_matches_superseded_f9_semantics` pins
this in the unit suite already) — it additionally DECOMPOSES the raw delta
into baseline/post cells, adds a first-class insufficiency taxonomy, and
integrates into the real `b_gate`/`run_measurement` pipeline that actually
GATES a verdict (the W3 evaluator never had an owning service to gate).

This module is THIS suite's own real-engine repoint named in
`test_failure_mode_coverage_matrix.py`'s row 11: the fraud fixture proven
through `run_measurement` end-to-end over REAL Postgres-backed ports, not a
second copy of the superseded scalar evaluator. `tests/security/
measurement_fraud.py` itself is repointed (see that module's own docstring,
updated alongside this file) to delegate its public API to this same real
engine as a thin backward-compatible shim — this module is the INTEGRATION-
level proof that repoint rests on; `tests/security/test_f9_measurement_fraud.py`
(an existing importer of `measurement_fraud.py`'s public names, outside this
patch unit's exclusive paths) continues to exercise the shim directly and
must stay green unmodified.

## The scenario (k3s spec §10 row 9 / Algorithm §11.3 business integrity)

Raw citation count grows in the treatment arm — but the control arm grows by
the SAME amount over the same window (a market-wide trend, not a caused
effect). Net-of-control (DiD) lift is exactly `0`. A report presenting only
the raw treatment movement would look like a real win; the B-gate must never
grant PASS on it.
"""

from __future__ import annotations

import dataclasses

import pytest
from measurement_failure_factories import make_pg_ports
from pipeline_factories import make_fraud_signal, make_happy_path_inputs, make_policies
from saena_domain.measurement.did import DiDPolicy, compute_did
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement

pytestmark = pytest.mark.integration


def test_fraud_did_scalar_is_zero_net_of_control_not_the_raw_movement() -> None:
    """DiD-level (pure, no I/O): the real engine's decomposition of the F-9
    fraud fixture — raw treatment delta is clearly positive (movement DID
    happen), but `net_of_control_lift` is exactly `0.0` once the identical
    control-arm movement is netted out. This is `did.py`'s own documented
    parity claim with the superseded W3 scalar, exercised directly rather
    than only via the unit suite's `test_d_fraud_parity_matches_superseded_
    f9_semantics`."""
    inputs, _registration = make_happy_path_inputs(num_qualifying_layers=1)
    anchor = inputs.server_received_at
    fraud_signal = make_fraud_signal(
        inputs.signals[0].layer, inputs.signals[0].evidence_basis_id, window_anchor=anchor
    )

    result = compute_did(
        (fraud_signal,),
        DiDPolicy(min_repeats=3, effect_threshold=0.5, provenance="test_fixture"),
        window_start=None,
        window_end=None,
    )

    assert len(result.signals) == 1
    signal_did = result.signals[0]
    # Raw treatment movement is real and positive...
    assert signal_did.treatment_raw_delta is not None
    assert signal_did.treatment_raw_delta > 0.0
    # ...but the control arm moved by the identical amount, so the
    # control-adjusted (causal) lift is exactly zero — never silently
    # reported as the raw movement, never a fabricated negative to "punish"
    # it either.
    assert signal_did.net_of_control_lift == 0.0


def test_fraud_signal_through_real_did_and_b_gate_never_passes(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """Pipeline level, over REAL Postgres-backed ports: TWO independent
    fraud-fixture signals (raw-up-both-arms, net-of-control lift == 0 on
    EACH) run through the full `run_measurement` pipeline — the REAL
    production DiD + B-gate code, not a reimplementation. The B-gate must
    NEVER return PASS: a zero net-of-control lift on every signal is exactly
    "no real effect", so the honest outcome is FAIL (a decidable, real
    B-gate verdict of no-qualifying-layers) — never UNDETERMINED-because-we-
    could-not-tell (the DiD scalars ARE well-defined here, just non-positive)
    and never PASS."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    anchor = inputs.server_received_at
    fraud_signals = tuple(
        make_fraud_signal(s.layer, s.evidence_basis_id, window_anchor=anchor)
        for s in inputs.signals
    )
    fraud_inputs = dataclasses.replace(inputs, signals=fraud_signals)
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    outcome = run_measurement(fraud_inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS
    assert outcome.status is OutcomeStatus.FAIL
    assert ReasonCode.NEGATIVE_OR_INCONCLUSIVE_LIFT in outcome.reason_codes
    # k3s §9.2:485 "raw + causal reporting together": the raw view still
    # shows the raw treatment movement happened, even though it never
    # qualified as a causal (control-adjusted) effect.
    assert set(outcome.raw_view) == {s.layer for s in fraud_signals}
    assert outcome.control_adjusted_view == ()
    assert outcome.qualifying_layers == ()


def test_fraud_signal_never_promoted_by_grs_eligibility_over_real_postgres(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """A GRS-eligible policy bundle (the "everything else about this run
    looks fine" case) must NOT be able to promote a zero-net-of-control-lift
    fraud fixture to PASS — GRS eligibility can only ever hold a status BACK
    (`orchestrator._final_status`'s own documented contract), never grant
    one. Proven over real Postgres so the composed pipeline (not a unit-level
    stand-in) is what is asserted against."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    anchor = inputs.server_received_at
    fraud_signals = tuple(
        make_fraud_signal(s.layer, s.evidence_basis_id, window_anchor=anchor)
        for s in inputs.signals
    )
    fraud_inputs = dataclasses.replace(inputs, signals=fraud_signals)
    policies = make_policies(registration, grs_bundle="eligible")
    ports = make_pg_ports(postgres_url)

    outcome = run_measurement(fraud_inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS


def test_fraud_signal_replay_never_upgrades_to_pass(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """Idempotent replay of the SAME fraud-fixture inputs must not "wear
    down" the gate on a second try — the FAIL verdict is stable, and the
    replay resolves to the identical decision (DUPLICATE at the store level,
    never a second, differently-favorable write)."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    anchor = inputs.server_received_at
    fraud_signals = tuple(
        make_fraud_signal(s.layer, s.evidence_basis_id, window_anchor=anchor)
        for s in inputs.signals
    )
    fraud_inputs = dataclasses.replace(inputs, signals=fraud_signals)
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    first = run_measurement(fraud_inputs, ports, policies)
    second = run_measurement(fraud_inputs, ports, policies)

    assert first.status is OutcomeStatus.FAIL
    assert second.status is OutcomeStatus.FAIL
    assert second.status is not OutcomeStatus.PASS
    assert first.canonical_payload() == second.canonical_payload()

    decisions = ports.decision_store.list_decisions(inputs.tenant_id)
    assert len(decisions) == 1
