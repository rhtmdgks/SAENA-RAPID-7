"""Tenant identity: immutable slug value object, namespace derivation, and
the `TenantContext` runtime wrapper.

Spec basis: ADR-0014 (docs/decisions/ADR-0014-tenant-propagation.md) —
`tenant_id` format/immutability, `namespace = saena-tenant-<tenant_id>`
derivation, `TenantContext` field list. docs/architecture/tenancy-model.md
(namespace convention, ≤63 chars). Reuses the generated pydantic model
`saena_schemas.context.tenant_context_v1.TenantContext` — this module never
redefines that DTO's fields, it only adds runtime behaviour on top.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from saena_schemas.context.tenant_context_v1 import Status as _SchemaStatus
from saena_schemas.context.tenant_context_v1 import TenantContext as _TenantContextModel

from saena_domain.identity.errors import (
    EngineScopeError,
    InvalidTenantIdError,
    NamespaceDerivationError,
    NamespaceMismatchError,
    TenantSuspendedError,
    TenantTerminatingError,
)

# Verbatim from ADR-0014 "tenant_id 형식" and the generated TenantId RootModel
# (packages/schemas/saena_schemas/context/tenant_context_v1/__init__.py) —
# duplicated here (not imported) because the generated RootModel gives us
# pattern validation but not a place to hang the extra immutability/value-
# object behaviour this module needs; the two must stay byte-for-byte in
# sync, same obligation the schema's own $comment records for its siblings.
TENANT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$")

# ADR-0014:32 — "saena-tenant-<id>" namespace convention, tenancy-model.md
# k3s spec CONFIRMED ≤63 chars.
_NAMESPACE_PREFIX: Final[str] = "saena-tenant-"
_MAX_NAMESPACE_LENGTH: Final[int] = 63

# v1 closed engine scope (CLAUDE.md Engine scope; ADR-0013:58).
_ALLOWED_ENGINE_SCOPE: Final[frozenset[str]] = frozenset({"chatgpt-search"})


@dataclass(frozen=True, slots=True)
class TenantId:
    """Immutable DNS-safe slug identifying a tenant (ADR-0014).

    Value object: once constructed, the wrapped string cannot be reassigned
    (rename is forbidden by ADR-0014 Constraints:62 — issuing a new
    `tenant_id` requires a fresh `TenantId` plus an out-of-band migration
    procedure, never in-place mutation).
    """

    value: str

    def __post_init__(self) -> None:
        if not TENANT_ID_PATTERN.fullmatch(self.value):
            raise InvalidTenantIdError(
                f"tenant_id {self.value!r} does not match ADR-0014 pattern "
                f"{TENANT_ID_PATTERN.pattern!r}",
                context={"tenant_id": self.value, "pattern": TENANT_ID_PATTERN.pattern},
            )

    def __str__(self) -> str:
        return self.value


def derive_namespace(tenant_id: TenantId | str) -> str:
    """Deterministically derive the k3s namespace for a tenant.

    `"saena-tenant-<tenant_id>"` per ADR-0014:32 / tenancy-model.md. Asserts
    the result fits the k3s ≤63-char namespace limit — this is always true
    for a schema-valid `tenant_id` (32-char max + 13-char prefix = 45 ≤ 63)
    but is asserted explicitly rather than assumed, per the ADR's own
    "역산한 상한" (limit derived backwards from the namespace budget) framing.
    """
    tid = tenant_id if isinstance(tenant_id, TenantId) else TenantId(tenant_id)
    namespace = f"{_NAMESPACE_PREFIX}{tid.value}"
    if len(namespace) > _MAX_NAMESPACE_LENGTH:
        raise NamespaceDerivationError(
            f"derived namespace {namespace!r} exceeds {_MAX_NAMESPACE_LENGTH} chars",
            context={
                "tenant_id": tid.value,
                "namespace": namespace,
                "max_length": _MAX_NAMESPACE_LENGTH,
            },
        )
    return namespace


def validate_namespace(context: _TenantContextModel) -> None:
    """Assert `context.namespace` equals the value derived from
    `context.tenant_id` (ADR-0014 Constraints:65 — namespace is a computed
    field, never an independent input).

    JSON Schema can only validate the *shape* of `namespace`
    (`tenant-context.schema.json`'s own `$comment` records this gap and the
    `namespace-mismatch` fixture documents it as a permanent gap this
    function exists to close). Raises `NamespaceMismatchError` on mismatch —
    ADR-0014 calls this "hard error", never a silent correction.
    """
    expected = derive_namespace(context.tenant_id.root)
    actual = context.namespace
    if actual != expected:
        raise NamespaceMismatchError(
            f"TenantContext.namespace {actual!r} does not match namespace "
            f"{expected!r} derived from tenant_id {context.tenant_id.root!r}",
            context={
                "tenant_id": context.tenant_id.root,
                "expected_namespace": expected,
                "actual_namespace": actual,
            },
        )


class TenantContext:
    """Runtime wrapper over the generated `TenantContext` pydantic model.

    Adds three behaviours the generated DTO cannot express on its own:

    1. Namespace/tenant_id cross-field validation (`validate_namespace`) at
       construction time — a mismatched namespace never produces a usable
       `TenantContext` instance.
    2. A status gate: `active` is usable; `suspended`/`terminating` raise on
       construction (ADR-0014 status enum, tenancy-model.md cross-tenant
       isolation intent — a suspended tenant's context should never reach
       business logic that assumes an active tenant).
    3. An `engine_scope` guard (`require_engine`) enforcing CLAUDE.md's v1
       ChatGPT-Search-only operating principle at the tenant level, on top of
       the contract-level closed `engine_id` enum.
    """

    __slots__ = ("_model",)

    def __init__(self, model: _TenantContextModel) -> None:
        validate_namespace(model)
        if model.status is _SchemaStatus.terminating:
            raise TenantTerminatingError(
                f"tenant {model.tenant_id.root!r} is terminating",
                context={"tenant_id": model.tenant_id.root, "status": model.status.value},
            )
        if model.status is _SchemaStatus.suspended:
            raise TenantSuspendedError(
                f"tenant {model.tenant_id.root!r} is suspended",
                context={"tenant_id": model.tenant_id.root, "status": model.status.value},
            )
        self._model = model

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> TenantContext:
        """Construct from a raw (already contract-valid) mapping, e.g. a
        deserialized `tenant-context.schema.json` document."""
        return cls(_TenantContextModel.model_validate(payload))

    @property
    def model(self) -> _TenantContextModel:
        """The underlying generated pydantic model (read-only access)."""
        return self._model

    @property
    def tenant_id(self) -> TenantId:
        return TenantId(self._model.tenant_id.root)

    @property
    def namespace(self) -> str:
        return self._model.namespace

    @property
    def isolation_profile(self) -> str:
        return self._model.isolation_profile.value

    @property
    def status(self) -> str:
        return self._model.status.value

    @property
    def engine_scope(self) -> tuple[str, ...]:
        return tuple(engine.value for engine in self._model.engine_scope)

    def require_engine(self, engine_id: str) -> None:
        """Guard: raise `EngineScopeError` unless `engine_id` is both within
        the v1 closed engine allow-list (`chatgpt-search` only, CLAUDE.md /
        ADR-0013:58) and within this tenant's own `engine_scope`.
        """
        if engine_id not in _ALLOWED_ENGINE_SCOPE:
            raise EngineScopeError(
                f"engine {engine_id!r} is outside the v1 engine scope "
                f"{sorted(_ALLOWED_ENGINE_SCOPE)!r}",
                context={"engine_id": engine_id, "tenant_id": self._model.tenant_id.root},
            )
        if engine_id not in self.engine_scope:
            raise EngineScopeError(
                f"engine {engine_id!r} is outside tenant "
                f"{self._model.tenant_id.root!r}'s engine_scope {self.engine_scope!r}",
                context={
                    "engine_id": engine_id,
                    "tenant_id": self._model.tenant_id.root,
                    "engine_scope": list(self.engine_scope),
                },
            )

    def __repr__(self) -> str:
        return (
            f"TenantContext(tenant_id={self._model.tenant_id.root!r}, "
            f"status={self.status!r}, namespace={self.namespace!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TenantContext):
            return NotImplemented
        return self._model == other._model

    def __hash__(self) -> int:
        return hash(self._model.tenant_id.root)
