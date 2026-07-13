"""Heartbeat/cancellation/progress Protocol interfaces — pure shape checks.

No implementation lives in this package (later Wave 3 units own that) — these
tests only prove the Protocols are runtime-checkable and that a minimal
duck-typed stand-in satisfies each one, i.e. the shape is usable by a future
implementation without importing anything beyond `JobContext`.
"""

from __future__ import annotations

from saena_domain.execution.context import JobContext
from saena_domain.execution.protocols import (
    CancellationSignal,
    HeartbeatSink,
    ProgressReporter,
)

_CTX = JobContext(
    tenant_id="acme-co",
    workspace_id="ws-1",
    project_id="proj-1",
    run_id="run-1",
    trace_id="a" * 32,
    idempotency_key="k1",
    actor_id="actor-1",
)


class _FakeHeartbeatSink:
    def __init__(self) -> None:
        self.calls: list[tuple[JobContext, int]] = []

    def heartbeat(self, *, job_context: JobContext, sequence: int) -> None:
        self.calls.append((job_context, sequence))


class _FakeCancellationSignal:
    def __init__(self, *, cancelled: bool) -> None:
        self._cancelled = cancelled

    def is_cancellation_requested(self, *, job_context: JobContext) -> bool:
        return self._cancelled


class _FakeProgressReporter:
    def __init__(self) -> None:
        self.calls: list[tuple[JobContext, float, str | None]] = []

    def report_progress(
        self,
        *,
        job_context: JobContext,
        fraction_complete: float,
        message: str | None = None,
    ) -> None:
        self.calls.append((job_context, fraction_complete, message))


def test_heartbeat_sink_duck_type_satisfies_protocol() -> None:
    sink = _FakeHeartbeatSink()
    assert isinstance(sink, HeartbeatSink)
    sink.heartbeat(job_context=_CTX, sequence=1)
    assert sink.calls == [(_CTX, 1)]


def test_cancellation_signal_duck_type_satisfies_protocol() -> None:
    signal = _FakeCancellationSignal(cancelled=True)
    assert isinstance(signal, CancellationSignal)
    assert signal.is_cancellation_requested(job_context=_CTX) is True


def test_progress_reporter_duck_type_satisfies_protocol() -> None:
    reporter = _FakeProgressReporter()
    assert isinstance(reporter, ProgressReporter)
    reporter.report_progress(job_context=_CTX, fraction_complete=0.5, message="halfway")
    assert reporter.calls == [(_CTX, 0.5, "halfway")]


def test_object_missing_the_method_does_not_satisfy_protocol() -> None:
    class _NotASink:
        pass

    assert not isinstance(_NotASink(), HeartbeatSink)
    assert not isinstance(_NotASink(), CancellationSignal)
    assert not isinstance(_NotASink(), ProgressReporter)
