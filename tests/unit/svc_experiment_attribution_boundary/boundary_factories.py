"""Shared test factories/fakes for `tests/unit/svc_experiment_attribution_boundary`.

In-memory fakes for every injected port (`RegistrationLookup`,
`WorkflowSignal`, `ManifestLookup`, `ConfirmationStore`) plus small builder
helpers for the domain/contract objects the boundary handlers consume. No
real bus/DB anywhere in this module.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from saena_domain.measurement.b_gate import (
    BGateDecision,
    BVerdict,
    EvidenceCheck,
    GatePolicy,
    PolicyProvenance,
    SignalResult,
    WindowState,
    decide_b_verdict,
)
from saena_domain.measurement.confirmation import RegistrationView
from saena_domain.measurement.evidence import (
    EvidenceBundleManifest,
    EvidenceEntry,
    EvidenceKind,
    EvidenceMetadata,
    EvidenceRef,
)
from saena_domain.measurement.outcome_layer import OutcomeLayer
from saena_domain.measurement.ports import InMemoryConfirmationStore
from saena_schemas.event.experiment_outcome_observed_v1 import GrsPolicy, Provenance, Window

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
RUN_ID = "run-001"
EXPERIMENT_ID = "exp-001"
REGISTRATION_HASH = "sha256:" + "a" * 64
ARTIFACT_HASH = "sha256:" + "b" * 64
GIT_SHA = "c" * 40

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)


def now() -> datetime:
    return _NOW


class FakeRegistrationLookup:
    """In-memory `RegistrationLookup` — compound-key store only.

    Deliberately has NO secondary lookup method (mirrors the port's
    contract) — a test proving the cross-tenant oracle is neutralized calls
    `.lookup(wrong_tenant, real_hash)` and observes the identical `None` a
    genuinely-unknown hash would produce.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], RegistrationView] = {}

    def put(self, view: RegistrationView) -> None:
        self._store[(view.tenant_id, view.registration_canonical_hash)] = view

    def lookup(self, tenant_id: str, registration_hash: str) -> RegistrationView | None:
        return self._store.get((tenant_id, registration_hash))


class FakeWorkflowSignal:
    """Records every `signal_confirmed` call for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def signal_confirmed(self, tenant_id: str, experiment_id: str, server_received_at: str) -> None:
        self.calls.append((tenant_id, experiment_id, server_received_at))


class FakeManifestLookup:
    """In-memory `ManifestLookup` — compound-key store, non-leaking absent."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], EvidenceBundleManifest] = {}

    def put(self, tenant_id: str, manifest: EvidenceBundleManifest) -> None:
        assert manifest.manifest_hash is not None
        self._store[(tenant_id, manifest.manifest_hash)] = manifest

    def lookup(self, tenant_id: str, manifest_hash: str) -> EvidenceBundleManifest | None:
        return self._store.get((tenant_id, manifest_hash))


class AlwaysTrustVerifier:
    """A `TrustVerifier` that always returns `True` (accepted confirmer)."""

    def verify(self, confirmation: object) -> bool:  # noqa: ARG002
        return True


class NeverTrustVerifier:
    """A `TrustVerifier` that always returns `False` (rejected confirmer)."""

    def verify(self, confirmation: object) -> bool:  # noqa: ARG002
        return False


def make_registration_view(
    *,
    tenant_id: str = TENANT_A,
    experiment_id: str = EXPERIMENT_ID,
    run_id: str = RUN_ID,
    registration_canonical_hash: str = REGISTRATION_HASH,
    project: str = "site-kind",
    site: str = "site-identifier",
    created_at: datetime | None = None,
    approved_at: datetime | None = None,
) -> RegistrationView:
    created = created_at or (_NOW - timedelta(days=10))
    approved = approved_at or (_NOW - timedelta(days=9))
    return RegistrationView(
        experiment_id=experiment_id,
        tenant_id=tenant_id,
        run_id=run_id,
        project=project,
        site=site,
        registration_canonical_hash=registration_canonical_hash,
        created_at=created,
        approved_at=approved,
    )


