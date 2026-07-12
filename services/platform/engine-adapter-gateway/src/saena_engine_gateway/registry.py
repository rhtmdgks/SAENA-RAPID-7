"""`EngineAdapter` Protocol and `AdapterRegistry` (ADR-0001 option A).

ADR-0001 confirms adapters are gateway-embedded library units — one Python
object implementing `EngineAdapter` per `packages/provider-adapters/*`
candidate, registered into a single `AdapterRegistry` instance owned by this
gateway. `AdapterRegistry.register` is the enforcement point that makes the
v1 closed engine enum a *construction-time* invariant, not merely a runtime
check: attempting to register `google-generative-search`, `gemini`, or any
other non-`chatgpt-search` value raises `EngineNotPermittedError`
immediately, before the adapter ever becomes resolvable.

v1 gateway scope note: `submit_observation_request` is a boundary-enforcement
stub only. Real observer behaviour (issuing the actual ChatGPT Search
request, parsing citations, etc.) is chatgpt-observer-service's concern and
lands in W4 — see `ChatGPTSearchAdapter`'s docstring.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from saena_schemas.common.engine_id_v1 import EngineId

from saena_engine_gateway.errors import AdapterNotFoundError, EngineNotPermittedError

#: The v1 closed engine enum, read from the generated pydantic artifact that
#: is itself generated from
#: `packages/contracts/json-schema/common/engine-id/v1/engine-id.schema.json`
#: (ADR-0013 §Current decision) — this frozenset is the single runtime source
#: every construction-time guard in this package consults.
PERMITTED_ENGINE_IDS: frozenset[str] = frozenset(item.value for item in EngineId)


@runtime_checkable
class EngineAdapter(Protocol):
    """Structural contract every v1/vNext provider adapter implements.

    A `packages/provider-adapters/*` candidate does not need to inherit from
    this Protocol explicitly (`@runtime_checkable` allows structural/duck
    typing) — it only needs to expose the same shape.
    """

    @property
    def engine_id(self) -> str:
        """The closed-enum engine identifier this adapter serves."""
        ...

    @property
    def capabilities(self) -> frozenset[str]:
        """Declared capability tags for this adapter (e.g.
        `"observation"`, `"citation"`) — stub-shape in v1, consumed by
        future capability-gated routing (W4+)."""
        ...

    def submit_observation_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Boundary-enforcement stub: accept a request payload shape and
        return a stub acknowledgement. Does not perform any real engine
        call — see `ChatGPTSearchAdapter` for the v1 stub implementation
        and its W4 real-implementation note."""
        ...


class AdapterRegistry:
    """Keyed-by-`engine_id` adapter store with construction-time closed-enum
    validation (ADR-0001 "single control point").

    `register()` is the sole mutation entry point. Every call validates
    `adapter.engine_id` against `PERMITTED_ENGINE_IDS` *before* storing
    anything — a rejected registration never partially mutates the
    registry's internal state.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, EngineAdapter] = {}

    def register(self, adapter: EngineAdapter) -> None:
        """Register `adapter`, keyed by `adapter.engine_id`.

        Raises `EngineNotPermittedError` if `adapter.engine_id` is outside
        the v1 closed enum — this is the "registering google/gemini/
        anything-else raises AT REGISTRATION" guarantee. Re-registering the
        same `engine_id` overwrites the previous adapter (last write wins;
        v1 has exactly one enum value so this only matters for tests that
        swap in a fake adapter for the same engine).
        """
        if adapter.engine_id not in PERMITTED_ENGINE_IDS:
            raise EngineNotPermittedError(adapter.engine_id)
        self._adapters[adapter.engine_id] = adapter

    def get(self, engine_id: str) -> EngineAdapter:
        """Return the adapter registered for `engine_id`.

        Raises `EngineNotPermittedError` if `engine_id` itself is outside
        the closed enum (checked first — a non-enum value is never a
        "not found", it is "not permitted"). Raises `AdapterNotFoundError`
        if `engine_id` is enum-valid but nothing is registered for it.
        """
        if engine_id not in PERMITTED_ENGINE_IDS:
            raise EngineNotPermittedError(engine_id)
        try:
            return self._adapters[engine_id]
        except KeyError as exc:
            raise AdapterNotFoundError(engine_id) from exc

    def __contains__(self, engine_id: str) -> bool:
        return engine_id in self._adapters

    def enabled_engine_ids(self) -> tuple[str, ...]:
        """`engine_id`s with a registered adapter, sorted for deterministic
        output (used by `GET /v1/engines`)."""
        return tuple(sorted(self._adapters))

    def _unsafe_insert_for_testing(self, engine_id: str, adapter: EngineAdapter) -> None:
        """Bypass the closed-enum guard to insert a rogue adapter directly.

        **Test-only.** Exists solely so the preflight self-check
        (`GET /v1/preflight`) has something real to detect — the
        regression-suite requirement is "inject rogue adapter via registry
        internals to prove detection" (task spec), which by definition
        requires a path that skips `register()`'s own guard. Production
        code must never call this; the leading underscore plus
        `_for_testing` suffix mark it as such, and it performs no
        validation of any kind.
        """
        self._adapters[engine_id] = adapter
