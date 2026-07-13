"""`JobContext` — mandatory execution identity carried by every Wave 3 job.

Spec basis: `docs/architecture/tenancy-model.md` "Identifier set" table
(`tenant_id`/`workspace_id`/`project_id`/`run_id`/`actor_id` — `site_id` is
that table's 6th entry but is NOT part of `JobContext`; it is a
site-discovery-specific value carried in that job's own event payload, not a
cross-cutting execution identity). ADR-0007 rev.2 ("blanket 파티션 규칙
철회"): the blanket PHYSICAL partitioning rule was withdrawn, but the
LOGICAL `tenant_id` discriminator requirement on every tenant-scoped
record/event was not — `JobContext.tenant_id` is REQUIRED, never optional,
per that surviving rule. ADR-0013 (`trace_id` 32-hex W3C format,
`idempotency_key` at-least-once dedup key) and ADR-0014 (`tenant_id`
immutable DNS-safe slug format, reused verbatim via
`saena_domain.identity.tenant.TenantId` rather than re-implementing the
pattern — see that module's own "byte-for-byte in sync" comment on why the
pattern itself is duplicated at the schema layer but this runtime check
reuses the ONE Python value object instead of a second regex).

All seven fields are REQUIRED (no `Optional`/`None` default) — a Wave 3 job
without a bound tenant/workspace/project/run/trace/idempotency-key/actor is a
construction-time error, never a runtime null-check deep inside job logic.
This mirrors `identity.tenant.TenantContext`/`identity.actor.ActorContext`'s
"validate at construction, not at first use" discipline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from saena_domain.execution.errors import JobContextValidationError
from saena_domain.identity.errors import InvalidTenantIdError
from saena_domain.identity.tenant import TenantId

# common/identifiers/v1#/$defs/{workspace_id,project_id,run_id,actor_id}:
# minLength 1, maxLength 128 (format itself is OPEN per that schema's
# $comment — issuer runtime convention — so this module only enforces the
# length bound the contract DOES fix, not a format it deliberately leaves
# open).
_MAX_OPAQUE_IDENTIFIER_LENGTH = 128

# event-envelope.schema.json #/$defs/commonFields/trace_id: 32 lowercase-hex
# (W3C trace context format).
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _require_non_empty_bounded(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise JobContextValidationError(
            f"{field_name} must be a non-empty string, got {value!r}",
            context={"field": field_name},
        )
    if len(value) > _MAX_OPAQUE_IDENTIFIER_LENGTH:
        raise JobContextValidationError(
            f"{field_name} exceeds {_MAX_OPAQUE_IDENTIFIER_LENGTH} chars "
            f"({len(value)}) — common/identifiers/v1 maxLength",
            context={
                "field": field_name,
                "length": len(value),
                "max_length": _MAX_OPAQUE_IDENTIFIER_LENGTH,
            },
        )


def _require_idempotency_key(value: str) -> None:
    # event-envelope.schema.json #/$defs/commonFields/idempotency_key:
    # minLength 1 only — no maxLength in the contract (format OPEN, callers
    # commonly compose it as "tenant:run:unit"-shaped strings, see
    # saena_domain.events.factory's docstring). This module therefore only
    # enforces non-emptiness, deliberately NOT inventing a length cap the
    # contract does not itself impose.
    if not isinstance(value, str) or not value:
        raise JobContextValidationError(
            f"idempotency_key must be a non-empty string, got {value!r}",
            context={"field": "idempotency_key"},
        )


def _require_trace_id(value: str) -> None:
    if not isinstance(value, str) or not _TRACE_ID_PATTERN.fullmatch(value):
        raise JobContextValidationError(
            f"trace_id {value!r} must be 32 lowercase-hex characters "
            "(W3C trace context format, ADR-0013)",
            context={"field": "trace_id"},
        )


@dataclass(frozen=True, slots=True)
class JobContext:
    """Execution identity every Wave 3 job carries. All fields required."""

    tenant_id: str
    workspace_id: str
    project_id: str
    run_id: str
    trace_id: str
    idempotency_key: str
    actor_id: str

    def __post_init__(self) -> None:
        try:
            TenantId(self.tenant_id)
        except InvalidTenantIdError as exc:
            raise JobContextValidationError(
                str(exc), context={"field": "tenant_id", **exc.context}
            ) from exc
        _require_non_empty_bounded("workspace_id", self.workspace_id)
        _require_non_empty_bounded("project_id", self.project_id)
        _require_non_empty_bounded("run_id", self.run_id)
        _require_non_empty_bounded("actor_id", self.actor_id)
        _require_idempotency_key(self.idempotency_key)
        _require_trace_id(self.trace_id)


__all__ = ["JobContext"]
