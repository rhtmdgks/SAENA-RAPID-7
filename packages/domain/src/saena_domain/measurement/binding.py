"""Measurement-time binding of a W4 experiment registration (w5-04).

This module is the E1 boundary (wave5-plan.md exit matrix): the W4
`saena_domain.experiment` package makes a treatment/control experiment design
*immutable at registration time* and anchors its hash into the audit ledger.
`binding.py` re-enforces that immutability *at measurement time* — the moment
observations are about to feed the DiD engine (w5-05) — so that a design which
was honestly pre-registered cannot be silently mutated, contaminated, or
tenant-confused between registration and outcome computation.

Pure, deterministic, no I/O. It computes NOTHING about outcomes/effect/lift
(that is w5-05 DiD, downstream): it only *admits or rejects* a measurement
submission against the registration it claims to measure, and, on success,
emits a frozen `BoundExperiment` carrying the registered arms/metrics/cell
read-only for the DiD engine to consume.

## What it guards (each guard has a pinned adversarial + guard-mutation test)

1. **Registration integrity** — re-derives the registration's chain-entry hash
   via the EXISTING W4 `saena_domain.experiment.ledger.compute_experiment_hash`
   (NEVER a second hashing rule) and compares it to the audit-anchored hash the
   caller supplies. Mismatch ⇒ a post-registration mutation happened between
   anchoring and measurement ⇒ `post_registration_mutation` reject.
2. **Metric immutability** — every metric the measurement references must be a
   metric the registration declared, matched by `metric_id` AND by the metric's
   content hash (so an altered definition under a reused id is caught). Unknown
   metric or altered definition ⇒ `metric_mutation`. A KPI weight that differs
   from the registered weight ⇒ `metric_mutation` (KPI-weight tampering path).
3. **Observation cell conformance** — each observation's
   locale / browser_policy / query_cluster_ref / repeat_count cell must equal
   the registered cell exactly; the FIRST differing field is named in the
   reject (`cell_mismatch`).
4. **Arm-assignment integrity + contamination** — asset design: a query cell
   assigned to `treatment` may not also appear under `control` (or vice
   versa); matched-cluster design: an observation's cluster must equal its
   arm's REGISTERED cluster, and one cluster may not be claimed by two
   different arms; in both designs the same observation/evidence id may not
   be claimed by two arms; an observed `asset_hash` differing from the
   registered `asset_hash` ⇒ `asset_hash_conflict`; the rest ⇒
   `contamination`.
5. **Cross-tenant** — a measurement tenant that differs from
   `registration.tenant_id` is denied with the SAME error shape as a
   not-found registration: no existence oracle (an attacker probing another
   tenant's `experiment_id` cannot distinguish "wrong tenant" from "no such
   registration").
6. **Conflicting registration** — same `experiment_id` presented with a
   different `content_fingerprint` than the caller's anchored view ⇒
   `conflicting_registration`.

## Redaction discipline (mirrors `saena_domain.experiment.errors`)

Every `BindingError` carries an `experiment_id`, a typed `reason`, and — where
relevant — the NAME of the offending field or arm/id, never the raw
registration content, arm/metric payloads, observed values, or secrets. This
matches ADR-0015's audit error-footprint principle: name the offending
reference, not the offending data.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from saena_domain.audit.canonical import canonical_json, sha256_hex
from saena_domain.experiment.ledger import compute_experiment_hash
from saena_domain.experiment.models import (
    ExperimentRegistration,
    MetricDefinition,
)

#: The `sha256:<hex>` wire-form prefix convention shared across the contracts
#: (`^sha256:[0-9a-f]{64}$`) and used by `saena_domain.experiment.ledger` /
#: `saena_domain.audit.hashing`. Metric fingerprints below use the SAME
#: canonical-JSON + sha256 rule (`saena_domain.audit.canonical`) — never a
#: second hashing rule — with this prefix.
_SHA256_PREFIX = "sha256:"

#: Typed reject reason codes. `not_found` is deliberately the SAME code used
#: for both a genuinely-absent registration and a cross-tenant access attempt
#: (no existence oracle). The remaining codes name the specific immutability /
#: contamination invariant that was violated.
BindingRejectReason = Literal[
    "not_found",
    "post_registration_mutation",
    "conflicting_registration",
    "metric_mutation",
    "cell_mismatch",
    "contamination",
    "asset_hash_conflict",
]

#: Arm-role pairs that participate in the ASSET-design contamination check
#: (a query cell observed under one role must not appear under the paired
#: role). Matched-cluster designs are guarded separately in
#: `_reject_contamination`: each observation's cluster ref must equal its
#: arm's REGISTERED cluster ref, and a cluster ref may not be claimed by two
#: different arms (bidirectional per-arm ownership). `baseline` is the shared
#: reference and never a contamination source on its own in asset designs.
_CONTAMINATING_ROLE_PAIRS: tuple[tuple[str, str], ...] = (("treatment", "control"),)


class BindingError(Exception):
    """Base class for all measurement-binding rejections.

    Carries an `experiment_id`, a typed `reason` code, and an optional `field`
    naming the specific offending reference (metric id, cell field, arm id, or
    observation id) — never the raw offending data. `not_found` is the
    existence-oracle-safe reason shared by absent-registration and
    cross-tenant denials.
    """

    def __init__(
        self,
        experiment_id: str,
        reason: BindingRejectReason,
        *,
        field: str | None = None,
    ) -> None:
        self.experiment_id = experiment_id
        self.reason: BindingRejectReason = reason
        self.field = field
        detail = f" (field: {field})" if field is not None else ""
        super().__init__(
            f"measurement binding for experiment_id {experiment_id!r} rejected: {reason}{detail}"
        )


class BindingNotFoundError(BindingError):
    """Registration absent OR cross-tenant — indistinguishable by design.

    Both "no registration with this `experiment_id`" and "a registration
    exists but belongs to a different tenant" raise this with
    `reason="not_found"` and NO tenant-identifying field, so a caller probing
    another tenant's `experiment_id` learns nothing about its existence.
    """

    def __init__(self, experiment_id: str) -> None:
        super().__init__(experiment_id, "not_found")


class BindingRejectedError(BindingError):
    """A registration was located and owned by the caller's tenant, but the
    measurement submission violated an immutability/contamination invariant."""


class WeightsPolicy(BaseModel):
    """Explicit, non-forgettable KPI-weight enforcement state for a bind.

    ALG §3.6:190 names KPI-weight manipulation as a first-class tampering
    risk, so weight enforcement may never be skipped BY ACCIDENT:
    `bind_experiment` takes a REQUIRED keyword-only `weights` parameter of
    this type — omitting it raises `TypeError` at the call site, never a
    silent fail-open no-op. Exactly two constructors exist:

    - `WeightsPolicy.enforce(registered_weights)` — supply the registered
      `metric_id -> KPI weight` mapping; a submission weight that differs, or
      a submitted metric absent from the mapping, is a `metric_mutation`
      reject (KPI-weight tampering path).
    - `WeightsPolicy.not_registered()` — a DELIBERATE declaration that this
      engagement registered no KPI weights. Only valid when the experiment's
      registration genuinely carries no weights (the current
      `ExperimentRegistration`/`MetricDefinition` models have no weight
      field); it is an explicit opt-out visible in the caller's code, never
      an implicit default.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["enforce", "not_registered"]
    #: Sorted `(metric_id, weight)` pairs — a frozen representation of the
    #: registered mapping; empty (and unused) in `not_registered` mode.
    registered_weights: tuple[tuple[str, float], ...] = ()

    @classmethod
    def enforce(cls, registered_weights: Mapping[str, float]) -> WeightsPolicy:
        """Enforce the registered `metric_id -> KPI weight` mapping."""
        return cls(
            mode="enforce",
            registered_weights=tuple(sorted(registered_weights.items())),
        )

    @classmethod
    def not_registered(cls) -> WeightsPolicy:
        """Deliberate opt-out — ONLY valid when the engagement registered no
        KPI weights. An explicit statement in the caller's code, not a default."""
        return cls(mode="not_registered")

    def registered_weight_for(self, metric_id: str) -> float | None:
        """The registered weight for `metric_id`, or `None` if unregistered."""
        for candidate_id, weight in self.registered_weights:
            if candidate_id == metric_id:
                return weight
        return None


