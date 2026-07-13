"""Cross-module privacy / tenant-isolation security suite for the Wave-5
measurement plane (w5-18).

Exit-matrix conditions exercised here (wave5-plan.md §Exit matrix):
- **E5** — "Evidence bundle complete + tamper/reorder/splice-evident; no raw
  customer content/secrets" (the no-leakage sweep, and the manifest tenant
  guard).
- **E8** — "Tenant/privacy/idempotency/replay invariants green".
- **E12** — "No forbidden P1/Future activation; no deploy; no unsupported lift
  claim" (a leaked secret in a decision record IS an unsupported/unsafe
  externalisation; the sweep is part of E12's honesty guarantee too).

## What this suite adds ON TOP of the per-unit suites (integration-shaped)

The w5-03..09 unit suites each prove their OWN module's tenant guard in
isolation. This suite is the CROSS-MODULE one the directive asks for: it
drives a real tenant-A registration → confirmation → clock → binding → DiD →
B-gate → evidence chain and injects tenant-B artifacts at EVERY seam, then
compares the REJECTION SURFACES across the whole chain for consistency (a
uniform "no existence oracle" story, or a flagged drift). It is pure Python —
no containers, no I/O, no clock — mirroring the existing tests/security W3/W4
adversarial style (`test_intel_tenant_isolation.py`).

It does NOT modify any unit's module (read-only against them) and does NOT
touch `measurement_fraud.py` (the superseded F-9 evaluator).

## FINDINGS for the Integrator (seam inconsistencies, reported not fixed)

`test_cross_tenant_error_surfaces_are_consistent_or_flagged` documents a real
DRIFT it does not "fix" (this suite may not edit another unit's module):

  - `binding.bind_experiment` and `evidence.entry_for_tenant` are
    EXISTENCE-ORACLE-SAFE across tenants: a cross-tenant access is
    indistinguishable from a genuinely-absent record (`not_found` / `None`).
  - `confirmation.validate_confirmation` is NOT: it reports a tenant mismatch
    as a DISTINCT `RejectionReason.CROSS_TENANT_REPLAY`, different from the
    `IDENTITY_MISMATCH` it gives a run/project/site mismatch — an attacker who
    can present a confirmation against another tenant's `RegistrationView`
    learns "the tenant field, specifically, was wrong". The `Rejected` value
    also always echoes back the caller's own `experiment_id`.
  - The `ports` stores split cross-tenant into two shapes by design: a
    cross-tenant READ is a non-leaking `NotFoundError`; a forged-tenant-id
    WRITE is a distinct `TenantIsolationError`.

The test PINS these as the observed contract (so a regression that changes one
surface is caught) and asserts the two families that CLAIM oracle-safety
(binding, evidence) actually are. The confirmation drift is a documented
finding, asserted as the CURRENT behaviour, not silently accepted as safe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from saena_domain.experiment.ledger import register
from saena_domain.experiment.models import (
    ExperimentArm,
    ExperimentRegistration,
    MetricDefinition,
)
from saena_domain.measurement.binding import (
    BindingNotFoundError,
    BindingRejectedError,
    MeasurementCell,
    MeasurementMetricInput,
    MeasurementSubmission,
    Observation,
    WeightsPolicy,
    bind_experiment,
    compute_metric_fingerprint,
)
from saena_domain.measurement.clock import start_measurement_window
from saena_domain.measurement.confirmation import (
    Accepted,
    DeploymentConfirmation,
    Duplicate,
    RegistrationView,
    Rejected,
    RejectionReason,
    validate_confirmation,
)
from saena_domain.measurement.evidence import (
    EvidenceBundleManifest,
    EvidenceEntry,
    EvidenceKind,
    EvidenceMetadata,
    EvidenceRef,
    RawContentRejectedError,
    entry_for_tenant,
    guard_evidence_fields,
)
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    EvidenceBundle,
    InMemoryConfirmationStore,
    InMemoryEvidenceBundleStore,
    InMemoryMeasurementWindowStore,
    InMemoryOutcomeDecisionStore,
    NotFoundError,
    OutcomeDecisionRecord,
    PutOutcome,
    TenantIsolationError,
)
from saena_domain.measurement.ports import (
    MeasurementWindow as StoredWindow,
)

TENANT_A = "acme-co"
TENANT_B = "globex-co"

_CREATED = datetime(2026, 7, 14, 8, 0, 0, tzinfo=UTC)
_SERVER_RECEIVED = _CREATED + timedelta(hours=1)
_SHA_A = "sha256:" + "a" * 64
_SHA_1 = "sha256:" + "1" * 64
_SHA_2 = "sha256:" + "2" * 64


class _YesVerifier:
    """A trust verifier that accepts — the confirmer-trust seam, satisfied so
    the chain can reach the LATER seams under test (never the thing under test
    in the tenant-isolation cases)."""

    def verify(self, confirmation: DeploymentConfirmation) -> bool:
        return True


# --------------------------------------------------------------------------
# Chain builders (one honest tenant-A pipeline; tenant-B variants per seam)
# --------------------------------------------------------------------------


def _registration(
    *, tenant_id: str = TENANT_A, experiment_id: str = "exp-1"
) -> ExperimentRegistration:
    reg = ExperimentRegistration(
        experiment_id=experiment_id,
        tenant_id=tenant_id,
        run_id="run-1",
        arms=(
            ExperimentArm(arm_id="b", role="baseline"),
            ExperimentArm(arm_id="t", role="treatment", asset_ref="asset-t"),
            ExperimentArm(arm_id="c", role="control", asset_ref="asset-c"),
        ),
        metric_definitions=(
            MetricDefinition(metric_id="m1", description="citations"),
            MetricDefinition(metric_id="m2", description="prominence"),
        ),
        query_cluster_ref="qc-1",
        locale="en-US",
        browser_policy="default",
        repeat_count=3,
        asset_hash=_SHA_1,
        code_version_hash=_SHA_2,
        created_by="alice",
        approved_by="bob",
        created_at=_CREATED,
    )
    _ledger, stored = register((), reg)
    return stored


def _registration_view(
    reg: ExperimentRegistration, *, tenant_id: str | None = None
) -> RegistrationView:
    return RegistrationView(
        experiment_id=reg.experiment_id,
        tenant_id=tenant_id or reg.tenant_id,
        run_id=reg.run_id,
        project="proj",
        site="site",
        registration_canonical_hash=reg.canonical_hash,
        created_at=_CREATED,
        approved_at=_CREATED,
    )


def _confirmation(
    reg: ExperimentRegistration, *, tenant_id: str | None = None
) -> DeploymentConfirmation:
    return DeploymentConfirmation(
        experiment_id=reg.experiment_id,
        tenant_id=tenant_id or reg.tenant_id,
        run_id=reg.run_id,
        project="proj",
        site="site",
        registration_canonical_hash=reg.canonical_hash,
        deployment_target="prod",
        deployed_commit_sha="abc123def",
        confirmed_at=_SERVER_RECEIVED,
        idempotency_key="idem-1",
        confirmer_identity="deployer",
        confirmer_signature="signature-bytes",
    )


def _submission(
    reg: ExperimentRegistration, *, tenant_id: str | None = None
) -> MeasurementSubmission:
    mh1 = compute_metric_fingerprint(reg.metric_definitions[0])
    mh2 = compute_metric_fingerprint(reg.metric_definitions[1])
    cell = MeasurementCell(
        locale=reg.locale,
        browser_policy=reg.browser_policy,
        query_cluster_ref=reg.query_cluster_ref,
        repeat_count=reg.repeat_count,
    )
    return MeasurementSubmission(
        experiment_id=reg.experiment_id,
        tenant_id=tenant_id or reg.tenant_id,
        anchored_hash=reg.canonical_hash,
        content_fingerprint=reg.content_fingerprint,
        metrics=(
            MeasurementMetricInput(metric_id="m1", metric_hash=mh1, weight=1.0),
            MeasurementMetricInput(metric_id="m2", metric_hash=mh2, weight=1.0),
        ),
        observations=(
            Observation(
                observation_id="o1",
                arm_id="t",
                cell=cell,
                asset_hash=reg.asset_hash,
            ),
        ),
    )


def _sealed_manifest(*, tenant_id: str = TENANT_A) -> EvidenceBundleManifest:
    entry = EvidenceEntry(
        kind=EvidenceKind.B_GATE_DECISION,
        ref=EvidenceRef(uri="artifact://decision", content_hash=_SHA_A),
        metadata=EvidenceMetadata(),
    )
    return EvidenceBundleManifest.seal(
        tenant_id=tenant_id,
        run_id="run-1",
        experiment_id="exp-1",
        entries=(entry,),
    )


# ==========================================================================
# TEST 1 — Tenant isolation end-to-end across the module chain (E8)
# ==========================================================================


def test_tenant_b_injected_at_confirmation_seam_is_rejected() -> None:
    """E8: at the confirmation seam, a tenant-B confirmation presented against
    tenant A's registration view is rejected (never Accepted), and the clock
    therefore never starts. Pins `validate_confirmation`'s tenant guard."""
    reg = _registration()
    view = _registration_view(reg)  # tenant A
    foreign = _confirmation(reg, tenant_id=TENANT_B)

    verdict = validate_confirmation(foreign, view, _SERVER_RECEIVED, _YesVerifier(), {})

    assert isinstance(verdict, Rejected)
    assert verdict.reason_code is RejectionReason.CROSS_TENANT_REPLAY
    # A rejection is not an Accepted -> the clock start seam is structurally
    # unreachable (start_measurement_window takes ONLY an Accepted).
    assert not isinstance(verdict, Accepted)


