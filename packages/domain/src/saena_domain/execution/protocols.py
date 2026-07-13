"""Heartbeat / cancellation / progress protocol interfaces.

Pure `typing.Protocol` structural-typing interfaces — NO implementation, NO
I/O. Implementations live in the services that actually run Wave 3 Jobs
(agent-runner / repository-intake / quality-eval / chatgpt-observer /
site-discovery services — later Wave 3 units) and talk to whatever real
transport they use (Temporal heartbeat, K8s Job status polling, an SSE
stream, ...). This module only fixes the call SHAPE those implementations
must satisfy, so pure-domain code in this package (and later units) can
depend on the shape without depending on any one transport — exactly the
"typed I/O ports, no I/O in the domain layer" split
`saena_domain.persistence.ports` already establishes for storage; this is
the same pattern applied to the runtime-signal side of a Job's lifecycle.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from saena_domain.execution.context import JobContext


@runtime_checkable
class HeartbeatSink(Protocol):
    """Liveness signal sink a running Job pushes to periodically."""

    def heartbeat(self, *, job_context: JobContext, sequence: int) -> None:
        """Record that the job identified by `job_context` is still alive.

        `sequence` is a caller-owned monotonic counter (not a timestamp —
        the sink implementation is responsible for stamping wall-clock time
        on receipt) so an implementation can detect out-of-order/duplicate
        delivery under at-least-once retry (ADR-0013 delivery semantics).
        """
        ...


@runtime_checkable
class CancellationSignal(Protocol):
    """Cooperative cancellation check a running Job polls."""

    def is_cancellation_requested(self, *, job_context: JobContext) -> bool:
        """Return `True` iff cancellation has been requested for this job.

        Implementations must be safe to call frequently — a running Job is
        expected to poll this between units of work — so no I/O-heavy
        synchronous call should be hidden behind this shape without its own
        caching/backoff; that concern belongs to the implementation, not
        this Protocol.
        """
        ...


@runtime_checkable
class ProgressReporter(Protocol):
    """Progress-fraction sink a running Job pushes to periodically."""

    def report_progress(
        self,
        *,
        job_context: JobContext,
        fraction_complete: float,
        message: str | None = None,
    ) -> None:
        """Record progress. `fraction_complete` is expected to be in
        `[0.0, 1.0]` — implementations are responsible for validating/
        clamping it themselves; this Protocol fixes the call shape only,
        not I/O-adjacent validation behavior, which is out of this
        pure-domain package's scope.
        """
        ...


__all__ = ["CancellationSignal", "HeartbeatSink", "ProgressReporter"]
