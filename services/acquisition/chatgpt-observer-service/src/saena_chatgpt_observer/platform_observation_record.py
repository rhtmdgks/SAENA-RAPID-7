"""`build_platform_observation_record` / `build_observation_captured_envelope`
— the formal P1 `PlatformObservation` domain contract + its
`observation.captured.v1` notification event, both landed by w4-10
(Contracts Steward) and consumed here for the first time.

`README.md`/`observation.py`'s own docstrings note this package's local
`PlatformObservation` dataclass predates the formal
`packages/contracts`-backed schema (w4-10 landed
`saena_schemas.domain.platform_observation_v1.PlatformObservation` +
`saena_schemas.event.observation_captured_v1.ObservationCapturedV1Payload`,
this unit's own task instruction: "via
`saena_schemas.domain.platform_observation_v1`" / "via
`saena_domain.events.factory`"). This module is the bridge: it builds and
validates the GENERATED contract model directly (no duplicate DTO,
ADR-0011 codegen-is-SSOT), never reconstructing `observation.py`'s
pre-existing local `PlatformObservation` value object (that class stays as
this package's own W3 capture-pipeline shape; `capture.py`'s
`run_chatgpt_observation` is untouched by this unit).

Field discipline (this unit's own task instruction, verbatim): the produced
record carries exactly `{tenant_id, run_id, engine_id, observation_id,
raw_object_ref, artifact_hash, citation_refs, captured_at}` — never the raw
response HTML/screenshot inline (`raw_object_ref`/`artifact_hash` come from
`artifact_gateway.RawArtifactRef`, this package's single-gateway boundary,
never computed a second way here).

`observation.captured.v1`'s envelope is built via `saena_domain.events.
EnvelopeFactory.build_tenant_envelope` (task instruction: "via
`saena_domain.events.factory`"), producer=`chatgpt-observer-service`
(`saena_domain.execution.job_kind.profile_for(JobKind.CHATGPT_OBSERVER).
producer_id`, the SAME producer id `JOB_KIND_PROFILES` already fixes for
this job kind — not a second, hand-typed string). `observation.captured.v1`
is one of the 3 CONFIRMED `x-saena-engine-id-required: true` channels
(ADR-0013 observation/citation/experiment family rule); `EnvelopeFactory`
itself enforces `payload.engine_id` presence+value — this module additionally
validates the payload against the GENERATED
`ObservationCapturedV1Payload` model before handing it to the factory
(defense in depth; `saena_domain.events.factory.EVENT_PAYLOAD_MODELS` does
not YET bind `observation.captured.v1` — binding that dict is
`saena_domain.events.factory`'s own exclusive write path, a single-owner
package this unit does not touch — so this module's own pre-validation is
the only place `observation.captured.v1` payloads get generated-model
checking until that binding lands).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from saena_domain.events import EnvelopeFactory
from saena_domain.execution import JobKind, guard_engine_id, profile_for
from saena_schemas.domain.platform_observation_v1 import PlatformObservation as _PlatformObsSchema
from saena_schemas.event.observation_captured_v1 import (
    ObservationCapturedV1Payload as _ObservationCapturedPayloadSchema,
)

from saena_chatgpt_observer.errors import ChatgptObserverError

_OBSERVATION_CAPTURED_EVENT_TYPE = "observation.captured.v1"
_PRODUCER_ID = profile_for(JobKind.CHATGPT_OBSERVER).producer_id


class PlatformObservationRecordError(ChatgptObserverError):
    """The assembled `PlatformObservation` record failed the generated
    `saena_schemas.domain.platform_observation_v1` schema/model."""

    error_code = "saena.validation.platform_observation_record_invalid"


class ObservationCapturedEventError(ChatgptObserverError):
    """The assembled `observation.captured.v1` payload failed the generated
    `ObservationCapturedV1Payload` model, or envelope construction itself
    failed (`saena_domain.events.EnvelopeValidationError`/
    `EngineIdRequiredError`/`EngineNotPermittedError` — all propagate from
    `EnvelopeFactory`, wrapped here only for this package's own consistent
    `ChatgptObserverError` taxonomy)."""

    error_code = "saena.validation.observation_captured_event_invalid"


def build_platform_observation_record(
    *,
    tenant_id: str,
    run_id: str,
    engine_id: str,
    observation_id: str,
    raw_object_ref: str,
    artifact_hash: str,
    citation_refs: tuple[str, ...],
    captured_at: str,
) -> dict[str, Any]:
    """Assemble + validate the formal `PlatformObservation` domain record
    (`saena_schemas.domain.platform_observation_v1`) — the ONLY fields
    named in this unit's own instruction, no additions, no omissions
    (`extra="forbid"` on the generated model itself already refuses any
    stray field, this function does not accept one to forbid).

    `engine_id` is checked TWICE, deliberately: `guard_engine_id` runs
    first (this package's own v1 closed-enum guard, consistent with
    `observation.PlatformObservation.__post_init__`'s existing double-guard
    discipline, task instruction "reject any other engine id" — checked
    BEFORE the generated model even sees the value, so a disallowed
    `engine_id` never reaches pydantic's own enum validation at all); the
    generated model's own `engine_id_1.Schema` enum re-validates it a
    second, independent time as defense in depth.

    Raises `PlatformObservationRecordError` if the assembled dict fails the
    generated model's own validation (e.g. a malformed `raw_object_ref`/
    `artifact_hash` shape, an out-of-bounds `observation_id` length).
    """
    guard_engine_id(engine_id)
    candidate: dict[str, Any] = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "engine_id": engine_id,
        "observation_id": observation_id,
        "raw_object_ref": raw_object_ref,
        "artifact_hash": artifact_hash,
        "citation_refs": list(citation_refs),
        "captured_at": captured_at,
    }
    try:
        validated = _PlatformObsSchema.model_validate(candidate)
    except ValidationError as exc:
        raise PlatformObservationRecordError(
            f"assembled PlatformObservation record failed schema validation: {exc}",
            context={"observation_id": observation_id},
        ) from exc
    return validated.model_dump(mode="json")


def build_observation_captured_envelope(
    *,
    tenant_id: str,
    run_id: str,
    engine_id: str,
    observation_id: str,
    artifact_hash: str,
    idempotency_key: str,
    trace_id: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Build + dual-validate the `observation.captured.v1` tenant-context
    envelope (task instruction: "Emit `observation.captured.v1` (payload
    `{observation_id, artifact_hash}` minimum) via
    `saena_domain.events.factory`; this event family REQUIRES `engine_id`
    in the envelope -> `chatgpt-search`").

    The payload carries exactly `engine_id`/`observation_id`/
    `artifact_hash` — NEVER `raw_object_ref` (raw-content-adjacent) and
    NEVER `tenant_id`/`run_id` (ADR-0024(e)-1, envelope already carries
    those — `EnvelopeFactory` itself would reject a payload that
    re-projects them, this function simply never constructs one that
    tries).
    """
    guard_engine_id(engine_id)
    payload: dict[str, Any] = {
        "engine_id": engine_id,
        "observation_id": observation_id,
        "artifact_hash": artifact_hash,
    }
    try:
        _ObservationCapturedPayloadSchema.model_validate(payload)
    except ValidationError as exc:
        raise ObservationCapturedEventError(
            f"assembled observation.captured.v1 payload failed schema validation: {exc}",
            context={"observation_id": observation_id},
        ) from exc

    return EnvelopeFactory.build_tenant_envelope(
        producer=_PRODUCER_ID,
        event_type=_OBSERVATION_CAPTURED_EVENT_TYPE,
        tenant_id=tenant_id,
        run_id=run_id,
        idempotency_key=idempotency_key,
        payload=payload,
        trace_id=trace_id,
        occurred_at=occurred_at,
    )


__all__ = [
    "ObservationCapturedEventError",
    "PlatformObservationRecordError",
    "build_observation_captured_envelope",
    "build_platform_observation_record",
]
