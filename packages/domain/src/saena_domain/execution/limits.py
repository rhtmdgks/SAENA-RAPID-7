"""Per-`JobKind` resource limit defaults (k3s spec §5.3 resource policy).

k3s spec §5.3: "Agent runner는 `activeDeadlineSeconds`, max retry, maximum
artifact size, max token/cost budget을 가진다." `ResourceLimits` is this
module's typed carrier for those 4 fields, generalized to all 5 `JobKind`
members (§5.3 names agent-runner explicitly as the example, but the same
section's blanket rule — "모든 Deployment/Job에 CPU/memory request와
limit을 강제한다" — applies per-Job budget discipline to every k3s Job this
package models, not an agent-runner-only carve-out).

**SOURCE OF DEFAULT VALUES — read this before trusting a number below:**

- `JobKind.AGENT_RUNNER`'s `active_deadline_seconds` / `max_cost_usd` /
  `max_artifact_mib` are copied VERBATIM from
  `deploy/charts/saena-forge/values.yaml`
  (`agentRunner.job.activeDeadlineSeconds: 7200`,
  `agentRunner.limits.maxCostUsdPerRun: 100`,
  `agentRunner.limits.maxArtifactsMiBPerRun: 1024`) — this is the ONLY
  `JobKind` with a values.yaml source. `max_retries` has NO values.yaml
  field at all in that chart (only `ttlSecondsAfterFinished: 1800`, a K8s
  Job TTL-after-finish setting, not a retry count) — its default of `3`
  below is this module's own placeholder, not a confirmed ops value.
- The other 4 `JobKind` members (`REPOSITORY_INTAKE`, `QUALITY_EVAL`,
  `CHATGPT_OBSERVER`, `SITE_DISCOVERY`) have NO values.yaml section in this
  chart yet. Every number below for them is this module's own reasoned
  proposal (scaled down from agent-runner's budget by each kind's
  pool/read-only profile — see `job_kind.py`: runner-pool build/intake jobs
  get a shorter deadline and a fraction of agent-runner's cost budget;
  browser-pool observation/crawl jobs get the smallest budgets of all).
  These are **NOT CONFIRMED spec values** — a later patch unit that adds
  each service's own Helm values section should reconcile this table
  against that authoritative source and update it, not silently diverge
  from it.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.execution.errors import ResourceLimitsValidationError
from saena_domain.execution.job_kind import JobKind


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """k3s spec §5.3's 4 named per-Job budget fields."""

    active_deadline_seconds: int
    max_retries: int
    max_artifact_mib: int
    max_cost_usd: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("active_deadline_seconds", self.active_deadline_seconds),
            ("max_retries", self.max_retries),
            ("max_artifact_mib", self.max_artifact_mib),
            ("max_cost_usd", self.max_cost_usd),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ResourceLimitsValidationError(
                    f"{field_name} must be a positive int, got {value!r}",
                    context={"field": field_name, "value": value},
                )


# See module docstring "SOURCE OF DEFAULT VALUES" — only AGENT_RUNNER's 3 of
# 4 fields are values.yaml-sourced; everything else here is this module's
# own reasoned proposal, not CONFIRMED ops config.
DEFAULT_RESOURCE_LIMITS: dict[JobKind, ResourceLimits] = {
    JobKind.AGENT_RUNNER: ResourceLimits(
        active_deadline_seconds=7200,
        max_retries=3,
        max_artifact_mib=1024,
        max_cost_usd=100,
    ),
    JobKind.REPOSITORY_INTAKE: ResourceLimits(
        active_deadline_seconds=1800,
        max_retries=3,
        max_artifact_mib=256,
        max_cost_usd=10,
    ),
    JobKind.QUALITY_EVAL: ResourceLimits(
        active_deadline_seconds=3600,
        max_retries=2,
        max_artifact_mib=512,
        max_cost_usd=25,
    ),
    JobKind.CHATGPT_OBSERVER: ResourceLimits(
        active_deadline_seconds=900,
        max_retries=3,
        max_artifact_mib=64,
        max_cost_usd=5,
    ),
    JobKind.SITE_DISCOVERY: ResourceLimits(
        active_deadline_seconds=1800,
        max_retries=3,
        max_artifact_mib=128,
        max_cost_usd=5,
    ),
}


def resource_limits_for(kind: JobKind) -> ResourceLimits:
    """Return the default `ResourceLimits` for `kind`.

    `DEFAULT_RESOURCE_LIMITS` covers every `JobKind` member (asserted by
    this package's unit tests) so this never raises `KeyError` for a valid
    `JobKind` value.
    """
    return DEFAULT_RESOURCE_LIMITS[kind]


__all__ = [
    "DEFAULT_RESOURCE_LIMITS",
    "ResourceLimits",
    "resource_limits_for",
]