class MeasurementMetricInput(BaseModel):
    """One metric the measurement submission intends to observe.

    `metric_hash` is the content hash of the metric DEFINITION as the caller
    believes it was registered; `weight` is the KPI weight the caller intends
    to apply. Both are checked against the registration — a mismatch on either
    is a `metric_mutation` reject. `weight` is a pure comparison value here:
    this module never optimizes or recomputes weights (that is forbidden in
    W5 — see wave5-plan.md non-scope "KPI weight auto-optimization").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str = Field(min_length=1)
    metric_hash: str = Field(min_length=1)
    weight: float


class MeasurementCell(BaseModel):
    """The observation cell (locale/browser/query-cluster/repeat) a measurement
    claims to have observed — must equal the registered cell exactly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    locale: str = Field(min_length=1)
    browser_policy: str = Field(min_length=1)
    query_cluster_ref: str = Field(min_length=1)
    repeat_count: int = Field(gt=0)


class Observation(BaseModel):
    """One measurement observation attributed to a single arm.

    `observation_id` uniquely identifies the observation across the whole
    submission; the same id claimed by two arms is contamination. `arm_id`
    must name a registered arm. `cell` must equal the registered cell.
    `asset_hash` (present only for asset-design arms) must equal the
    registered `asset_hash`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str = Field(min_length=1)
    arm_id: str = Field(min_length=1)
    cell: MeasurementCell
    asset_hash: str | None = Field(default=None, min_length=1)
    query_cluster_ref: str | None = Field(default=None, min_length=1)


class MeasurementSubmission(BaseModel):
    """Everything a measurement run presents to be bound to a registration.

    `anchored_hash` is the registration's chain-entry hash as recorded in the
    audit ledger at registration time (the trusted anchor). `tenant_id` is the
    tenant on whose behalf the measurement runs. `content_fingerprint` is the
    caller's view of the registration's content fingerprint (used to detect a
    same-id/different-content conflicting registration).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    anchored_hash: str = Field(min_length=1)
    content_fingerprint: str = Field(min_length=1)
    metrics: tuple[MeasurementMetricInput, ...] = Field(min_length=1)
    observations: tuple[Observation, ...] = Field(min_length=1)


