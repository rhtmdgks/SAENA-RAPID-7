"""`run_pooled_observation` — the w4-08 browser-pool capture pass.

This is the pool-adapter counterpart to `capture.run_chatgpt_observation`
(W3, `ObservationSourcePort`-based, still unchanged/untouched by this
unit): same engine-guard-then-capture pipeline shape, same per-query audit
trail, but sourcing raw content from a bounded `pool.BrowserPool` of
`pool.BrowserSessionPort` sessions instead of a single injected
`ObservationSourcePort`, and routing every captured raw response through
`artifact_gateway.RawArtifactGatewayPort` (the single gateway — task
instruction: "raw response HTML/screenshot is NEVER stored inline in the
observation") before ever constructing a `PlatformObservation` record.

Per query, in order:

1. `guard_engine_id(engine_id)` — called ONCE, before any query/pool
   interaction happens (same "reject before a single browser session is
   even acquired" discipline as `capture.run_chatgpt_observation`'s own
   engine guard — mission negative test "engine_id google/gemini
   rejected", checked here at the pool-adapter boundary too).
2. `pool.leased_session()` — acquire one pooled `BrowserSessionPort`,
   `render_search_result(query_text=...)`, release (recycling it
   automatically if it is now unhealthy — `BrowserPool.release`'s own
   job, this module never inspects session health itself).
3. `artifact_gateway.put_raw_artifact(tenant_id=..., raw_content=...)` —
   the ONLY place the raw rendered bytes are handed to anything; this
   module never logs them, never returns them to a caller, never embeds
   them in the audit trail or the built record/event.
4. `citation_extractor(raw_content=...)` — an INJECTED, pure
   `bytes -> tuple[str, ...]` callable this module treats as a black box.
   Citation parsing/normalization is citation-intelligence-service's own
   bounded context (`docs/architecture/wave4-plan.md` w4-05); this
   capture-only adapter never derives citation refs from raw content
   itself — a caller with no real extractor yet may pass
   `lambda raw_content: ()` (zero citations is a valid, meaningful
   signal — same "never rejected" discipline `observation.
   PlatformObservation` already documents for the W3 pipeline).
5. `platform_observation_record.build_platform_observation_record(...)` +
   `build_observation_captured_envelope(...)` — the formal P1 contract
   record and its notification event, both schema-validated.
6. An `AuditEntry` (reused from `capture.py` — same shape, no duplicate
   dataclass) is appended for every captured query.

Tenant scoping: `job_context.tenant_id` is the ONLY tenant_id this module
ever passes to the pool/artifact-gateway/record layers — there is no
per-query tenant override parameter anywhere in this module's public
surface, so a caller cannot smuggle a second tenant's data through one
`JobContext`-scoped run (cross-tenant default-deny by construction, task
instruction "tenant_id discriminator mandatory; cross-tenant default-DENY").
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from saena_domain.execution import JobContext, JobStatus, guard_engine_id, transition

from saena_chatgpt_observer.artifact_gateway import RawArtifactGatewayPort
from saena_chatgpt_observer.capture import AuditEntry
from saena_chatgpt_observer.errors import BrowserSessionRenderError, ObservationRetryExhaustedError
from saena_chatgpt_observer.platform_observation_record import (
    build_observation_captured_envelope,
    build_platform_observation_record,
)
from saena_chatgpt_observer.pool import BrowserPool

#: Pure `raw_content -> citation_refs` callable — see module docstring
#: item 4. Never performs I/O; a caller with no real extractor wired up yet
#: may pass a constant-`()` lambda.
CitationExtractor = Callable[[bytes], tuple[str, ...]]


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_observation_id(run_id: str, index: int) -> str:
    # Deterministic, dependency-free default — a caller that wants a
    # globally-unique id (e.g. `saena_domain.events.generate_uuid7()`)
    # injects its own `observation_id_factory` instead; this module never
    # hardcodes UUID generation as the ONLY option (mirrors `capture.py`'s
    # own `clock`-injectable-for-determinism discipline).
    return f"{run_id}-{index:04d}"


@dataclass(frozen=True, slots=True)
class PooledObservationResult:
    """One query's captured result: the formal P1 `PlatformObservation`
    record dict, its `observation.captured.v1` envelope dict, and the raw
    artifact's opaque ref (for a caller/test that wants to assert the
    artifact-gateway round trip without ever handling raw bytes itself)."""

    observation_record: dict[str, Any]
    observation_captured_envelope: dict[str, Any]
    raw_object_ref: str
    artifact_hash: str


@dataclass(frozen=True, slots=True)
class PooledObservationRunResult:
    """`run_pooled_observation`'s return value."""

    results: tuple[PooledObservationResult, ...]
    audit_trail: tuple[AuditEntry, ...]
    final_status: JobStatus