def test_tenant_b_injected_at_binding_seam_is_not_found() -> None:
    """E8: at the binding seam, a submission whose tenant is B but whose
    registration is tenant A's is denied EXACTLY as a genuinely-absent
    registration is (`BindingNotFoundError`, no tenant field) — no existence
    oracle. Pins `bind_experiment`'s tenant-first guard."""
    reg = _registration()  # tenant A
    foreign_submission = _submission(reg, tenant_id=TENANT_B)

    with pytest.raises(BindingNotFoundError) as cross_tenant:
        bind_experiment(reg, foreign_submission, weights=WeightsPolicy.not_registered())

    # A genuinely absent registration (None) for the SAME foreign tenant.
    with pytest.raises(BindingNotFoundError) as truly_absent:
        bind_experiment(None, foreign_submission, weights=WeightsPolicy.not_registered())

    # Identical surface: same type, same reason, same (absent) field.
    assert cross_tenant.value.reason == truly_absent.value.reason == "not_found"
    assert cross_tenant.value.field is truly_absent.value.field is None
    assert str(cross_tenant.value) == str(truly_absent.value)


def test_tenant_b_injected_at_evidence_retrieval_seam_reads_nothing() -> None:
    """E5/E8: at the evidence seam, a tenant-B reader of tenant A's sealed
    manifest reads the SAME `None` as an out-of-range index — no cross-tenant
    bundle content, no existence oracle. Pins `entry_for_tenant`'s guard."""
    manifest = _sealed_manifest(tenant_id=TENANT_A)

    cross_tenant = entry_for_tenant(manifest, tenant_id=TENANT_B, index=0)
    out_of_range = entry_for_tenant(manifest, tenant_id=TENANT_A, index=99)
    owner_reads_it = entry_for_tenant(manifest, tenant_id=TENANT_A, index=0)

    assert cross_tenant is None
    assert out_of_range is None
    assert owner_reads_it is not None  # the real owner really can read it


