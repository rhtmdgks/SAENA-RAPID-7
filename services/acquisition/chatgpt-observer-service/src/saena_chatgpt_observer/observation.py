"""`PlatformObservation` — this service's read-only capture record.

`PlatformObservation` itself is a P1 (Wave 3-4) contract
(`docs/architecture/contract-catalog.md` row 41: "계약은 엔진 중립,
**engine_id 필수**"; ADR-0007 §Current decision: "`PlatformObservation`
계약을 `engine_id` 포함 엔진 중립형으로 정의. chatgpt-observer-service는 그
**첫 구현체**") that has NO `packages/contracts` JSON Schema yet — exactly
like `saena_site_discovery.records.ContentRecordProjection`, this class is
this SERVICE's own domain-internal value object (the first engine
implementation's capture shape), not the formal cross-engine contract
itself; a later patch unit against `packages/contracts` owns formalizing
that contract (ADR-0007's whole point is that a second engine, when it
lands, reuses the SAME contract with zero core rework — this class's field
set is deliberately engine-neutral already, `engine_id` included, in
anticipation of that).

`raw_object_ref` is an OPAQUE reference to the raw captured
screenshot/HTML/response, NEVER the raw content itself
(contract-catalog.md row 41: "raw는 object ref만; customer+ToS,
encrypted") — mirrors `saena_artifact_registry.blobstore.BlobRef` and
`saena_site_discovery.records.ContentRecordProjection.evidence_ref`'s same
discipline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from saena_domain.execution import guard_engine_id

from saena_chatgpt_observer.errors import ChatgptObserverError

_QUERY_TEXT_MAX_LENGTH = 2000
_RAW_OBJECT_REF_MAX_LENGTH = 512
_CITATION_REF_MAX_LENGTH = 512
# ADR-0024(f) common uri-field pattern, reused for the same reason
# `records.ContentRecordProjection` reuses it: keep raw/citation references
# off any query-string-shaped (e.g. presigned-token) path.
_OPAQUE_REF_PATTERN = re.compile(r"^[a-z0-9+.-]+://[^?#]+$")


class ObservationValidationError(ChatgptObserverError):
    """A `PlatformObservation` field failed validation at construction
    time."""

    error_code = "saena.validation.platform_observation_invalid"


def _validate_opaque_ref(*, field_name: str, value: str, max_length: int) -> None:
    if not value:
        raise ObservationValidationError(
            f"{field_name} must be a non-empty string", context={"field": field_name}
        )
    if len(value) > max_length:
        raise ObservationValidationError(
            f"{field_name} exceeds {max_length} chars",
            context={"field": field_name, "length": len(value)},
        )
    if not _OPAQUE_REF_PATTERN.match(value):
        raise ObservationValidationError(
            f"{field_name} {value!r} is not a well-formed opaque reference "
            "(scheme required, '?'/'#' forbidden)",
            context={"field": field_name},
        )


@dataclass(frozen=True, slots=True)
class PlatformObservation:
    """Immutable, frozen ChatGPT Search observation capture (deliverable
    7's "read-only PlatformObservation capture").

    `engine_id` is guarded to the v1 closed enum's sole permitted value
    (`chatgpt-search`) at construction time via
    `saena_domain.execution.guard_engine_id` — constructing this object
    with `engine_id="google-aio"`/`"gemini"`/any other value raises
    `EngineDisallowedError`/`EngineNotPermittedError` (from
    `saena_domain.execution.errors`), never silently accepted (mission
    negative test: "engine_id google/gemini rejected").
    """

    engine_id: str
    tenant_id: str
    run_id: str
    query_text: str
    citation_refs: tuple[str, ...]
    raw_object_ref: str
    observed_at: str

    def __post_init__(self) -> None:
        guard_engine_id(self.engine_id)
        if not self.tenant_id:
            raise ObservationValidationError(
                "tenant_id must be a non-empty string", context={"field": "tenant_id"}
            )
        if not self.run_id:
            raise ObservationValidationError(
                "run_id must be a non-empty string", context={"field": "run_id"}
            )
        if not self.query_text:
            raise ObservationValidationError(
                "query_text must be a non-empty string", context={"field": "query_text"}
            )
        if len(self.query_text) > _QUERY_TEXT_MAX_LENGTH:
            raise ObservationValidationError(
                f"query_text exceeds {_QUERY_TEXT_MAX_LENGTH} chars",
                context={"field": "query_text", "length": len(self.query_text)},
            )
        if not self.observed_at:
            raise ObservationValidationError(
                "observed_at must be a non-empty string", context={"field": "observed_at"}
            )
        # citation_refs MAY legitimately be empty (a query can yield zero
        # citations — that absence is itself a meaningful AEO signal, never
        # treated as a construction error), but any ref present must be a
        # well-formed opaque reference, never a raw citation snippet/URL
        # with a query string.
        for ref in self.citation_refs:
            _validate_opaque_ref(
                field_name="citation_refs[]", value=ref, max_length=_CITATION_REF_MAX_LENGTH
            )
        _validate_opaque_ref(
            field_name="raw_object_ref",
            value=self.raw_object_ref,
            max_length=_RAW_OBJECT_REF_MAX_LENGTH,
        )


__all__ = ["ObservationValidationError", "PlatformObservation"]
