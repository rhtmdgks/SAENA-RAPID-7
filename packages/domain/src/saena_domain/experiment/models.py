"""`ExperimentRegistration` — the immutable pre-registration record (w4-09).

Source specification references (READ ONLY basis for this module):
- docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md §3.7 (7일 실험 설계:
  Query Cluster/locale/browser policy/반복 횟수를 Day 0에 고정 등록; treatment
  asset과 control asset 또는 matched query cluster; asset hash/code version
  이 관측에 붙는다).
- docs/decisions/ADR-0007-final-synthesis-ownership-topology.md (D-3: TAG
  projection/실험 outcome = experiment-attribution-service, read-only CQRS —
  outcome computation lives downstream of THIS module, not in it).
- packages/contracts/json-schema/context/run-context-experiment/v1/
  run-context-experiment.schema.json ("사전등록 불변성 — 등록 시점 hash를
  audit-ledger에 앵커링") — the precedent this module's `previous_hash`
  anchor-chain field generalizes into an append-only ledger.

Scope discipline: this module is REGISTRATION ONLY. It has no field and no
method that could carry an observed/computed outcome, effect size, lift,
delta, or DiD/causal estimate — that is Wave 5's job (experiment-attribution
outcome projection). `tests/unit/domain_experiment/test_no_outcome_fields.py`
pins this as an executable assertion, not just a comment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Case-insensitive substrings that, if present in any field name on any
#: model in this module, would indicate an outcome/effect/causal-estimate
#: field has crept into what must remain a pure registration record. Used by
#: the pinned regression test (never imported by production hashing/ledger
#: logic — this is a design-time guard, not a runtime one).
FORBIDDEN_OUTCOME_TOKENS: tuple[str, ...] = (
    "lift",
    "outcome",
    "delta",
    "effect",
    "uplift",
    "causal",
    "did",
    "p_value",
    "pvalue",
    "significance",
    "observed_value",
    "result",
    "estimate",
)

ArmRole = Literal["baseline", "treatment", "control", "matched_cluster"]


class ExperimentArm(BaseModel):
    """One arm of an experiment's design — WHAT is being compared, not what happened.

    Design §3.7.2: "treatment asset와 control asset 또는 matched query
    cluster를 설정한다" — exactly one `baseline` arm is required, plus either
    an asset-comparison design (`treatment`/`control` arms carrying
    `asset_ref`) OR a matched-query-cluster design (`matched_cluster` arms
    carrying `query_cluster_ref`), never a mix of the two (enforced by
    `ExperimentRegistration._check_arm_design`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm_id: str = Field(min_length=1)
    role: ArmRole
    asset_ref: str | None = Field(default=None, min_length=1)
    query_cluster_ref: str | None = Field(default=None, min_length=1)


class MetricDefinition(BaseModel):
    """The DEFINITION of a metric this experiment will observe — never a value.

    Registering a metric definition records what will be measured and how;
    it deliberately carries no slot for an observed number, a comparison
    result, or a significance judgement (see `FORBIDDEN_OUTCOME_TOKENS`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ExperimentRegistration(BaseModel):
    """One append-only, pre-registered experiment design entry.

    Every field the w4-09 mission lists is present verbatim. `canonical_hash`
    and `previous_hash` are `None` on a freshly constructed registration (the
    caller has not yet appended it to a ledger) and are populated by
    `saena_domain.experiment.ledger.register`, which returns a NEW instance
    (`model_copy`, since this model is `frozen=True`) with both hash fields
    filled in — mirroring `saena_domain.audit.chain.build_entry`'s pattern of
    constructing the hash-bearing entry only once its position in the chain
    is known.

    `tenant_id` is mandatory (ADR-0007 rev.2 D-3 tenant-discriminator rule:
    every tenant-scoped record carries a `tenant_id` field; there is no
    system-scope carve-out for experiment registrations, unlike
    `saena_domain.audit.AuditEntry`'s `scope="system"` case).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    arms: tuple[ExperimentArm, ...] = Field(min_length=2)
    metric_definitions: tuple[MetricDefinition, ...] = Field(min_length=1)
    query_cluster_ref: str = Field(min_length=1)
    locale: str = Field(min_length=1)
    browser_policy: str = Field(min_length=1)
    repeat_count: int = Field(gt=0)
    asset_hash: str = Field(min_length=1)
    code_version_hash: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    created_at: datetime
    canonical_hash: str | None = None
    previous_hash: str | None = None

    @model_validator(mode="after")
    def _check_arm_design(self) -> ExperimentRegistration:
        arm_ids = [arm.arm_id for arm in self.arms]
        if len(arm_ids) != len(set(arm_ids)):
            raise ValueError("arm_id values must be unique within a registration")

        roles = [arm.role for arm in self.arms]
        if roles.count("baseline") != 1:
            raise ValueError("arms must contain exactly one 'baseline' arm")

        non_baseline_roles = {r for r in roles if r != "baseline"}
        if not non_baseline_roles:
            raise ValueError(
                "arms must contain at least one non-baseline arm "
                "(treatment/control asset design, or matched_cluster design)"
            )

        asset_design_roles = {"treatment", "control"}
        is_matched_cluster_design = non_baseline_roles == {"matched_cluster"}
        is_asset_design = non_baseline_roles <= asset_design_roles
        if not (is_matched_cluster_design or is_asset_design):
            raise ValueError(
                "non-baseline arms must be either an asset design "
                "(treatment/control only) or a matched_cluster design "
                "(matched_cluster only) — mixing the two is not permitted "
                "(design §3.7.2)"
            )
        return self
