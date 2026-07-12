"""Request/response models for this service — derived exclusively from the
generated `saena_schemas` contracts (task instruction 2: "no hand DTOs").

`RunCreateRequest` is `pydantic.create_model`'d directly FROM
`RuncontextLifecycle.model_fields`, excluding the two server-assigned
fields (`run_id` — generated server-side via UUIDv7,
`saena_domain.events.generate_uuid7`; `tenant_id` — resolved from the
reconciled request tenant, ADR-0014, never client-supplied on this route).
This is not a hand-written DTO: every remaining field keeps the exact
`FieldInfo` (type + validators) the codegen pipeline produced for
`RuncontextLifecycle` — if that generated model's field set changes on a
future codegen run, this request model's field set changes with it
automatically, with zero edits to this file required for fields that stay
in the excluded/included sets they are already in.

`RunResponse` is `RuncontextLifecycle` itself, used unchanged as the
response model for both `POST /v1/runs` and `GET /v1/runs/{run_id}` — no
derivation needed since every field of the stored run is exactly what the
generated contract already describes.
"""

from __future__ import annotations

from pydantic import ConfigDict, create_model
from saena_schemas.context.run_context_lifecycle_v1 import RuncontextLifecycle

RunResponse = RuncontextLifecycle

_EXCLUDED_FIELDS = frozenset({"run_id", "tenant_id"})

RunCreateRequest = create_model(  # type: ignore[call-overload]
    "RunCreateRequest",
    __config__=ConfigDict(extra="forbid"),
    **{
        name: (field.annotation, field)
        for name, field in RuncontextLifecycle.model_fields.items()
        if name not in _EXCLUDED_FIELDS
    },
)

__all__ = ["RunCreateRequest", "RunResponse"]
