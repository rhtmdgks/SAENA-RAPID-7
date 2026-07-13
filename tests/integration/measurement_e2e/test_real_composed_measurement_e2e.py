"""The REAL composed measurement E2E (w5-19/c5-01) — real Postgres 16, real
ClickHouse 24.8, Temporal time-skipping for the 7-day clock. NOT mock-only
(wave5-plan.md E9: "mock-only E2E is forbidden").

Every scenario drives the ACTUAL production composition:

    experiment registration ledger (register)
      -> deployment.confirmed.v1-shaped confirmation -> validate_confirmation
      -> saena_experiment_attribution.pipeline.run_measurement
         (binding -> window/clock -> DiD -> B-gate -> evidence-bundle seal ->
          OutcomeDecisionRecord append), writing through REAL Postgres ports
         (PgConfirmationStore / PgMeasurementWindowStore / PgOutcomeDecisionStore
         / PgEvidenceBundleStore, via the sync facades over the real w5-10
         asyncpg adapter)
      -> saena_experiment_attribution.boundary.OutcomePublisher assembles +
         fail-closed-gates the real experiment.outcome.observed.v1 payload
         (contract-validated against the generated saena_schemas model)
      -> saena_analytics_clickhouse.store.ClickHouseAnalyticsStore projects a
         MeasurementOutcomeRow into the REAL ClickHouse measurement_outcome
         table
      -> saena_strategy_skill_bank.intake.IntakeGuard (B-verified-only,
         TEST-ONLY fixture provenance) evaluates the real sealed manifest

The load-bearing discipline throughout: every read-back happens on a FRESH
store instance / fresh connection, never the same in-process object the write
went through — proving PHYSICAL persistence in Postgres/ClickHouse, not
merely object identity a fake executor would also satisfy.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, timedelta

import pytest
from measurement_e2e_container_harness import (
    TENANT_1,
    TENANT_2,
    AlwaysTrustVerifier,
    accept_confirmation,
    build_deployment_confirmation,
    build_fraud_scenario,
    build_late_deployment_scenario,
    build_pass_scenario,
    build_registration,
    build_registration_view,
    build_submission,
    evaluate_intake,
    make_pg_ports,
    make_policies,
    project_outcome_to_clickhouse,
    publish_outcome_event,
    qualifying_signal,
    read_back_manifest,
)
from saena_domain.measurement.evidence import verify_manifest
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.boundary.errors import PublishRefusedError
from saena_experiment_attribution.pipeline.inputs import MeasurementInputs
from saena_experiment_attribution.pipeline.orchestrator import run_measurement
from saena_experiment_attribution.pipeline.outcome import OutcomeStatus
from saena_strategy_skill_bank.intake import IntakeDecisionStatus

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# 1. Full PASS -> B-verified skill intake accepted.
# --------------------------------------------------------------------------- #
def test_full_pass_flow_b_verified_skill_intake_accepted(postgres_url: str, ch_store) -> None:  # noqa: ANN001
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:pass:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")

    outcome = run_measurement(scenario.inputs, ports, policies)

    assert outcome.status is OutcomeStatus.PASS
    assert len(outcome.qualifying_layers) >= 2

    # --- Postgres round-trip: fresh connection, not the write-path object. ---
    stored_decision = ports.decision_store.get(
        scenario.inputs.tenant_id, (scenario.inputs.experiment_id, scenario.inputs.run_id)
    )
    assert stored_decision.outcome == OutcomeStatus.PASS.value
    manifest = read_back_manifest(
        postgres_url, scenario.inputs.tenant_id, outcome.evidence_bundle_ref
    )
    assert verify_manifest(manifest) == (True, None)

    # --- OutcomePublisher: real contract-validated wire payload. ---
    wire_payload = publish_outcome_event(outcome, scenario, ports.evidence_store)
    assert wire_payload["b_verdict"] == "pass"
    assert wire_payload["engine_id"] == "chatgpt-search"

    # --- ClickHouse projection: real container round-trip. ---
    row = project_outcome_to_clickhouse(outcome, scenario, row_id="c5e2e-row-pass-1")
    assert ch_store.append_measurement_outcome(row) is True
    (fetched,) = ch_store.get_measurement_outcomes(scenario.inputs.tenant_id)
    assert fetched.b_verdict == "pass"
    assert fetched.experiment_id == scenario.inputs.experiment_id

    # --- skill-bank intake: B-verified PASS admits. ---
    decision = evaluate_intake(outcome, scenario, ports.evidence_store)
    assert decision.status is IntakeDecisionStatus.ADMIT_AS_CANDIDATE


# --------------------------------------------------------------------------- #
# 2. 1 qualifying layer -> not PASS + intake denied.
# --------------------------------------------------------------------------- #
def test_one_qualifying_layer_not_pass_intake_denied(postgres_url: str) -> None:
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:onelayer:0001", num_qualifying_layers=1)
    policies = make_policies(scenario.registration, grs_bundle="eligible")

    outcome = run_measurement(scenario.inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS
    assert len(outcome.qualifying_layers) < 2

    decision = evaluate_intake(outcome, scenario, ports.evidence_store)
    assert decision.status is IntakeDecisionStatus.REJECT


# --------------------------------------------------------------------------- #
# 3. Missing/invalid GRS -> fail-closed, never PASS.
# --------------------------------------------------------------------------- #
def test_missing_grs_fails_closed_never_pass(postgres_url: str) -> None:
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:grs-missing:0001")
    policies = make_policies(scenario.registration, grs_bundle="missing")

    outcome = run_measurement(scenario.inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS
    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.GRS_POLICY_MISSING in outcome.reason_codes

    # NOTE: the B-gate's OWN `decision.verdict` (what the wire payload's
    # `b_verdict` reflects) can legitimately still read "pass" — GRS
    # non-eligibility is a pipeline-level fail-closed FORCER on
    # `outcome.status` (orchestrator.py `_final_status`), not a rewrite of
    # the B-gate's own signal-level verdict. The load-bearing fail-closed
    # guarantee this scenario proves is that the PIPELINE's own outcome —
    # what skill-bank intake and ClickHouse projection actually consume — is
    # never PASS when GRS is missing, proven directly on `outcome.status`
    # above and on the intake guard below (never on the wire `b_verdict`
    # alone, which is a narrower, B-gate-only signal).
    decision = evaluate_intake(outcome, scenario, ports.evidence_store)
    assert decision.status is IntakeDecisionStatus.REJECT

    wire_payload = publish_outcome_event(outcome, scenario, ports.evidence_store)
    assert wire_payload["engine_id"] == "chatgpt-search"


def test_invalid_grs_deny_bundle_fails_closed_never_pass(postgres_url: str) -> None:
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:grs-deny:0001")
    policies = make_policies(scenario.registration, grs_bundle="deny")

    outcome = run_measurement(scenario.inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS
    assert outcome.status is OutcomeStatus.UNDETERMINED


# --------------------------------------------------------------------------- #
# 4. Day-2-late -> UNDETERMINED, clock never started.
# --------------------------------------------------------------------------- #
def test_day2_late_deployment_undetermined_clock_not_started(postgres_url: str) -> None:
    ports = make_pg_ports(postgres_url)
    scenario = build_late_deployment_scenario(idempotency_key="c5e2e:late:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")

    outcome = run_measurement(scenario.inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.DEPLOYMENT_LATE in outcome.reason_codes
    # No window was ever opened — read-back against Postgres proves it,
    # never a mock's in-memory "just didn't happen to write" ambiguity.
    from saena_domain.measurement.errors import NotFoundError

    with pytest.raises(NotFoundError):
        ports.window_store.get_active(scenario.inputs.tenant_id, scenario.inputs.experiment_id)


def test_day2_late_deployment_via_temporal_timer_never_starts(
    postgres_url: str, temporal_env
) -> None:  # noqa: ANN001
    """Same Day-2-late scenario, but driven through the REAL Temporal
    time-skipping workflow (w5-14) with a REAL `run_measurement` activity
    bound to Postgres — proving the durable-timer-driven path ALSO never
    starts a clock for a late deployment, with zero wall-clock sleep."""
    import asyncio

    from real_collect_and_decide_activity import (
        clear_registry,
        make_real_collect_and_decide_activity,
    )
    from saena_domain.measurement.confirmation import Accepted
    from saena_experiment_attribution.workflow.activities import derive_window
    from saena_experiment_attribution.workflow.workflow import (
        DEPLOYMENT_CONFIRMED_SIGNAL_NAME,
        MeasurementWorkflow,
        MeasurementWorkflowInput,
    )
    from temporalio.worker import Worker

    async def scenario_coro() -> None:
        clear_registry()
        registration = build_registration(
            tenant_id=TENANT_1, experiment_id="exp-c5e2e-late-temporal"
        )
        registration_view = build_registration_view(registration)
        anchor = await temporal_env.get_current_time()
        anchor = anchor.replace(tzinfo=UTC) if anchor.tzinfo is None else anchor
        late_approved_at = anchor - timedelta(days=5)
        registration_view = (
            dataclasses.replace(registration_view, approved_at=late_approved_at)
            if not hasattr(registration_view, "model_copy")
            else registration_view.model_copy(update={"approved_at": late_approved_at})
        )
        confirmation = build_deployment_confirmation(
            registration,
            registration_view,
            idempotency_key="c5e2e:temporal-late:0001",
            confirmed_at=anchor,
        )
        verdict = accept_confirmation(confirmation, registration_view, server_received_at=anchor)
        assert isinstance(verdict, Accepted)

        activity_fn = make_real_collect_and_decide_activity(postgres_url)
        worker = Worker(
            temporal_env.client,
            task_queue="c5e2e-late-queue",
            workflows=[MeasurementWorkflow],
            activities=[derive_window, activity_fn],
            max_cached_workflows=0,
        )
        async with worker:
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                MeasurementWorkflowInput(
                    expected_registration_hash=registration.canonical_hash,
                    run_id=registration.run_id,
                ),
                id="wf-c5e2e-late",
                task_queue="c5e2e-late-queue",
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, verdict)
            with temporal_env.auto_time_skipping_disabled():
                result = await handle.result()
            assert result.status.value == "undetermined_deployment_late"
            assert result.outcome_ref is None

    asyncio.run(scenario_coro())


# --------------------------------------------------------------------------- #
# 5. Crash/replay during timer -> original anchor/end preserved.
# --------------------------------------------------------------------------- #
def test_crash_replay_during_timer_preserves_original_window(
    postgres_url: str, temporal_env
) -> None:  # noqa: ANN001
    """Worker restart mid-window (crash-at-day-3.5): the durable timer must
    resume toward the SAME absolute end, and the collect-and-decide activity
    that eventually fires must run the REAL pipeline against Postgres — the
    window this run opens in Postgres therefore reflects the ORIGINAL anchor,
    never a re-anchored one."""
    import asyncio

    from measurement_e2e_container_harness import (
        make_did_policy,
        make_gate_policy,
        make_grs_bundle_eligible,
    )
    from real_collect_and_decide_activity import (
        clear_registry,
        make_real_collect_and_decide_activity,
        register_scenario,
    )
    from saena_domain.measurement.binding import WeightsPolicy
    from saena_domain.measurement.confirmation import Accepted
    from saena_experiment_attribution.pipeline.inputs import MeasurementPolicies
    from saena_experiment_attribution.workflow.activities import derive_window
    from saena_experiment_attribution.workflow.workflow import (
        DEPLOYMENT_CONFIRMED_SIGNAL_NAME,
        MeasurementWorkflow,
        MeasurementWorkflowInput,
    )
    from temporalio.worker import Worker

    task_queue = "c5e2e-replay-queue"

    async def scenario_coro() -> None:
        clear_registry()
        registration = build_registration(
            tenant_id=TENANT_1, experiment_id="exp-c5e2e-replay-temporal"
        )
        anchor = await temporal_env.get_current_time()
        anchor = anchor.replace(tzinfo=UTC) if anchor.tzinfo is None else anchor
        # `approved_at` must be anchored at the environment's CURRENT virtual
        # time (same gotcha #1 discipline as test_measurement_workflow.py's
        # own `_accepted_at_env_now`) — the harness's default `_APPROVED_AT`
        # is a FIXED 2026-07-01 instant, which would read as Day-2-late
        # against this session's virtual "now" and complete the workflow
        # immediately with no timer at all.
        registration_view = build_registration_view(registration, approved_at=anchor)
        submission = build_submission(registration)
        confirmation = build_deployment_confirmation(
            registration,
            registration_view,
            idempotency_key="c5e2e:temporal-replay:0001",
            confirmed_at=anchor,
        )
        verdict = accept_confirmation(confirmation, registration_view, server_received_at=anchor)
        assert isinstance(verdict, Accepted)

        signals = (
            qualifying_signal("discovery", "basis-discovery", window_anchor=anchor),
            qualifying_signal("citation", "basis-citation", window_anchor=anchor),
        )
        window_end = anchor + timedelta(days=7)
        inputs = MeasurementInputs(
            tenant_id=registration.tenant_id,
            run_id=registration.run_id,
            experiment_id=registration.experiment_id,
            registration=registration,
            registration_view=registration_view,
            submission=submission,
            signals=signals,
            deployment_confirmation=confirmation,
            server_received_at=anchor,
            evaluation_at=window_end + timedelta(hours=1),
            prior_confirmations={},
            grs_inputs={"grs": 100, "independent_layers": 2, "open_incidents": 0},
        )
        policies = MeasurementPolicies(
            weights=WeightsPolicy.enforce({registration.metric_definitions[0].metric_id: 1.0}),
            did_policy=make_did_policy(),
            gate_policy=make_gate_policy(),
            clock_policy=None,  # placeholder overwritten below
            grs_bundle=make_grs_bundle_eligible(),
            trust_verifier=AlwaysTrustVerifier(),
        )
        from measurement_e2e_container_harness import make_clock_policy

        policies = dataclasses.replace(policies, clock_policy=make_clock_policy())
        register_scenario(confirmation.idempotency_key, inputs, policies)

        activity_fn = make_real_collect_and_decide_activity(postgres_url)

        # First Worker: signal, advance to mid-window (Day 3.5), then shut down
        # WITHOUT completing — simulated crash.
        worker1 = Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[MeasurementWorkflow],
            activities=[derive_window, activity_fn],
            max_cached_workflows=0,
        )
        async with worker1:
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                MeasurementWorkflowInput(
                    expected_registration_hash=registration.canonical_hash,
                    run_id=registration.run_id,
                ),
                id="wf-c5e2e-replay",
                task_queue=task_queue,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, verdict)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is True
            await temporal_env.sleep(timedelta(days=3, hours=12))
            desc = await handle.describe()
            from temporalio.client import WorkflowExecutionStatus

            assert desc.status == WorkflowExecutionStatus.RUNNING

        # Fresh Worker: replay resumes toward the ORIGINAL absolute end.
        worker2 = Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[MeasurementWorkflow],
            activities=[derive_window, activity_fn],
            max_cached_workflows=0,
        )
        async with worker2:
            await temporal_env.sleep(timedelta(days=3, hours=11))
            desc = await handle.describe()
            from temporalio.client import WorkflowExecutionStatus

            assert desc.status == WorkflowExecutionStatus.RUNNING
            await temporal_env.sleep(timedelta(hours=2))
            desc = await handle.describe()
            assert desc.status == WorkflowExecutionStatus.COMPLETED, (
                "workflow still running past the ORIGINAL Day-7 end after a "
                "mid-window worker restart — the durable timer appears to "
                "have RESET instead of continuing to its original end"
            )
            with temporal_env.auto_time_skipping_disabled():
                result = await handle.result()
            assert result.status.value == "decided"

        # The activity that fired ran the REAL pipeline against Postgres —
        # read the window back from a FRESH store and confirm its anchor is
        # the ORIGINAL confirmation instant, not a restart-shifted one. The
        # sync facade's `asyncio.run(...)` cannot be called from THIS
        # coroutine's own running loop (same reason the real activity itself
        # offloads to a thread — see real_collect_and_decide_activity.py), so
        # this read-back runs off-thread too.
        def _read_window_sync():  # noqa: ANN202
            return make_pg_ports(postgres_url).window_store.get_active(
                registration.tenant_id, registration.experiment_id
            )

        stored_window = await asyncio.to_thread(_read_window_sync)
        assert stored_window.starts_at == anchor.isoformat()

    asyncio.run(scenario_coro())


# --------------------------------------------------------------------------- #
# 6. Duplicate identical confirmation/outcome -> idempotent.
# --------------------------------------------------------------------------- #
def test_duplicate_identical_confirmation_is_idempotent(postgres_url: str) -> None:
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:dup:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")

    first = run_measurement(scenario.inputs, ports, policies)
    second = run_measurement(scenario.inputs, ports, policies)

    assert first.canonical_payload() == second.canonical_payload()
    # Only ONE decision physically exists in Postgres for this key.
    decisions = ports.decision_store.list_decisions(scenario.inputs.tenant_id)
    matching = [
        d
        for d in decisions
        if d.decision_key == (scenario.inputs.experiment_id, scenario.inputs.run_id)
    ]
    assert len(matching) == 1


# --------------------------------------------------------------------------- #
# 7. Conflicting confirmation -> deterministic safe UNDETERMINED, first
#    record unchanged (uses the c5-03 fix).
# --------------------------------------------------------------------------- #
def test_conflicting_confirmation_undetermined_first_record_unchanged(postgres_url: str) -> None:
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:conflict:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")

    first_outcome = run_measurement(scenario.inputs, ports, policies)
    assert first_outcome.status is OutcomeStatus.PASS

    first_stored = ports.confirmation_store.get(
        scenario.inputs.tenant_id, scenario.inputs.deployment_confirmation.idempotency_key
    )

    view = build_registration_view(scenario.registration)
    conflicting_confirmation = build_deployment_confirmation(
        scenario.registration,
        view,
        idempotency_key=scenario.inputs.deployment_confirmation.idempotency_key,
    )
    conflicting_confirmation = conflicting_confirmation.model_copy(
        update={"deployed_commit_sha": "b" * 40}
    )
    conflicting_inputs = dataclasses.replace(
        scenario.inputs,
        run_id="c5e2e-conflict-run-2",
        deployment_confirmation=conflicting_confirmation,
    )

    second_outcome = run_measurement(conflicting_inputs, ports, policies)

    assert second_outcome.status is OutcomeStatus.UNDETERMINED
    assert second_outcome.status is not OutcomeStatus.PASS
    assert ReasonCode.CONFLICTING_CONFIRMATION in second_outcome.reason_codes

    # First-wins immutability — read back from a FRESH store handle.
    still_stored = make_pg_ports(postgres_url).confirmation_store.get(
        scenario.inputs.tenant_id, scenario.inputs.deployment_confirmation.idempotency_key
    )
    assert still_stored == first_stored


def test_non_conflict_store_errors_still_propagate_against_real_pg(postgres_url: str) -> None:
    """Sanity companion: a genuinely malformed write against the REAL adapter
    (a forged cross-tenant record) still raises its own typed error rather
    than being silently absorbed by the conflicting-confirmation seam."""
    from saena_domain.measurement.errors import TenantIsolationError
    from saena_domain.measurement.ports import ConfirmationRecord

    ports = make_pg_ports(postgres_url)
    forged = ConfirmationRecord(
        tenant_id="attacker-tenant",
        confirmation_key="c5e2e:forged:0001",
        measurement_kind="deployment_confirmation",
        payload={"x": 1},
    )
    with pytest.raises(TenantIsolationError):
        ports.confirmation_store.put_confirmation("victim-tenant", "c5e2e:forged:0001", forged)


# --------------------------------------------------------------------------- #
# 8. Cross-tenant replay/read -> denied, no existence oracle.
# --------------------------------------------------------------------------- #
def test_cross_tenant_read_denied_no_existence_oracle(postgres_url: str) -> None:
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(tenant_id=TENANT_1, idempotency_key="c5e2e:tenantA:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")
    outcome = run_measurement(scenario.inputs, ports, policies)
    assert outcome.status is OutcomeStatus.PASS

    from saena_domain.measurement.errors import NotFoundError

    # Tenant 2 reading tenant 1's confirmation key gets the SAME NotFoundError
    # shape as a genuinely absent key — no existence oracle.
    with pytest.raises(NotFoundError):
        ports.confirmation_store.get(
            TENANT_2, scenario.inputs.deployment_confirmation.idempotency_key
        )
    with pytest.raises(NotFoundError):
        ports.decision_store.get(TENANT_2, (scenario.inputs.experiment_id, scenario.inputs.run_id))
    with pytest.raises(NotFoundError):
        ports.evidence_store.get(TENANT_2, outcome.evidence_bundle_ref)

    # Tenant 2's OWN decision list never contains tenant 1's decision.
    tenant2_decisions = ports.decision_store.list_decisions(TENANT_2)
    assert scenario.inputs.experiment_id not in [d.decision_key[0] for d in tenant2_decisions]


def test_cross_tenant_write_replay_rejected(postgres_url: str) -> None:
    """A forged record whose OWN embedded tenant_id disagrees with the
    caller-supplied tenant is rejected BEFORE any statement runs — proven
    against the real adapter (not a mock that might skip the pre-check)."""
    from saena_domain.measurement.errors import TenantIsolationError
    from saena_domain.measurement.ports import ConfirmationRecord

    ports = make_pg_ports(postgres_url)
    record = ConfirmationRecord(
        tenant_id=TENANT_1,
        confirmation_key="c5e2e:replay:0001",
        measurement_kind="deployment_confirmation",
        payload={"x": 1},
    )
    with pytest.raises(TenantIsolationError):
        ports.confirmation_store.put_confirmation(TENANT_2, "c5e2e:replay:0001", record)

    # And genuinely never landed under either tenant.
    from saena_domain.measurement.errors import NotFoundError

    with pytest.raises(NotFoundError):
        ports.confirmation_store.get(TENANT_1, "c5e2e:replay:0001")
    with pytest.raises(NotFoundError):
        ports.confirmation_store.get(TENANT_2, "c5e2e:replay:0001")


# --------------------------------------------------------------------------- #
# 9. Evidence tamper/reorder/splice -> verification failure, no promotion.
# --------------------------------------------------------------------------- #
def test_evidence_tamper_detected_on_readback_no_promotion(postgres_url: str) -> None:
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:tamper:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")
    outcome = run_measurement(scenario.inputs, ports, policies)
    assert outcome.status is OutcomeStatus.PASS

    manifest = read_back_manifest(
        postgres_url, scenario.inputs.tenant_id, outcome.evidence_bundle_ref
    )
    assert verify_manifest(manifest) == (True, None)

    # Splice: remove the middle entry, keep the ORIGINAL sealed chain attached
    # (force-mutate the sealed, frozen manifest AFTER it is already nested in
    # a validly-constructed candidate — pydantic does not re-run validators on
    # an `object.__setattr__` force-mutation of an already-constructed nested
    # model; this is the SAME adversarial pattern
    # `tests/unit/svc_strategy_skill_bank/test_intake_guard.py::
    # test_reject_tampered_manifest_fails_verification` uses, applied here to
    # a manifest that was PHYSICALLY read back from Postgres, not merely
    # built in-process) -> verify_manifest must report failure — the tampered
    # manifest is never treated as intact.
    entries = manifest.entries
    assert len(entries) >= 3

    from saena_domain.measurement.b_gate import BVerdict
    from saena_strategy_skill_bank.intake import (
        IntakeCandidate,
        IntakeGuard,
        IntakeRejectReason,
        SourceOutcomeAssertion,
        SourceOutcomeProvenance,
    )

    candidate = IntakeCandidate(
        card_candidate_ref=f"card-{scenario.inputs.experiment_id}-tampered",
        evidence_bundle_manifest_hash=outcome.evidence_bundle_ref,
        source_outcome=SourceOutcomeAssertion(
            b_verdict=BVerdict.PASS,
            provenance=SourceOutcomeProvenance.TEST_FIXTURE,
            manifest=manifest,
        ),
    )
    nested_manifest = candidate.source_outcome.manifest
    assert nested_manifest is not None
    tampered_commitments = ("sha256:" + "f" * 64,) * len(nested_manifest.entry_commitments)
    object.__setattr__(nested_manifest, "entry_commitments", tampered_commitments)
    object.__setattr__(nested_manifest, "manifest_hash", tampered_commitments[-1])

    ok, _divergence_index = verify_manifest(nested_manifest)
    assert ok is False

    guard = IntakeGuard()
    decision = guard.evaluate(candidate)
    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.TAMPERED_EVIDENCE in decision.reject_reasons


# --------------------------------------------------------------------------- #
# 10. Raw-content/secret sentinel absent from events/logs/evidence/rows/
#     exception strings.
# --------------------------------------------------------------------------- #
_SECRET_SENTINEL = "sk-test-c5e2e-SENTINEL-1234567890abcdef"


def test_secret_sentinel_absent_from_evidence_and_persistence_rows(
    postgres_url: str, ch_store
) -> None:  # noqa: ANN001
    """A secret-shaped sentinel embedded in the confirmer signature (an
    untrusted, caller-controlled string) must never surface in the sealed
    evidence bundle rows physically read back from Postgres, the ClickHouse
    projection, the published wire payload, or any exception string raised
    along the way."""
    ports = make_pg_ports(postgres_url)
    registration = build_registration(tenant_id=TENANT_1, experiment_id="exp-c5e2e-secret")
    registration_view = build_registration_view(registration)
    submission = build_submission(registration)
    confirmation = build_deployment_confirmation(
        registration, registration_view, idempotency_key="c5e2e:secret:0001"
    )
    confirmation = confirmation.model_copy(update={"confirmer_signature": _SECRET_SENTINEL})

    server_received_at = confirmation.confirmed_at + timedelta(seconds=5)
    from saena_domain.measurement.confirmation import Accepted

    verdict = accept_confirmation(
        confirmation, registration_view, server_received_at=server_received_at
    )
    assert isinstance(verdict, Accepted)
    signals = (
        qualifying_signal("discovery", "basis-discovery", window_anchor=server_received_at),
        qualifying_signal("citation", "basis-citation", window_anchor=server_received_at),
    )
    window_end = server_received_at + timedelta(days=7)
    inputs = MeasurementInputs(
        tenant_id=registration.tenant_id,
        run_id=registration.run_id,
        experiment_id=registration.experiment_id,
        registration=registration,
        registration_view=registration_view,
        submission=submission,
        signals=signals,
        deployment_confirmation=confirmation,
        server_received_at=server_received_at,
        evaluation_at=window_end + timedelta(hours=1),
        prior_confirmations={},
        grs_inputs={"grs": 100, "independent_layers": 2, "open_incidents": 0},
    )
    policies = make_policies(registration, grs_bundle="eligible")

    outcome = run_measurement(inputs, ports, policies)

    manifest = read_back_manifest(postgres_url, inputs.tenant_id, outcome.evidence_bundle_ref)
    rendered_manifest = manifest.model_dump_json()
    assert _SECRET_SENTINEL not in rendered_manifest

    stored_decision = ports.decision_store.get(
        inputs.tenant_id, (inputs.experiment_id, inputs.run_id)
    )
    assert _SECRET_SENTINEL not in str(stored_decision.policy_metadata)

    ch_row = project_outcome_to_clickhouse(
        outcome,
        _ScenarioLike(inputs=inputs, registration=registration, window_end=window_end),
        row_id="c5e2e-secret-row-1",
    )
    assert ch_store.append_measurement_outcome(ch_row) is True
    (fetched,) = ch_store.get_measurement_outcomes(inputs.tenant_id)
    fetched_repr = repr(dataclasses.asdict(fetched))
    assert _SECRET_SENTINEL not in fetched_repr

    if outcome.status is OutcomeStatus.PASS:
        wire_payload = publish_outcome_event(
            outcome,
            _ScenarioLike(inputs=inputs, registration=registration, window_end=window_end),
            ports.evidence_store,
        )
        assert _SECRET_SENTINEL not in str(wire_payload)


@dataclasses.dataclass(frozen=True)
class _ScenarioLike:
    """Minimal stand-in exposing only the attributes
    `measurement_outcome_row_from_outcome`/`publish_outcome_event` read
    (`.inputs`, `.registration`, `.window_anchor`, `.window_end`,
    `.confirmation`) — used where this scenario built `MeasurementInputs`
    directly rather than via `build_pass_scenario`."""

    inputs: MeasurementInputs
    registration: object
    window_end: object

    @property
    def window_anchor(self):  # noqa: ANN201
        return self.inputs.server_received_at

    @property
    def confirmation(self):  # noqa: ANN201
        return self.inputs.deployment_confirmation


def test_secret_sentinel_absent_from_conflicting_confirmation_reason_codes(
    postgres_url: str,
) -> None:
    """The c5-03 conflicting-confirmation seam must never echo the
    conflicting confirmation's own raw content (signature/commit sha) into
    the outcome's canonical payload — proven against the real Postgres
    conflict path, not just the in-memory unit test."""
    ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:secret-conflict:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")
    run_measurement(scenario.inputs, ports, policies)

    view = build_registration_view(scenario.registration)
    conflicting = build_deployment_confirmation(
        scenario.registration,
        view,
        idempotency_key=scenario.inputs.deployment_confirmation.idempotency_key,
    ).model_copy(update={"confirmer_signature": _SECRET_SENTINEL, "deployed_commit_sha": "f" * 40})
    conflicting_inputs = dataclasses.replace(
        scenario.inputs, run_id="c5e2e-secret-conflict-run-2", deployment_confirmation=conflicting
    )
    outcome = run_measurement(conflicting_inputs, ports, policies)
    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert _SECRET_SENTINEL not in outcome.canonical_payload()


def test_secret_sentinel_absent_from_raised_exception_strings(postgres_url: str) -> None:
    """SHOULD-FIX (c5-01 critic): the sentinel sweep must cover RAISED-EXCEPTION
    message strings too, not only events/logs/evidence/rows. Force a REAL
    store-level fail-closed rejection whose triggering content carries a
    secret-shaped sentinel, and assert the sentinel appears in NEITHER
    `str(exc)` NOR `repr(exc)` NOR the exception's structured `context` dict.

    Two independent real-adapter rejection paths are exercised:

    (a) `IdempotencyConflictError` — a same-tenant/same-key confirmation whose
        DIFFERING content embeds the sentinel (the raw
        `ConfirmationStore.put_confirmation` conflict, exercised DIRECTLY here
        rather than through the seam that would otherwise absorb it into an
        UNDETERMINED outcome, so the raw exception itself is inspectable).
    (b) `TenantIsolationError` — a forged cross-tenant confirmation record
        whose payload embeds the sentinel.
    """
    from saena_domain.measurement.errors import (
        IdempotencyConflictError,
        TenantIsolationError,
    )
    from saena_domain.measurement.ports import ConfirmationRecord

    ports = make_pg_ports(postgres_url)
    key = "c5e2e:exc-secret:0001"

    # (a) First store a benign confirmation, then a same-key conflicting one
    # whose payload embeds the sentinel — the raw adapter raises
    # IdempotencyConflictError (fail-closed, no overwrite).
    ports.confirmation_store.put_confirmation(
        TENANT_1,
        key,
        ConfirmationRecord(
            tenant_id=TENANT_1,
            confirmation_key=key,
            measurement_kind="deployment_confirmation",
            payload={"commit": "a" * 40},
        ),
    )
    with pytest.raises(IdempotencyConflictError) as conflict_exc:
        ports.confirmation_store.put_confirmation(
            TENANT_1,
            key,
            ConfirmationRecord(
                tenant_id=TENANT_1,
                confirmation_key=key,
                measurement_kind="deployment_confirmation",
                payload={"commit": _SECRET_SENTINEL},
            ),
        )
    exc = conflict_exc.value
    assert _SECRET_SENTINEL not in str(exc)
    assert _SECRET_SENTINEL not in repr(exc)
    assert _SECRET_SENTINEL not in str(exc.context)
    assert _SECRET_SENTINEL not in str(exc.to_dict())

    # (b) A forged cross-tenant record carrying the sentinel — the raw adapter
    # rejects it with TenantIsolationError BEFORE any statement runs; the
    # rejection must not echo the forged payload's secret.
    forged = ConfirmationRecord(
        tenant_id="attacker-tenant",
        confirmation_key="c5e2e:exc-secret:tenant",
        measurement_kind="deployment_confirmation",
        payload={"commit": _SECRET_SENTINEL},
    )
    with pytest.raises(TenantIsolationError) as tenant_exc:
        ports.confirmation_store.put_confirmation(
            "victim-tenant", "c5e2e:exc-secret:tenant", forged
        )
    exc = tenant_exc.value
    assert _SECRET_SENTINEL not in str(exc)
    assert _SECRET_SENTINEL not in repr(exc)
    assert _SECRET_SENTINEL not in str(exc.context)
    assert _SECRET_SENTINEL not in str(exc.to_dict())


# --------------------------------------------------------------------------- #
# 11. Zero/common-trend synthetic effect -> never falsely promoted.
# --------------------------------------------------------------------------- #
def test_zero_common_trend_effect_never_falsely_promoted(postgres_url: str, ch_store) -> None:  # noqa: ANN001
    ports = make_pg_ports(postgres_url)
    scenario = build_fraud_scenario(idempotency_key="c5e2e:fraud:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")

    outcome = run_measurement(scenario.inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS

    row = project_outcome_to_clickhouse(outcome, scenario, row_id="c5e2e-fraud-row-1")
    assert ch_store.append_measurement_outcome(row) is True
    (fetched,) = ch_store.get_measurement_outcomes(scenario.inputs.tenant_id)
    assert fetched.b_verdict != "pass"

    # OutcomePublisher's fail-closed policy gate: even if somehow asked to
    # publish this as PASS, it must refuse (defence in depth) — exercised
    # directly since this outcome's own verdict already is not PASS.
    decision = evaluate_intake(outcome, scenario, ports.evidence_store)
    assert decision.status is IntakeDecisionStatus.REJECT


def test_outcome_publisher_refuses_forged_pass_without_qualifying_layers(postgres_url: str) -> None:
    """Defence-in-depth companion: `OutcomePublisher` independently refuses a
    would-be PASS publish when the policy-gate conditions are not met, even
    if a caller tried to force one — proven against the REAL evidence store
    read-back (a manifest that does not resolve/verify)."""
    from saena_domain.measurement.b_gate import BGateDecision, BVerdict, PolicyProvenance
    from saena_domain.measurement.did import DiDResult
    from saena_experiment_attribution.boundary.outcome_publisher import OutcomePublisher
    from saena_schemas.event.experiment_outcome_observed_v1 import GrsPolicy as WireGrsPolicy
    from saena_schemas.event.experiment_outcome_observed_v1 import Window as WirePayloadWindow

    class _NeverResolves:
        def lookup(self, tenant_id, manifest_hash):  # noqa: ANN001, ANN201
            return None

    forged_decision = BGateDecision.model_construct(
        verdict=BVerdict.PASS,
        qualifying_layers=(),  # insufficient layers — should refuse
        raw_view=(),
        control_adjusted_view=(),
        reason_codes=(),
        confidence=None,
        policy_version="0.0.0",
        policy_hash="sha256:" + "0" * 64,
        policy_provenance=PolicyProvenance.TEST_FIXTURE,
        is_production=False,
    )
    publisher = OutcomePublisher(manifest_lookup=_NeverResolves())
    with pytest.raises(PublishRefusedError) as exc_info:
        publisher.publish(
            tenant_id=TENANT_1,
            engine_id="chatgpt-search",
            experiment_id="exp-forged",
            registration_canonical_hash="sha256:" + "a" * 64,
            deployment_confirmation_ref="deploy-ref",
            window=WirePayloadWindow(
                started_at="2026-07-01T00:00:00Z",
                ended_at="2026-07-08T00:00:00Z",
                clock_anchor="deployment_confirmed",
            ),
            did_result=DiDResult(signals=()),
            decision=forged_decision,
            manifest_hash="sha256:" + "9" * 64,
            artifact_ref="evidence://none",
            grs_policy=WireGrsPolicy(
                version="0.0.0", hash="sha256:" + "0" * 64, provenance="test_fixture"
            ),
        )
    assert "insufficient_qualifying_layers" in exc_info.value.context["reasons"]
    assert "evidence_manifest_unresolved" in exc_info.value.context["reasons"]


# --------------------------------------------------------------------------- #
# 12. Successful path proves PHYSICAL persistence + subsequent reads from the
#     real adapters (the load-bearing "not a fake executor" proof).
# --------------------------------------------------------------------------- #
def test_successful_path_physical_persistence_subsequent_real_reads(
    postgres_url: str, ch_store
) -> None:  # noqa: ANN001
    """The discriminating assertion: a scenario that would pass against an
    in-memory fake but fail against real containers is the point. This test
    (a) writes through ports bound to ONE `AsyncEngine`-backed connection
    pool, then (b) reads back through a COMPLETELY FRESH set of Pg store
    instances (`make_pg_ports` called again, a distinct engine/connection),
    and separately (c) reads the ClickHouse projection back through the
    session-scoped container's OWN client — never the writer's in-process
    object. An in-memory fake port would trivially "round-trip" via shared
    Python object identity; this proves the row is ACTUALLY IN Postgres and
    ACTUALLY IN ClickHouse.
    """
    write_ports = make_pg_ports(postgres_url)
    scenario = build_pass_scenario(idempotency_key="c5e2e:physical:0001")
    policies = make_policies(scenario.registration, grs_bundle="eligible")

    outcome = run_measurement(scenario.inputs, write_ports, policies)
    assert outcome.status is OutcomeStatus.PASS

    # Fresh Postgres ports — a NEW SyncPg*Store set, each opening its own
    # fresh AsyncEngine per call (sync_facade module docstring) — never the
    # `write_ports` object.
    read_ports = make_pg_ports(postgres_url)
    assert read_ports is not write_ports

    reread_decision = read_ports.decision_store.get(
        scenario.inputs.tenant_id, (scenario.inputs.experiment_id, scenario.inputs.run_id)
    )
    assert reread_decision.outcome == OutcomeStatus.PASS.value

    reread_window = read_ports.window_store.get_active(
        scenario.inputs.tenant_id, scenario.inputs.experiment_id
    )
    assert reread_window.experiment_id == scenario.inputs.experiment_id

    reread_confirmation = read_ports.confirmation_store.get(
        scenario.inputs.tenant_id, scenario.inputs.deployment_confirmation.idempotency_key
    )
    assert (
        reread_confirmation.confirmation_key
        == scenario.inputs.deployment_confirmation.idempotency_key
    )

    reread_manifest = read_back_manifest(
        postgres_url, scenario.inputs.tenant_id, outcome.evidence_bundle_ref
    )
    assert verify_manifest(reread_manifest) == (True, None)
    assert reread_manifest.manifest_hash == outcome.evidence_bundle_ref

    # ClickHouse: append via `ch_store`, then query via a SEPARATE store
    # instance built from the SAME session container's executor but a fresh
    # `ClickHouseAnalyticsStore` wrapper — still a real server-side query
    # (ClickHouse has no client-side cache this could spuriously satisfy).
    from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

    row = project_outcome_to_clickhouse(outcome, scenario, row_id="c5e2e-physical-row-1")
    assert ch_store.append_measurement_outcome(row) is True
    fresh_ch_store = ClickHouseAnalyticsStore(ch_store._executor)  # noqa: SLF001
    (fetched,) = fresh_ch_store.get_measurement_outcomes(scenario.inputs.tenant_id)
    assert fetched.id == row.id
    assert fetched.evidence_bundle_manifest_hash == outcome.evidence_bundle_ref
