"""saena_domain.execution — shared execution-domain layer for the 5 Wave 3
job kinds (agent-runner, repository-intake, quality-eval, chatgpt-observer,
site-discovery).

Pure/deterministic, no I/O (mirrors `saena_domain.policy`'s discipline):
this package defines the closed `JobKind` vocabulary, the mandatory
`JobContext` execution identity, the job lifecycle state machine, a
canonical `JobError` value object, per-`JobKind` resource-limit defaults,
heartbeat/cancellation/progress `typing.Protocol` interfaces (no
implementation), a v1 engine guard, and event payload builders for the 4
CONFIRMED job-kind events. See `docs/architecture/execution-runtime.md` for
the bounded-context write-up and job/SA mapping.

Spec basis: k3s spec §5.2 (worker pool table) / §5.3 (resource policy),
ADR-0004 (node pool revision — runner pool extension + 3-way ServiceAccount
split), ADR-0007 rev.2 (tenant discriminator survives the withdrawn blanket
partition rule), ADR-0013 (event envelope v1, engine_id closed enum),
ADR-0014 (tenant propagation), ADR-0015 (canonical error model).

Public API:
    JobKind / ExecutionPool / JobKindProfile / JOB_KIND_PROFILES / profile_for
    JobContext
    JobStatus / JobTransitionOutcome / TERMINAL_STATUSES / transition / is_terminal
    JobError / KNOWN_ERROR_CATEGORIES
    ResourceLimits / DEFAULT_RESOURCE_LIMITS / resource_limits_for
    HeartbeatSink / CancellationSignal / ProgressReporter
    ALLOWED_ENGINE_IDS / guard_engine_id
    build_repo_intaken_payload / build_patch_unit_completed_payload /
        build_quality_gate_passed_payload / build_quality_gate_failed_payload /
        build_site_inventory_completed_payload
    ExecutionError and every specific error subclass
"""

from __future__ import annotations

from saena_domain.execution.context import JobContext
from saena_domain.execution.engine import ALLOWED_ENGINE_IDS, guard_engine_id
from saena_domain.execution.errors import (
    EngineDisallowedError,
    EngineNotPermittedError,
    EventPayloadValidationError,
    ExecutionError,
    InvalidJobTransitionError,
    JobContextValidationError,
    JobErrorValidationError,
    ResourceLimitsValidationError,
)
from saena_domain.execution.events import (
    build_patch_unit_completed_payload,
    build_quality_gate_failed_payload,
    build_quality_gate_passed_payload,
    build_repo_intaken_payload,
    build_site_inventory_completed_payload,
)
from saena_domain.execution.job_error import KNOWN_ERROR_CATEGORIES, JobError
from saena_domain.execution.job_kind import (
    JOB_KIND_PROFILES,
    ExecutionPool,
    JobKind,
    JobKindProfile,
    profile_for,
)
from saena_domain.execution.lifecycle import (
    TERMINAL_STATUSES,
    JobStatus,
    JobTransitionOutcome,
    is_terminal,
    transition,
)
from saena_domain.execution.limits import (
    DEFAULT_RESOURCE_LIMITS,
    ResourceLimits,
    resource_limits_for,
)
from saena_domain.execution.protocols import (
    CancellationSignal,
    HeartbeatSink,
    ProgressReporter,
)

__all__ = [
    "ALLOWED_ENGINE_IDS",
    "DEFAULT_RESOURCE_LIMITS",
    "JOB_KIND_PROFILES",
    "KNOWN_ERROR_CATEGORIES",
    "TERMINAL_STATUSES",
    "CancellationSignal",
    "EngineDisallowedError",
    "EngineNotPermittedError",
    "EventPayloadValidationError",
    "ExecutionError",
    "ExecutionPool",
    "HeartbeatSink",
    "InvalidJobTransitionError",
    "JobContext",
    "JobContextValidationError",
    "JobError",
    "JobErrorValidationError",
    "JobKind",
    "JobKindProfile",
    "JobStatus",
    "JobTransitionOutcome",
    "ProgressReporter",
    "ResourceLimits",
    "ResourceLimitsValidationError",
    "build_patch_unit_completed_payload",
    "build_quality_gate_failed_payload",
    "build_quality_gate_passed_payload",
    "build_repo_intaken_payload",
    "build_site_inventory_completed_payload",
    "guard_engine_id",
    "is_terminal",
    "profile_for",
    "resource_limits_for",
    "transition",
]