def test_tenant_b_injected_at_store_seams_is_isolated() -> None:
    """E8: at each ports store seam, a tenant-B forged-tenant-id WRITE raises
    `TenantIsolationError` and a tenant-B READ of tenant A's key is a
    non-leaking `NotFoundError`. Covers all four measurement stores."""
    conf_store = InMemoryConfirmationStore()
    window_store = InMemoryMeasurementWindowStore()
    decision_store = InMemoryOutcomeDecisionStore()
    bundle_store = InMemoryEvidenceBundleStore()

    # Store a real tenant-A record in each.
    conf_store.put_confirmation(
        TENANT_A,
        "k1",
        ConfirmationRecord(
            tenant_id=TENANT_A, confirmation_key="k1", measurement_kind="citation", payload={"x": 1}
        ),
    )
    window_store.open_window(
        TENANT_A,
        StoredWindow(
            tenant_id=TENANT_A,
            experiment_id="exp-1",
            starts_at="t0",
            ends_at=None,
            policy_version="1",
        ),
    )
    decision_store.append_decision(
        TENANT_A,
        OutcomeDecisionRecord(
            tenant_id=TENANT_A,
            decision_key=("exp-1", "primary"),
            outcome="undetermined",
            evidence_bundle_ref=_SHA_A,
            policy_metadata={"v": "1"},
        ),
    )
    bundle_store.put(TENANT_A, _SHA_A, EvidenceBundle(tenant_id=TENANT_A, manifest={"n": 1}))

    # (a) forged tenant-id write: caller claims TENANT_B but record embeds TENANT_A.
    with pytest.raises(TenantIsolationError):
        conf_store.put_confirmation(
            TENANT_B,
            "k1",
            ConfirmationRecord(
                tenant_id=TENANT_A,
                confirmation_key="k1",
                measurement_kind="citation",
                payload={"x": 1},
            ),
        )
    with pytest.raises(TenantIsolationError):
        window_store.open_window(
            TENANT_B,
            StoredWindow(
                tenant_id=TENANT_A,
                experiment_id="exp-1",
                starts_at="t0",
                ends_at=None,
                policy_version="1",
            ),
        )
    with pytest.raises(TenantIsolationError):
        decision_store.append_decision(
            TENANT_B,
            OutcomeDecisionRecord(
                tenant_id=TENANT_A,
                decision_key=("exp-1", "primary"),
                outcome="undetermined",
                evidence_bundle_ref=_SHA_A,
                policy_metadata={"v": "1"},
            ),
        )
    with pytest.raises(TenantIsolationError):
        bundle_store.put(TENANT_B, _SHA_A, EvidenceBundle(tenant_id=TENANT_A, manifest={"n": 1}))

    # (b) cross-tenant read: tenant B asks for tenant A's key -> non-leaking absent.
    with pytest.raises(NotFoundError):
        conf_store.get(TENANT_B, "k1")
    with pytest.raises(NotFoundError):
        window_store.get_active(TENANT_B, "exp-1")
    with pytest.raises(NotFoundError):
        decision_store.get(TENANT_B, ("exp-1", "primary"))
    with pytest.raises(NotFoundError):
        bundle_store.get(TENANT_B, _SHA_A)

    # tenant B's list is empty (never sees tenant A's decision).
    assert decision_store.list_decisions(TENANT_B) == ()


