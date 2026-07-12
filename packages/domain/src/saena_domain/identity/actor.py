"""Actor identity and session semantics.

Spec basis: `packages/contracts/json-schema/context/actor-context/v1/
actor-context.schema.json` (Security MUST-FIX 2 / plan §1.1 R9 — human actors
require `tenant_id`; contract-catalog.md:20 PII minimization — identity
fields are structurally absent, ledger stores `actor_id` only).

The generated pydantic model
(`saena_schemas.context.actor_context_v1.ActorContext`) does not implement
the schema's `allOf/if/then` conditional (datamodel-code-generator does not
lower that construct into a Python-level check) — this wrapper is where that
conditional is actually enforced at runtime, matching the
`human-without-tenant-id` contract fixture's expected behaviour.
"""

from __future__ import annotations

from saena_schemas.context.actor_context_v1 import ActorContext as _ActorContextModel
from saena_schemas.context.actor_context_v1 import ActorType as _SchemaActorType

from saena_domain.identity.errors import IdentityError


class ActorTenantRequiredError(IdentityError):
    """A human actor was constructed without `tenant_id`.

    Enforces the actor-context schema's `allOf/if/then` conditional
    (Security MUST-FIX 2 / plan §1.1 R9) that the generated model does not
    lower into Python.
    """

    error_code = "saena.identity.actor_tenant_required"


class ActorContext:
    """Runtime wrapper over the generated `ActorContext` pydantic model.

    Idempotency identity (contract-catalog.md:20 "Idempotency key:
    actor_id+session") is `(actor_id, session_id)` — exposed via
    `idempotency_key()`.

    PII boundary: the generated schema already structurally omits
    `display_name`/`email`/`role` (contract-catalog.md:20 "ledger에는
    actor_id만, 신원 매핑 분리 보관"). This wrapper reinforces that boundary at
    the Python level — `repr()`/`__str__` expose `actor_id` only, never
    `session_id` (a session identifier is closer to a bearer-adjacent value
    than a stable identity and is deliberately excluded from the log-safe
    form) — so accidental `logger.info(actor_context)` calls cannot leak
    more than the ledger itself is allowed to store.
    """

    __slots__ = ("_model",)

    def __init__(self, model: _ActorContextModel) -> None:
        if model.actor_type is _SchemaActorType.human and model.tenant_id is None:
            raise ActorTenantRequiredError(
                f"human actor {model.actor_id.root!r} must carry tenant_id "
                "(actor-context.schema.json allOf/if/then, Security MUST-FIX 2)",
                context={"actor_id": model.actor_id.root, "actor_type": model.actor_type.value},
            )
        self._model = model

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> ActorContext:
        """Construct from a raw (already contract-valid) mapping, e.g. a
        deserialized `actor-context.schema.json` document."""
        return cls(_ActorContextModel.model_validate(payload))

    @property
    def model(self) -> _ActorContextModel:
        """The underlying generated pydantic model (read-only access)."""
        return self._model

    @property
    def actor_id(self) -> str:
        return self._model.actor_id.root

    @property
    def actor_type(self) -> str:
        return self._model.actor_type.value

    @property
    def session_id(self) -> str:
        return self._model.session_id

    @property
    def tenant_id(self) -> str | None:
        return self._model.tenant_id.root if self._model.tenant_id is not None else None

    def is_human(self) -> bool:
        return self._model.actor_type is _SchemaActorType.human

    def idempotency_key(self) -> tuple[str, str]:
        """`(actor_id, session_id)` — the composite idempotency identity
        (contract-catalog.md:20)."""
        return (self.actor_id, self.session_id)

    def __repr__(self) -> str:
        # PII boundary: actor_id only, never session_id or tenant_id (both
        # can narrow down to a specific human's activity window even though
        # neither is itself PII in isolation).
        return f"ActorContext(actor_id={self.actor_id!r})"

    def __str__(self) -> str:
        return self.__repr__()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ActorContext):
            return NotImplemented
        return self._model == other._model

    def __hash__(self) -> int:
        return hash(self.idempotency_key())