class BoundExperiment(BaseModel):
    """Frozen, read-only result of a successful bind — consumable by w5-05 DiD.

    Carries the registered arms/metrics/cell verbatim (read-only) plus the
    validated observations. It has NO field that could hold an outcome, effect
    size, lift, or DiD estimate — binding admits inputs, it does not compute
    results.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str
    tenant_id: str
    anchored_hash: str
    registered_cell: MeasurementCell
    arm_roles: tuple[tuple[str, str], ...]
    metric_ids: tuple[str, ...]
    observations: tuple[Observation, ...]


def _metric_hash(metric: MetricDefinition) -> str:
    """Content hash of a single metric DEFINITION, reusing the W4 canonical
    JSON + sha256 rule (never a second hashing rule)."""
    material = metric.model_dump(mode="json")
    return f"{_SHA256_PREFIX}{sha256_hex(canonical_json(material))}"


def compute_metric_fingerprint(metric: MetricDefinition) -> str:
    """Public deterministic content fingerprint of a registered metric.

    Exposed so a caller assembling a `MeasurementMetricInput.metric_hash`
    references the SAME rule the guard checks against — any drift between the
    two would surface as a `metric_mutation` reject, never a silent pass.
    """
    return _metric_hash(metric)


def _verify_registration_integrity(
    registration: ExperimentRegistration, anchored_hash: str
) -> None:
    """Re-derive the chain-entry hash via the W4 function and compare.

    A mismatch means the in-hand registration content no longer hashes to the
    value anchored in the audit ledger at registration time — i.e. the design
    was mutated after anchoring. Rejected as `post_registration_mutation`.
    """
    recomputed = compute_experiment_hash(registration)
    if recomputed != anchored_hash:
        raise BindingRejectedError(registration.experiment_id, "post_registration_mutation")


def _reject_metric_mutation(
    registration: ExperimentRegistration,
    metrics: tuple[MeasurementMetricInput, ...],
    weights: WeightsPolicy,
) -> None:
    """Every referenced metric must be a registered metric, by id AND by
    content hash; under `WeightsPolicy.enforce`, every supplied weight must
    equal the registered weight."""
    by_id = {m.metric_id: m for m in registration.metric_definitions}
    for measured in metrics:
        registered = by_id.get(measured.metric_id)
        if registered is None:
            # Unknown metric id — not one the experiment declared it would
            # measure. Naming the id is safe (it is the caller's own input).
            raise BindingRejectedError(
                registration.experiment_id,
                "metric_mutation",
                field=measured.metric_id,
            )
        if _metric_hash(registered) != measured.metric_hash:
            # Same id, altered definition (or a stale/forged hash).
            raise BindingRejectedError(
                registration.experiment_id,
                "metric_mutation",
                field=measured.metric_id,
            )
        if weights.mode == "enforce":
            registered_weight = weights.registered_weight_for(measured.metric_id)
            if registered_weight is None or registered_weight != measured.weight:
                # KPI-weight tampering: the measurement applies a weight that
                # was not the registered weight for this metric.
                raise BindingRejectedError(
                    registration.experiment_id,
                    "metric_mutation",
                    field=measured.metric_id,
                )


def _reject_cell_mismatch(
    registration: ExperimentRegistration, observations: tuple[Observation, ...]
) -> None:
    """Each observation's cell must equal the registered cell exactly; the
    FIRST differing field is named in the reject."""
    for obs in observations:
        cell = obs.cell
        if cell.locale != registration.locale:
            raise BindingRejectedError(registration.experiment_id, "cell_mismatch", field="locale")
        if cell.browser_policy != registration.browser_policy:
            raise BindingRejectedError(
                registration.experiment_id, "cell_mismatch", field="browser_policy"
            )
        if cell.query_cluster_ref != registration.query_cluster_ref:
            raise BindingRejectedError(
                registration.experiment_id,
                "cell_mismatch",
                field="query_cluster_ref",
            )
        if cell.repeat_count != registration.repeat_count:
            raise BindingRejectedError(
                registration.experiment_id, "cell_mismatch", field="repeat_count"
            )


def _reject_contamination(
    registration: ExperimentRegistration, observations: tuple[Observation, ...]
) -> None:
    """Arm-assignment integrity + bidirectional contamination + asset-hash.

    - Every observation must name a registered arm.
    - An observed `asset_hash` (for an asset-design arm) must equal the
      registered `asset_hash` ⇒ else `asset_hash_conflict`.
    - The same `observation_id` may not be claimed by two arms ⇒ contamination.
    - ASSET design: a query cell observed under one contaminating role may not
      also appear under the paired role (treatment↔control) ⇒ contamination,
      checked in BOTH directions (set intersection is symmetric).
    - MATCHED-CLUSTER design: each observation's `query_cluster_ref` must equal
      its arm's REGISTERED `query_cluster_ref` (an observation claiming a
      cluster its arm was not assigned is a leak ⇒ contamination), and the same
      cluster ref may not be claimed by two DIFFERENT arms (bidirectional
      per-arm ownership) ⇒ contamination.
    """
    arms_by_id = {arm.arm_id: arm for arm in registration.arms}
    non_baseline_roles = {arm.role for arm in registration.arms if arm.role != "baseline"}
    is_matched_cluster_design = non_baseline_roles == {"matched_cluster"}

    seen_observation_ids: set[str] = set()
    # ASSET design: role -> set of the per-observation distinguishing query-cell
    # reference observed under that role. The experiment-wide `asset_hash` is
    # NOT a contamination key (every observation legitimately shares it — it is
    # the integrity/`asset_hash_conflict` check below); the contamination signal
    # is a specific query cell showing up under two OPPOSING arm roles.
    role_cells: dict[str, set[str]] = {}
    # MATCHED-CLUSTER design: cluster ref -> the single arm_id that owns it.
    cluster_owner: dict[str, str] = {}

    for obs in observations:
        arm = arms_by_id.get(obs.arm_id)
        if arm is None:
            raise BindingRejectedError(
                registration.experiment_id, "contamination", field=obs.arm_id
            )

        if obs.observation_id in seen_observation_ids:
            # Same evidence/observation id claimed by two arms.
            raise BindingRejectedError(
                registration.experiment_id,
                "contamination",
                field=obs.observation_id,
            )
        seen_observation_ids.add(obs.observation_id)

        if obs.asset_hash is not None and obs.asset_hash != registration.asset_hash:
            raise BindingRejectedError(
                registration.experiment_id,
                "asset_hash_conflict",
                field=obs.arm_id,
            )

        if obs.query_cluster_ref is not None:
            if is_matched_cluster_design:
                if (
                    arm.query_cluster_ref is not None
                    and obs.query_cluster_ref != arm.query_cluster_ref
                ):
                    # The observation claims a cluster its arm was NOT
                    # registered to observe — a cross-arm leak.
                    raise BindingRejectedError(
                        registration.experiment_id,
                        "contamination",
                        field=obs.arm_id,
                    )
                owner = cluster_owner.setdefault(obs.query_cluster_ref, arm.arm_id)
                if owner != arm.arm_id:
                    # The same cluster claimed by two different arms —
                    # bidirectional by construction (first claimant owns it,
                    # any later different-arm claim rejects regardless of
                    # which arm came first).
                    raise BindingRejectedError(
                        registration.experiment_id,
                        "contamination",
                        field=obs.query_cluster_ref,
                    )
            else:
                role_cells.setdefault(arm.role, set()).add(obs.query_cluster_ref)

    for role_a, role_b in _CONTAMINATING_ROLE_PAIRS:
        overlap = role_cells.get(role_a, set()) & role_cells.get(role_b, set())
        if overlap:
            # A cell assigned to one arm role showed up under the opposing
            # role — bidirectional by construction (set intersection is
            # symmetric), so treatment-in-control and control-in-treatment
            # are the same reject.
            raise BindingRejectedError(
                registration.experiment_id,
                "contamination",
                field=sorted(overlap)[0],
            )


def _reject_conflicting_registration(
    registration: ExperimentRegistration, submission: MeasurementSubmission
) -> None:
    """Same `experiment_id` presented with a different content fingerprint than
    the caller's anchored view ⇒ `conflicting_registration`."""
    if registration.content_fingerprint != submission.content_fingerprint:
        raise BindingRejectedError(registration.experiment_id, "conflicting_registration")