def run_pooled_observation(
    *,
    job_context: JobContext,
    pool: BrowserPool,
    artifact_gateway: RawArtifactGatewayPort,
    engine_id: str,
    queries: Sequence[str],
    citation_extractor: CitationExtractor = lambda raw_content: (),  # noqa: ARG005
    observation_id_factory: Callable[[str, int], str] = _default_observation_id,
    clock: Callable[[], str] = _utc_now_iso,
) -> PooledObservationRunResult:
    """Run one read-only browser-pool observation pass over `queries`.

    `observation_id_factory(run_id, index)` and `clock()` are both
    injectable so this function is fully deterministic in the unit lane
    (task instruction: "Deterministic in the unit lane; inject clock/
    ids"). `pool`/`artifact_gateway` are always caller-provided — in the
    unit lane always `pool.FixtureBrowserSessionFactory`-backed
    `BrowserPool` + `artifact_gateway.FakeArtifactGateway`; the real
    Playwright pool / HTTP artifact-registry adapter are wired up by a
    later integration/deploy unit, never constructed by this module
    itself (single-gateway + fixture-vs-real-driver discipline, see
    `pool.py`/`artifact_gateway.py`/`playwright_driver.py` docstrings).
    """
    guard_engine_id(engine_id)

    status = JobStatus.PENDING
    status = transition(status, JobStatus.RUNNING).status

    results: list[PooledObservationResult] = []
    audit_trail: list[AuditEntry] = []

    try:
        for index, query_text in enumerate(queries):
            try:
                with pool.leased_session() as session:
                    raw_content = session.render_search_result(query_text=query_text)
            except BrowserSessionRenderError as exc:
                raise ObservationRetryExhaustedError(
                    f"pooled capture failed for query {query_text!r}: {exc}",
                    context={"query_text": query_text},
                ) from exc

            artifact_ref = artifact_gateway.put_raw_artifact(
                tenant_id=job_context.tenant_id, raw_content=raw_content
            )
            citation_refs = citation_extractor(raw_content)
            observation_id = observation_id_factory(job_context.run_id, index)
            captured_at = clock()

            observation_record = build_platform_observation_record(
                tenant_id=job_context.tenant_id,
                run_id=job_context.run_id,
                engine_id=engine_id,
                observation_id=observation_id,
                raw_object_ref=artifact_ref.raw_object_ref,
                artifact_hash=artifact_ref.artifact_hash,
                citation_refs=citation_refs,
                captured_at=captured_at,
            )
            envelope = build_observation_captured_envelope(
                tenant_id=job_context.tenant_id,
                run_id=job_context.run_id,
                engine_id=engine_id,
                observation_id=observation_id,
                artifact_hash=artifact_ref.artifact_hash,
                idempotency_key=f"{job_context.tenant_id}:{job_context.run_id}:{observation_id}",
            )
            results.append(
                PooledObservationResult(
                    observation_record=observation_record,
                    observation_captured_envelope=envelope,
                    raw_object_ref=artifact_ref.raw_object_ref,
                    artifact_hash=artifact_ref.artifact_hash,
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
    except ObservationRetryExhaustedError:
        transition(status, JobStatus.FAILED)
        raise

    status = transition(status, JobStatus.SUCCEEDED).status

    return PooledObservationRunResult(
        results=tuple(results),
        audit_trail=tuple(audit_trail),
        final_status=status,
    )


__all__ = [
    "CitationExtractor",
    "PooledObservationResult",
    "PooledObservationRunResult",
    "run_pooled_observation",
]
