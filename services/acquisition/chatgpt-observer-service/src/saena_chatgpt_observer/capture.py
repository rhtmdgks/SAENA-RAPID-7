"""`run_chatgpt_observation` — the `JobKind.CHATGPT_OBSERVER` capture pass.

W3 MINIMAL scope (explicit non-goals, per this unit's own task
instruction): this module does NOT implement a real browser pool/Playwright
fleet (W4, see `source.ObservationSourcePort`'s docstring), does NOT do any
citation-intelligence/experiment-attribution analysis over the captured
observations, and this unit's own event payload builder is deliberately
absent — `observation.captured.v1` (this `JobKind`'s own event) is named in
`docs/architecture/execution-runtime.md` "Deferred to later units" as OUT
of the w3-01 founding unit's scope precisely because, unlike the 4 events
that unit DOES build payloads for, it requires `payload.engine_id`
(ADR-0013 observation/citation/experiment family rule) and was left for a
later unit; this patch unit still does not add it (out of THIS unit's named
deliverables too — deliverable 7-9 name capture/observation/rate-limiting,
never event emission) — a later unit owns `build_observation_captured_payload`.

Pipeline per query, in order:

1. `guard_engine_id(engine_id)` — called ONCE, before any query is
   attempted, so a disallowed `engine_id` (`google-aio`/`gemini`/anything
   else) is rejected before a single observation source call happens
   (mission negative test: "engine_id google/gemini rejected").
2. `source.capture_observation(query_text=...)` — wrapped in a bounded
   retry loop (`ObservationBudget.max_retries`) that catches
   `TransientCaptureError` only.
3. An `AuditEntry` is appended for every captured query (deliverable 7/8's
   "audit trail").

Before the loop starts, the whole run is bounds-checked against
`ObservationBudget.max_queries_per_run` (rate limit) and, during the loop,
against `ObservationBudget.active_deadline_seconds` via an injectable
`clock` (timeout) — both raise a typed, retryable `ChatgptObserverError`
subclass.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from saena_domain.execution import JobContext, JobKind, JobStatus, guard_engine_id, transition

from saena_chatgpt_observer.budget import ObservationBudget, observation_budget_for
from saena_chatgpt_observer.errors import (
    ObservationBudgetExceededError,
    ObservationDeadlineExceededError,
    ObservationRetryExhaustedError,
)
from saena_chatgpt_observer.observation import PlatformObservation
from saena_chatgpt_observer.source import ObservationSourcePort, TransientCaptureError

# `run_chatgpt_observation` never hardcodes a default `engine_id` — callers
# always pass it explicitly, so a future 2nd engine (ADR-0007: "2번째 엔진 =
# 동일 계약을 쓰는 신규 observer, core 재작업 0") never requires editing
# this function's signature, only its own `guard_engine_id`-permitted value.


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One audit-trail line for a single query capture within an
    observation run — carries `JobContext`'s tenant/actor identity
    directly, same discipline as `saena_site_discovery.inventory.AuditEntry`."""

    tenant_id: str
    actor_id: str
    run_id: str
    query_text: str
    action: str  # "captured"
    recorded_at: str


@dataclass(frozen=True, slots=True)
class ChatgptObserverRunResult:
    """`run_chatgpt_observation`'s return value: every captured
    `PlatformObservation`, the run's audit trail, and its final
    `JobStatus`. NO event payload here — see module docstring."""

    observations: tuple[PlatformObservation, ...]
    audit_trail: tuple[AuditEntry, ...]
    final_status: JobStatus


def _capture_with_retries(
    source: ObservationSourcePort, query_text: str, *, max_retries: int
) -> tuple[tuple[str, ...], str]:
    attempt = 0
    while True:
        try:
            captured = source.capture_observation(query_text=query_text)
        except TransientCaptureError:
            attempt += 1
            if attempt > max_retries:
                raise ObservationRetryExhaustedError(
                    f"query {query_text!r} exceeded {max_retries} retries",
                    context={"query_text": query_text, "max_retries": max_retries},
                ) from None
            continue
        return captured.citation_refs, captured.raw_object_ref


def run_chatgpt_observation(
    *,
    job_context: JobContext,
    source: ObservationSourcePort,
    engine_id: str,
    queries: Sequence[str],
    budget: ObservationBudget | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ChatgptObserverRunResult:
    """Run one read-only `JobKind.CHATGPT_OBSERVER` capture pass over
    `queries` and return the captured `ChatgptObserverRunResult`.

    `budget` defaults to `observation_budget_for(JobKind.CHATGPT_OBSERVER)`;
    a caller may inject an override only for testing this function's own
    budget-enforcement branches deterministically (`clock` is always
    injectable for the same reason).
    """
    # Engine guard FIRST, before any budget check or source call — a
    # disallowed engine_id must never trigger even a single observation
    # attempt.
    guard_engine_id(engine_id)

    effective_budget = (
        budget if budget is not None else observation_budget_for(JobKind.CHATGPT_OBSERVER)
    )

    if len(queries) > effective_budget.max_queries_per_run:
        raise ObservationBudgetExceededError(
            f"{len(queries)} queries requested exceeds this run's budget of "
            f"{effective_budget.max_queries_per_run}",
            context={
                "requested_queries": len(queries),
                "max_queries_per_run": effective_budget.max_queries_per_run,
            },
        )

    status = JobStatus.PENDING
    status = transition(status, JobStatus.RUNNING).status

    started_at = clock()
    observations: list[PlatformObservation] = []
    audit_trail: list[AuditEntry] = []

    try:
        for query_text in queries:
            elapsed = clock() - started_at
            if elapsed > effective_budget.active_deadline_seconds:
                raise ObservationDeadlineExceededError(
                    f"observation run exceeded its "
                    f"{effective_budget.active_deadline_seconds}s deadline",
                    context={
                        "elapsed_seconds": elapsed,
                        "active_deadline_seconds": effective_budget.active_deadline_seconds,
                        "queries_completed": len(observations),
                        "queries_requested": len(queries),
                    },
                )

            citation_refs, raw_object_ref = _capture_with_retries(
                source, query_text, max_retries=effective_budget.max_retries
            )
            observations.append(
                PlatformObservation(
                    engine_id=engine_id,
                    tenant_id=job_context.tenant_id,
                    run_id=job_context.run_id,
                    query_text=query_text,
                    citation_refs=citation_refs,
                    raw_object_ref=raw_object_ref,
                    observed_at=_utc_now_iso(),
                )
            )
            audit_trail.append(
                AuditEntry(
                    tenant_id=job_context.tenant_id,
                    actor_id=job_context.actor_id,
                    run_id=job_context.run_id,
                    query_text=query_text,
                    action="captured",
                    recorded_at=_utc_now_iso(),
                )
            )
    except (ObservationDeadlineExceededError, ObservationRetryExhaustedError):
        transition(status, JobStatus.FAILED)
        raise

    status = transition(status, JobStatus.SUCCEEDED).status

    return ChatgptObserverRunResult(
        observations=tuple(observations),
        audit_trail=tuple(audit_trail),
        final_status=status,
    )


__all__ = ["AuditEntry", "ChatgptObserverRunResult", "run_chatgpt_observation"]