def bind_experiment(
    registration: ExperimentRegistration | None,
    submission: MeasurementSubmission,
    *,
    weights: WeightsPolicy,
) -> BoundExperiment:
    """Bind `submission` to `registration`, enforcing every immutability guard.

    `registration` is the located registration (or `None` if the lookup found
    nothing). `submission.anchored_hash` is the trusted audit-ledger anchor.
    `weights` is REQUIRED (omitting it is a `TypeError`, never a silent
    fail-open): pass `WeightsPolicy.enforce(mapping)` to check every
    submission weight against the registered `metric_id -> KPI weight`
    mapping (a differing weight is a `metric_mutation` reject — the
    KPI-weight tampering path), or `WeightsPolicy.not_registered()` as a
    DELIBERATE declaration that the engagement registered no weights (the
    registration model itself carries no weights — see wave5-plan.md).

    Guard order is security-first: the cross-tenant / not-found check runs
    FIRST and is existence-oracle-safe, BEFORE any content-dependent reject
    that could leak whether a registration exists.

    Returns a frozen `BoundExperiment` on success; raises `BindingNotFoundError`
    (absent OR cross-tenant) or `BindingRejectedError` (a located, owned
    registration that failed a guard) otherwise.
    """
    # 1. Existence + tenant, indistinguishable (no existence oracle).
    if registration is None or registration.tenant_id != submission.tenant_id:
        raise BindingNotFoundError(submission.experiment_id)

    # 2. Same id presented with different content than the anchored view.
    _reject_conflicting_registration(registration, submission)

    # 3. Registration integrity vs. the audit-anchored hash.
    _verify_registration_integrity(registration, submission.anchored_hash)

    # 4. Metric immutability (id + content hash + KPI weight per `weights` policy).
    _reject_metric_mutation(registration, submission.metrics, weights)

    # 5. Observation cell conformance.
    _reject_cell_mismatch(registration, submission.observations)

    # 6. Arm-assignment integrity + contamination + asset-hash.
    _reject_contamination(registration, submission.observations)

    return BoundExperiment(
        experiment_id=registration.experiment_id,
        tenant_id=registration.tenant_id,
        anchored_hash=submission.anchored_hash,
        registered_cell=MeasurementCell(
            locale=registration.locale,
            browser_policy=registration.browser_policy,
            query_cluster_ref=registration.query_cluster_ref,
            repeat_count=registration.repeat_count,
        ),
        arm_roles=tuple((arm.arm_id, arm.role) for arm in registration.arms),
        metric_ids=tuple(m.metric_id for m in registration.metric_definitions),
        observations=submission.observations,
    )