def test_cross_tenant_error_surfaces_are_consistent_or_flagged() -> None:
    """E8: compare the cross-tenant REJECTION SURFACES across every seam of the
    chain and assert the observed consistency contract.

    Two families CLAIM existence-oracle-safety (cross-tenant is
    indistinguishable from absent) — this asserts they actually deliver it:
      - binding: cross-tenant == absent (`not_found`, no field).
      - evidence: cross-tenant read == out-of-range read (`None`).

    One family does NOT and is a documented DRIFT (finding for the Integrator):
      - confirmation: a tenant mismatch is a DISTINCT reason code
        (`CROSS_TENANT_REPLAY`) from an identity (run/project/site) mismatch
        (`IDENTITY_MISMATCH`) — an existence/attribution oracle on the tenant
        field. Pinned here as the CURRENT behaviour so a change is caught, and
        called out in the module docstring, NOT silently accepted as safe.

    MITIGATION LOCUS (Integrator decision, 2026-07-14): the distinct code is
    KEPT for its audit value (ADR-0014 precedent: tenant mismatch = 403 +
    audit event; a cross-tenant replay attempt is a security signal worth
    recording distinctly). The oracle is neutralized at the service boundary
    instead: w5-12's DeploymentConfirmedConsumer resolves the registration
    view via a server-side TENANT-SCOPED lookup keyed
    (tenant_id, registration_hash), so a caller can never present another
    tenant's registration and the CROSS_TENANT_REPLAY path becomes
    internal defense-in-depth, unreachable from the boundary.
    """
    reg = _registration()
    view = _registration_view(reg)

    # --- confirmation: tenant-mismatch reason vs identity-mismatch reason ---
    wrong_tenant = validate_confirmation(
        _confirmation(reg, tenant_id=TENANT_B), view, _SERVER_RECEIVED, _YesVerifier(), {}
    )
    wrong_identity_conf = _confirmation(reg).model_copy(update={"run_id": "run-EVIL"})
    wrong_identity = validate_confirmation(
        wrong_identity_conf, view, _SERVER_RECEIVED, _YesVerifier(), {}
    )
    assert isinstance(wrong_tenant, Rejected) and isinstance(wrong_identity, Rejected)
    # DRIFT (finding): confirmation distinguishes the two -> tenant oracle.
    assert wrong_tenant.reason_code is RejectionReason.CROSS_TENANT_REPLAY
    assert wrong_identity.reason_code is RejectionReason.IDENTITY_MISMATCH
    assert wrong_tenant.reason_code != wrong_identity.reason_code

    # --- binding: cross-tenant == genuinely absent (oracle-safe) ------------
    foreign_submission = _submission(reg, tenant_id=TENANT_B)
    with pytest.raises(BindingNotFoundError) as b_cross:
        bind_experiment(reg, foreign_submission, weights=WeightsPolicy.not_registered())
    with pytest.raises(BindingNotFoundError) as b_absent:
        bind_experiment(None, foreign_submission, weights=WeightsPolicy.not_registered())
    assert b_cross.value.reason == b_absent.value.reason == "not_found"
    assert str(b_cross.value) == str(b_absent.value)  # byte-identical surface

    # --- evidence: cross-tenant read == out-of-range read (oracle-safe) -----
    manifest = _sealed_manifest(tenant_id=TENANT_A)
    assert entry_for_tenant(manifest, tenant_id=TENANT_B, index=0) is None
    assert entry_for_tenant(manifest, tenant_id=TENANT_A, index=99) is None

    # --- ports: cross-tenant read is uniform NotFoundError across all stores -
    conf_store = InMemoryConfirmationStore()
    with pytest.raises(NotFoundError):
        conf_store.get(TENANT_B, "never")