def make_confirmed_payload(
    *,
    deployment_id: str = "deploy-001",
    experiment_id: str = EXPERIMENT_ID,
    registration_canonical_hash: str = REGISTRATION_HASH,
    deployment_target_kind: str = "site-kind",
    deployment_target_identifier: str = "site-identifier",
    deployed_commit_sha: str | None = GIT_SHA,
    artifact_hash: str | None = None,
    confirmer_identity: str = "actor-001",
    confirmer_method: str = "ci_pipeline",
    confirmed_at: str = "2026-07-05T00:00:00Z",
    extra_tenant_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "deployment_id": deployment_id,
        "registration_ref": {
            "experiment_id": experiment_id,
            "registration_canonical_hash": registration_canonical_hash,
        },
        "deployment_target": {
            "kind": deployment_target_kind,
            "identifier": deployment_target_identifier,
        },
        "confirmer": {
            "identity": confirmer_identity,
            "method": confirmer_method,
        },
        "confirmed_at": confirmed_at,
    }
    if deployed_commit_sha is not None:
        payload["deployed_commit_sha"] = deployed_commit_sha
    if artifact_hash is not None:
        payload["artifact_hash"] = artifact_hash
    if extra_tenant_id is not None:
        payload["tenant_id"] = extra_tenant_id
    return payload


def make_confirmation_store() -> InMemoryConfirmationStore:
    return InMemoryConfirmationStore()


def make_evidence_manifest(
    *, tenant_id: str = TENANT_A, run_id: str = RUN_ID, experiment_id: str = EXPERIMENT_ID
) -> EvidenceBundleManifest:
    entry = EvidenceEntry(
        kind=EvidenceKind.B_GATE_DECISION,
        ref=EvidenceRef(uri="mem://bundle/1", content_hash="sha256:" + "d" * 64),
        metadata=EvidenceMetadata(),
    )
    return EvidenceBundleManifest.seal(
        tenant_id=tenant_id, run_id=run_id, experiment_id=experiment_id, entries=(entry,)
    )


def make_passing_b_gate_decision(
    *, provenance: PolicyProvenance = PolicyProvenance.TEST_FIXTURE
) -> BGateDecision:
    policy = GatePolicy(version="1.0.0", hash="sha256:" + "e" * 64, provenance=provenance)
    signals = (
        SignalResult(
            layer=OutcomeLayer.CITATION,
            evidence_basis_id="sha256:" + "1" * 64,
            treatment_raw_delta=5.0,
            control_raw_delta=0.0,
            net_of_control_lift=5.0,
        ),
        SignalResult(
            layer=OutcomeLayer.DISCOVERY,
            evidence_basis_id="sha256:" + "2" * 64,
            treatment_raw_delta=3.0,
            control_raw_delta=0.0,
            net_of_control_lift=3.0,
        ),
    )
    evidence_check = EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True)
    window_state = WindowState(complete=True, deployment_confirmed=True)
    decision = decide_b_verdict(signals, evidence_check, window_state, policy)
    assert decision.verdict is BVerdict.PASS
    return decision


def make_single_layer_decision() -> BGateDecision:
    policy = GatePolicy(
        version="1.0.0", hash="sha256:" + "e" * 64, provenance=PolicyProvenance.TEST_FIXTURE
    )
    signals = (
        SignalResult(
            layer=OutcomeLayer.CITATION,
            evidence_basis_id="sha256:" + "1" * 64,
            treatment_raw_delta=5.0,
            control_raw_delta=0.0,
            net_of_control_lift=5.0,
        ),
    )
    evidence_check = EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True)
    window_state = WindowState(complete=True, deployment_confirmed=True)
    return decide_b_verdict(signals, evidence_check, window_state, policy)


def make_window() -> Window:
    return Window(
        started_at="2026-07-05T00:00:00Z",
        ended_at="2026-07-12T00:00:00Z",
        clock_anchor="deployment_confirmed",
    )


def make_grs_policy(*, provenance: Provenance = Provenance.test_fixture) -> GrsPolicy:
    return GrsPolicy(version="1.0.0", hash="sha256:" + "f" * 64, provenance=provenance)


__all__ = [
    "ARTIFACT_HASH",
    "EXPERIMENT_ID",
    "GIT_SHA",
    "REGISTRATION_HASH",
    "RUN_ID",
    "TENANT_A",
    "TENANT_B",
    "AlwaysTrustVerifier",
    "FakeManifestLookup",
    "FakeRegistrationLookup",
    "FakeWorkflowSignal",
    "NeverTrustVerifier",
    "make_confirmation_store",
    "make_confirmed_payload",
    "make_evidence_manifest",
    "make_grs_policy",
    "make_passing_b_gate_decision",
    "make_registration_view",
    "make_single_layer_decision",
    "make_window",
    "now",
]
