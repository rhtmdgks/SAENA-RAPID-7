"""``ExperimentOutcome`` — the pipeline's terminal, always-honest output record.

Shaped to match the eventual `domain/experiment-outcome/v1` contract
(wave5-plan.md w5-02 deliverable, NOT YET landed in this worktree — w5-02 is a
Stage-1 sibling unit this patch unit does not depend on and must not
anticipate the exact wire shape of). This module defines the DOMAIN-LEVEL
value object the pipeline emits; `packages/contracts/**` is out of this
unit's exclusive paths (Integrator/w5-02-owned) and is never touched here.
When w5-02 lands the JSON-Schema contract, the service boundary (w5-12) is
the place a `saena_schemas.event.*` payload model gets built FROM this
record — this module stays contract-agnostic on purpose.

## Verdict vs. status: never collapsed

`OutcomeStatus` mirrors `saena_domain.measurement.b_gate.BVerdict` exactly
(`PASS` / `FAIL` / `UNDETERMINED`) PLUS nothing else — the pipeline never
invents a fourth status and never maps a B-gate verdict onto anything but its
own name. A record whose `status` is `PASS` is the ONLY status a downstream
consumer (skill-bank intake, w5-16) may treat as "B-verified"; `UNDETERMINED`
and `FAIL` are both explicitly-not-PASS and must never be silently upgraded.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from saena_domain.measurement.b_gate import BGateDecision, BVerdict
from saena_domain.measurement.grs import GrsDecision
from saena_domain.measurement.reason_codes import ReasonCode


class OutcomeStatus(str, Enum):
    """The outcome record's status — a 1:1 mirror of `BVerdict`, nothing more.

    `str` mixin so it serializes to its wire value directly, matching every
    other closed enum in `saena_domain.measurement`.
    """

    PASS = "pass"
    FAIL = "fail"
    UNDETERMINED = "undetermined"

    @classmethod
    def from_b_verdict(cls, verdict: BVerdict) -> OutcomeStatus:
        """The ONLY place a `BVerdict` becomes an `OutcomeStatus` — a pure
        1:1 rename, never a collapse/upgrade of one verdict into another."""
        return cls(verdict.value)


class ExperimentOutcome(BaseModel):
    """The pipeline's terminal record — ALWAYS produced, even on fail-closed.

    Every measurement run — happy path or any fail-closed branch — ends in
    exactly one `ExperimentOutcome`. `status` is never `PASS` unless every
    upstream step (GRS input recorded, binding admitted, window complete +
    deployment confirmed, DiD sufficient, B-gate PASS) actually succeeded;
    `reason_codes` names every contributing reason (empty ONLY on a clean
    PASS with GRS eligible and no duplicate-basis note). `evidence_bundle_ref`
    is the sealed evidence-bundle manifest's content hash — ALWAYS present
    (a bundle is sealed on every path, PASS or not; an incomplete bundle
    still seals, carrying a `missingness_report` entry, per E5/E1 honesty).

    `grs_decision` is carried through in full (never summarized away) so a
    consumer can see whether GRS eligibility was itself evaluated, DENY'd, or
    UNDETERMINED (`grs_policy_missing`) — independent of the B-gate verdict;
    the pipeline never lets a GRS outcome silently influence `status` (GRS and
    B-gate are two independent fail-closed judgements per wave5-plan.md
    deliverables 3 and 5, composed but not conflated).

    Frozen + `extra="forbid"`: an outcome record, once built, cannot acquire
    an undeclared field or be mutated in place.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    status: OutcomeStatus
    reason_codes: tuple[ReasonCode, ...]
    qualifying_layers: tuple[str, ...]
    raw_view: tuple[str, ...]
    control_adjusted_view: tuple[str, ...]
    b_gate_decision: BGateDecision | None
    grs_decision: GrsDecision | None
    evidence_bundle_ref: str | None
    evidence_bundle_complete: bool
    policy_version: str
    policy_hash: str
    is_production: bool
    computed_at: datetime

    def canonical_payload(self) -> dict[str, object]:
        """A deterministic, JSON-mode dict of this record's content.

        Used by the orchestrator's determinism/idempotency checks (byte-
        identical outcome record for byte-identical inputs) and by the
        `OutcomeDecisionRecord` the pipeline appends — NEVER re-derives
        content, only re-serializes this record's own fields.
        """
        return self.model_dump(mode="json")


__all__ = ["ExperimentOutcome", "OutcomeStatus"]
