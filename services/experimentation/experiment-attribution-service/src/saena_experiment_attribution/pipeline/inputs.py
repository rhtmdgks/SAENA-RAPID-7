"""Frozen input/port/policy shapes for `run_measurement` (w5-13).

`run_measurement` is a pure orchestration function: everything it needs comes
in through `MeasurementInputs` (the data), `MeasurementPorts` (the injected
persistence ports — `saena_domain.measurement.ports` Protocols, never a
concrete adapter), and `MeasurementPolicies` (the injected, already-decided
policy objects each composed domain module requires: `WeightsPolicy`,
`did.DiDPolicy`, `b_gate.GatePolicy`, `clock.MeasurementPolicy`). The pipeline
never constructs a policy default itself — every policy is REQUIRED, mirroring
`binding.bind_experiment`'s `weights` keyword-only requirement (an omitted
policy is a `TypeError` at the call site, never a silent fail-open default).

No I/O happens by importing this module: `MeasurementPorts` carries
`typing.Protocol` instances the CALLER constructs (in tests: the in-memory
reference adapters from `saena_domain.measurement.ports`; in production: the
w5-10 Postgres adapters, once wired by w5-12).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from saena_domain.experiment.models import ExperimentRegistration
from saena_domain.measurement.b_gate import GatePolicy
from saena_domain.measurement.binding import MeasurementSubmission, WeightsPolicy
from saena_domain.measurement.clock import MeasurementPolicy as ClockPolicy
from saena_domain.measurement.confirmation import (
    DeploymentConfirmation,
    PriorState,
    RegistrationView,
    TrustVerifier,
)
from saena_domain.measurement.did import DiDPolicy, SignalSeries
from saena_domain.measurement.evidence import EvidenceMetadata
from saena_domain.measurement.grs import GrsPolicyBundle
from saena_domain.measurement.ports import (
    ConfirmationStore,
    EvidenceBundleStore,
    MeasurementWindowStore,
    OutcomeDecisionStore,
)


@dataclass(frozen=True, slots=True)
class MeasurementPorts:
    """The persistence ports `run_measurement` writes through.

    All four are `saena_domain.measurement.ports` Protocols — the pipeline
    never imports a concrete adapter. `confirmation_store` and `window_store`
    give the pipeline durable idempotency for the deployment-confirmation and
    window-open steps (mirroring `validate_confirmation`'s own idempotency
    contract at the persistence layer); `decision_store` is where the final
    `ExperimentOutcome` (as an `OutcomeDecisionRecord`) is appended
    atomically; `evidence_store` is where the sealed evidence bundle manifest
    is content-addressed.
    """

    confirmation_store: ConfirmationStore
    window_store: MeasurementWindowStore
    decision_store: OutcomeDecisionStore
    evidence_store: EvidenceBundleStore


@dataclass(frozen=True, slots=True)
class MeasurementPolicies:
    """Every policy object a composed domain module requires — all REQUIRED.

    No field has a default: omitting one is a `TypeError` at the call site,
    never a silent fail-open default (mirrors `WeightsPolicy`'s own
    keyword-only-required discipline, extended to the whole pipeline). A
    caller that genuinely has no GRS policy bundle passes `grs_bundle=None`
    EXPLICITLY (the honest "no bundle" case handled by
    `evaluate_grs_eligibility` itself) — that is different from omitting the
    field.
    """

    weights: WeightsPolicy
    did_policy: DiDPolicy
    gate_policy: GatePolicy
    clock_policy: ClockPolicy
    grs_bundle: GrsPolicyBundle | None
    trust_verifier: TrustVerifier | None
    allowed_confirmation_skew_seconds: int = 0


@dataclass(frozen=True, slots=True)
class MeasurementInputs:
    """Everything `run_measurement` needs to know about ONE measurement run.

    `registration` is the located W4 registration (or `None` — an absent
    registration is itself a fail-closed binding outcome, never a pipeline
    exception). `registration_view` is the trusted projection used by
    confirmation/clock validation (see `saena_domain.measurement.confirmation.
    RegistrationView` — carries `approved_at`, which `ExperimentRegistration`
    itself does not, by W4 design: the approval timestamp is an operational
    fact layered on top of the immutable registration content, not part of
    it). `submission` is the measurement-time binding submission (cells /
    metrics / observation admission records). `signals` are the raw
    per-signal DiD input series (baseline/post x treatment/control repeat
    values) — a data flow INDEPENDENT of `submission.observations` (binding
    admits WHICH observations may be measured; `signals` carries the actual
    numeric values DiD computes over). `deployment_confirmation` +
    `server_received_at` feed `confirmation.validate_confirmation`.
    `evaluation_at` is the instant the pipeline evaluates the window's
    completeness against (Temporal's workflow-time in production; a fixed
    instant in tests — this pipeline is otherwise wall-clock-free).
    `grs_inputs` feeds `grs.evaluate_grs_eligibility`.

    `evidence_observation_entries` carries the caller-assembled
    per-observation `EvidenceMetadata` (timestamp/client_version/asset_hash/
    citation) keyed by `(kind, observation_id-or-slot)` so the evidence bundle
    can attach REAL provenance rather than a synthesized placeholder — see
    `orchestrator.py`'s evidence-assembly step for exactly how these are
    consumed.
    """

    tenant_id: str
    run_id: str
    experiment_id: str
    registration: ExperimentRegistration | None
    registration_view: RegistrationView
    submission: MeasurementSubmission
    signals: tuple[SignalSeries, ...]
    deployment_confirmation: DeploymentConfirmation
    server_received_at: datetime
    evaluation_at: datetime
    prior_confirmations: PriorState
    grs_inputs: dict[str, object]
    baseline_evidence: tuple[tuple[str, EvidenceMetadata], ...] = ()
    treatment_evidence: tuple[tuple[str, EvidenceMetadata], ...] = ()
    control_evidence: tuple[tuple[str, EvidenceMetadata], ...] = ()


__all__ = [
    "MeasurementInputs",
    "MeasurementPolicies",
    "MeasurementPorts",
]
