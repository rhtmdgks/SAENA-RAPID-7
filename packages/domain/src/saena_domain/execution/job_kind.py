"""`JobKind` — closed v1 enum of the 5 Wave 3 execution-domain job kinds.

Canonical names/roster: k3s spec §5.2 worker pool table (`runner`/`browser`
columns) + ADR-0004 (node pool revision — untrusted Jobs and compute pool,
"runner pool 확장" + 3-way ServiceAccount split + browser pool sub-profile
differentiation) + the Wave 3 job roster this patch unit's mission names
verbatim (agent-runner, repository-intake, quality-eval, chatgpt-observer,
site-discovery — the 5 services whose AsyncAPI producer ids are confirmed in
`packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml` operations).

`JOB_KIND_PROFILES` fixes 4 static boundary facts per kind:

- `pool`: which k3s §5.2 worker pool (`runner` or `browser`) hosts this
  kind's Jobs. ADR-0004 Current decision item 1: "customer source를 다루는
  모든 Job은 runner pool 상속" — agent-runner + repository-intake +
  quality-eval all land on `runner`; item 2 puts chatgpt-observer and
  site-discovery on `browser` with "권한 차등" (differentiated permissions,
  captured here via `read_only` + `service_account`, not by this module
  encoding pod-level RBAC itself).
- `read_only`: Git-write CAPABILITY specifically (not general filesystem
  read-only-ness) — ADR-0004's 3-way runner-pool ServiceAccount split states
  this explicitly per kind: agent-runner gets worktree write (contract-scope
  files only); quality-eval gets "빌드 실행 권한만, Git write 없음" (build
  execution only, no Git write — it still writes to an ephemeral build
  directory, so `read_only=True` here means "no Git write", not "makes no
  writes at all"); repository-intake gets "read-only Git만". The two
  browser-pool kinds are both read-only by ADR-0004 item 2 (chatgpt-observer
  = observation only; site-discovery = "read-only 크롤, Git credential
  미발급 sub-profile").
- `service_account`: the k3s ServiceAccount name each kind's Job runs under.
  `saena-agent-runner` is CONFIRMED (`deploy/charts/saena-forge/values.yaml`
  `agentRunner.job.serviceAccount`); the other 4 have no chart section yet —
  their names below follow that same `saena-<kind>` convention as this
  module's own proposal, to be reconciled against each service's own Helm
  values section when that lands (see `limits.py`'s equivalent sourcing
  note for the same caveat pattern).
- `producer_id`: the AsyncAPI producer identifier this kind's service uses
  when emitting its event (confirmed against
  `packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml` `operations.*.
  summary` "<producer> produces <event_type>." strings for all 5 —
  `saena_domain.execution.events`' payload builders and any later envelope
  construction should use these values verbatim as `EnvelopeFactory`'s
  `producer=` argument).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExecutionPool(StrEnum):
    """k3s spec §5.2 worker pool labels relevant to the 5 Wave 3 job kinds.

    Only `runner` and `browser` are relevant here — §5.2's other 3 pools
    (`control`/`data`/`gpu-optional`) never host a `JobKind` Job:
    control/data explicitly forbid agent-runner-class workloads (§5.2
    "위험 격리" column), and gpu-optional is out of scope for these 5 kinds
    (local embedding/reranking only, ADR-0004 Open decisions).
    """

    RUNNER = "runner"
    BROWSER = "browser"


class JobKind(StrEnum):
    """Closed v1 set of Wave 3 execution-domain job kinds."""

    AGENT_RUNNER = "agent_runner"
    REPOSITORY_INTAKE = "repository_intake"
    QUALITY_EVAL = "quality_eval"
    CHATGPT_OBSERVER = "chatgpt_observer"
    SITE_DISCOVERY = "site_discovery"


@dataclass(frozen=True, slots=True)
class JobKindProfile:
    """Static, per-`JobKind` boundary facts — see module docstring for the
    authority behind each field."""

    kind: JobKind
    pool: ExecutionPool
    read_only: bool
    service_account: str
    producer_id: str


JOB_KIND_PROFILES: dict[JobKind, JobKindProfile] = {
    JobKind.AGENT_RUNNER: JobKindProfile(
        kind=JobKind.AGENT_RUNNER,
        pool=ExecutionPool.RUNNER,
        read_only=False,
        service_account="saena-agent-runner",
        producer_id="agent-runner-service",
    ),
    JobKind.REPOSITORY_INTAKE: JobKindProfile(
        kind=JobKind.REPOSITORY_INTAKE,
        pool=ExecutionPool.RUNNER,
        read_only=True,
        service_account="saena-repository-intake",
        producer_id="repository-intake-service",
    ),
    JobKind.QUALITY_EVAL: JobKindProfile(
        kind=JobKind.QUALITY_EVAL,
        pool=ExecutionPool.RUNNER,
        read_only=True,
        service_account="saena-quality-eval",
        producer_id="quality-eval-service",
    ),
    JobKind.CHATGPT_OBSERVER: JobKindProfile(
        kind=JobKind.CHATGPT_OBSERVER,
        pool=ExecutionPool.BROWSER,
        read_only=True,
        service_account="saena-chatgpt-observer",
        producer_id="chatgpt-observer-service",
    ),
    JobKind.SITE_DISCOVERY: JobKindProfile(
        kind=JobKind.SITE_DISCOVERY,
        pool=ExecutionPool.BROWSER,
        read_only=True,
        service_account="saena-site-discovery",
        producer_id="site-discovery-service",
    ),
}


def profile_for(kind: JobKind) -> JobKindProfile:
    """Return the static boundary-fact profile for `kind`.

    `JOB_KIND_PROFILES` covers every `JobKind` member (asserted by this
    package's unit tests) so this never raises `KeyError` for a valid
    `JobKind` value.
    """
    return JOB_KIND_PROFILES[kind]


__all__ = [
    "JOB_KIND_PROFILES",
    "ExecutionPool",
    "JobKind",
    "JobKindProfile",
    "profile_for",
]