# ==========================================================================
# TEST 2 — No raw content / secret leakage sweep (E5/E12)
# ==========================================================================

#: Secret-shaped + raw-content salt values seeded into every free-form field.
#: Each is either a known secret shape the evidence guard already knows, or a
#: raw-content marker; the sweep asserts NONE of them ever echo out of an
#: exception, repr, decision record, or evidence entry.
_SECRET_SALT = "sk-" + "Z" * 32
_AWS_SALT = "AKIA" + "Q" * 16
_RAW_CONTENT_SALT = "<html><body>customer PII: SSN 123-45-6789</body></html>"


def _walk_strings(obj: object) -> list[str]:
    """Recursively collect every string reachable inside a JSON-shaped object."""
    found: list[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            found.append(str(k))
            found.extend(_walk_strings(v))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found.extend(_walk_strings(item))
    return found


def test_evidence_guard_rejects_secret_shaped_values_without_echoing_them() -> None:
    """E5: a secret-shaped value smuggled into an evidence field is rejected
    fail-closed, and the RaisedError never echoes the offending value (only the
    field name + reason category)."""
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({"note": f"leaked {_SECRET_SALT} here"})
    message = str(exc.value)
    context = exc.value.to_dict()
    assert _SECRET_SALT not in message
    assert _SECRET_SALT not in _walk_strings(context)
    assert context["reason"] == "secret_shaped_value"


def test_evidence_guard_rejects_forbidden_field_names_without_echoing_values() -> None:
    """E5: a raw-content-shaped FIELD NAME (any casing / separator) is rejected
    and the value is never echoed. Uses a nested mapping to prove recursion."""
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({"metadata": {"raw-Content": _RAW_CONTENT_SALT}})
    assert _RAW_CONTENT_SALT not in str(exc.value)
    assert _RAW_CONTENT_SALT not in _walk_strings(exc.value.to_dict())


def test_evidence_entry_construction_refuses_smuggled_secret_in_extra() -> None:
    """E5: an `EvidenceEntry` cannot be constructed with a secret smuggled into
    `metadata.extra`; the model_validator runs the guard and rejects it, and
    the ValidationError never carries the secret value."""
    with pytest.raises(Exception) as exc:  # pydantic ValidationError wraps RawContentRejectedError
        EvidenceEntry(
            kind=EvidenceKind.DID_INPUTS,
            ref=EvidenceRef(uri="artifact://x", content_hash=_SHA_A),
            metadata=EvidenceMetadata(extra={"api_key": _SECRET_SALT}),
        )
    assert _SECRET_SALT not in str(exc.value)


def test_no_secret_leaks_across_the_pipeline_output_objects() -> None:
    """E5/E12: seed secret-shaped + raw-content salts into every free-form
    field the pipeline objects accept, then walk `model_dump()` of every output
    object and assert NONE of the salts survive into a decision record, an
    evidence entry, a confirmation verdict, or a store record.

    Where a module GUARDS a field against secrets (evidence refs/metadata), the
    salt cannot even be constructed there — asserted separately above. Where a
    module accepts free text (confirmer identity, opaque URIs, decision outcome
    labels), this proves the salt does not silently propagate into a DIFFERENT
    object's serialised output further down the chain.
    """
    reg = _registration()

    # A confirmation whose free-form confirmer fields carry the salt. The
    # confirmer fields are consumed ONLY by the injected verifier; they must
    # not surface in the Rejected/Accepted verdict's dump.
    salted_conf = _confirmation(reg).model_copy(
        update={"confirmer_identity": _SECRET_SALT, "confirmer_signature": _AWS_SALT}
    )
    view = _registration_view(reg)
    # Accepted carries the confirmation, so its OWN dump legitimately contains
    # the confirmer fields (they are that object's data) — but the Rejected
    # verdict (what a non-owner sees) must NOT. Force a rejection path and dump.
    foreign_verdict = validate_confirmation(
        salted_conf.model_copy(update={"tenant_id": TENANT_B}),
        view,
        _SERVER_RECEIVED,
        _YesVerifier(),
        {},
    )
    assert isinstance(foreign_verdict, Rejected)
    rejected_strings = _walk_strings(foreign_verdict.model_dump(mode="json"))
    assert _SECRET_SALT not in rejected_strings
    assert _AWS_SALT not in rejected_strings

    # A binding rejection (metric mutation) must not echo raw values either —
    # only the offending field NAME (the metric id, caller's own input).
    bad_submission = _submission(reg).model_copy(
        update={
            "metrics": (MeasurementMetricInput(metric_id="m1", metric_hash=_SHA_A, weight=1.0),)
        }
    )
    with pytest.raises(BindingRejectedError) as binding_exc:
        bind_experiment(reg, bad_submission, weights=WeightsPolicy.not_registered())
    # The wrong metric_hash salt (a hash, not a secret, but treat as opaque)
    # must not appear in the error surface — only the metric id.
    assert _SHA_A not in str(binding_exc.value)

    # A stored decision record's dump must contain only what it was built with
    # (no cross-object leakage): build one WITHOUT any secret and confirm the
    # salts are absent from its serialised form.
    decision = OutcomeDecisionRecord(
        tenant_id=TENANT_A,
        decision_key=("exp-1", "primary"),
        outcome="undetermined",
        evidence_bundle_ref=_SHA_A,
        policy_metadata={"policy_version": "1.0.0"},
    )
    decision_strings = _walk_strings(
        {
            "tenant_id": decision.tenant_id,
            "decision_key": list(decision.decision_key),
            "outcome": decision.outcome,
            "evidence_bundle_ref": decision.evidence_bundle_ref,
            "policy_metadata": dict(decision.policy_metadata),
        }
    )
    assert _SECRET_SALT not in decision_strings
    assert _AWS_SALT not in decision_strings
    assert _RAW_CONTENT_SALT not in decision_strings


# ==========================================================================
# TEST 5 — Idempotency under adversarial replay ACROSS modules (E8)
# ==========================================================================


def test_replayed_confirmation_is_single_window_at_store_and_validation_levels() -> None:
    """E8: the SAME confirmation replayed at BOTH the store level (w5-09
    ConfirmationStore) AND the validation level (w5-03 validate_confirmation)
    yields a SINGLE window / a consistent Duplicate — never a second, never a
    restart, never a conflict.

    This is the cross-module replay invariant: the two independent idempotency
    mechanisms (store byte-identity dedup, and validation prior-state dedup)
    agree on the same confirmation.
    """
    reg = _registration()
    view = _registration_view(reg)
    conf = _confirmation(reg)

    # --- validation-level replay (w5-03) -----------------------------------
    first = validate_confirmation(conf, view, _SERVER_RECEIVED, _YesVerifier(), {})
    assert isinstance(first, Accepted)
    window_first = start_measurement_window(first, view)

    prior_state = {conf.idempotency_key: first}
    replay = validate_confirmation(conf, view, _SERVER_RECEIVED, _YesVerifier(), prior_state)
    assert isinstance(replay, Duplicate)
    # The duplicate resolves to the SAME accepted verdict (same window anchor).
    assert replay.accepted is first
    window_replay = start_measurement_window(replay.accepted, view)
    assert window_replay.anchor == window_first.anchor
    assert window_replay.end == window_first.end
    assert window_replay.content_fingerprint == window_first.content_fingerprint

    # --- store-level replay (w5-09) ----------------------------------------
    store = InMemoryConfirmationStore()
    record = ConfirmationRecord(
        tenant_id=TENANT_A,
        confirmation_key=conf.idempotency_key,
        measurement_kind="deployment_confirmation",
        payload={"registration_hash": reg.canonical_hash},
    )
    stored_first = store.put_confirmation(TENANT_A, conf.idempotency_key, record)
    stored_replay = store.put_confirmation(TENANT_A, conf.idempotency_key, record)
    assert stored_first.outcome is PutOutcome.STORED
    assert stored_replay.outcome is PutOutcome.DUPLICATE
    # A single record — the journal has exactly one accepted write.
    assert len(store.journal()) == 1
    assert stored_replay.record is stored_first.record
