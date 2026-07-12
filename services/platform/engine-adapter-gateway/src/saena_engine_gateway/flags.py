"""Per-adapter feature flags (ADR-0001 "재승인 단위 = adapter 단위" flag granularity).

ADR-0001's scope-expansion decision #1 aligns re-approval granularity to the
adapter unit — one flag per `packages/provider-adapters/*` candidate, so a
scenario like "only Google AI Overviews gets re-approved" can be represented
without an all-or-nothing Google/Gemini toggle. `FlagRegistry` mirrors
`AdapterRegistry`'s construction-time discipline: a flag can only ever be
created for an `engine_id` inside the v1 closed enum — flags for
`google-ai-overviews`, `gemini`, etc. cannot be created at all, not merely
"created but off".
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_engine_gateway.errors import EngineNotPermittedError
from saena_engine_gateway.registry import PERMITTED_ENGINE_IDS


@dataclass(frozen=True, slots=True)
class AdapterFlag:
    """Immutable feature-flag value object for one adapter unit.

    `flag_key` follows the "adapter unit" convention ADR-0001 mandates —
    by default `f"engine.{engine_id}"`, one flag per adapter, never a
    coarser per-vendor or per-vertical grouping.
    """

    engine_id: str
    enabled: bool

    @property
    def flag_key(self) -> str:
        return f"engine.{self.engine_id}"


class FlagRegistry:
    """Keyed-by-`engine_id` feature-flag store with construction-time
    closed-enum validation, mirroring `AdapterRegistry`."""

    def __init__(self) -> None:
        self._flags: dict[str, AdapterFlag] = {}

    def create(self, engine_id: str, *, enabled: bool) -> AdapterFlag:
        """Create (or replace) the flag for `engine_id`.

        Raises `EngineNotPermittedError` if `engine_id` is outside the v1
        closed enum — a flag for a non-enum engine cannot be created, on or
        off, ever (ADR-0001 + CLAUDE.md Engine scope v1).
        """
        if engine_id not in PERMITTED_ENGINE_IDS:
            raise EngineNotPermittedError(engine_id)
        flag = AdapterFlag(engine_id=engine_id, enabled=enabled)
        self._flags[engine_id] = flag
        return flag

    def is_enabled(self, engine_id: str) -> bool:
        """`True` iff a flag exists for `engine_id` and it is enabled.

        Raises `EngineNotPermittedError` if `engine_id` itself is outside
        the closed enum (checked first, same ordering as
        `AdapterRegistry.get`). An enum-valid `engine_id` with no flag
        created at all resolves to `False` (fail-closed default — absence
        of a flag is never treated as "on").
        """
        if engine_id not in PERMITTED_ENGINE_IDS:
            raise EngineNotPermittedError(engine_id)
        flag = self._flags.get(engine_id)
        return flag is not None and flag.enabled

    def get(self, engine_id: str) -> AdapterFlag | None:
        """Return the `AdapterFlag` for `engine_id`, or `None` if none has
        been created. Raises `EngineNotPermittedError` for a non-enum
        `engine_id`."""
        if engine_id not in PERMITTED_ENGINE_IDS:
            raise EngineNotPermittedError(engine_id)
        return self._flags.get(engine_id)

    def flagged_engine_ids(self) -> tuple[str, ...]:
        """Every `engine_id` that has a flag created (enabled or not),
        sorted for deterministic output. Deliberately bypasses the
        closed-enum guard (unlike `get`/`is_enabled`) so preflight-style
        self-checks (`GET /v1/preflight`) can enumerate raw state — including
        any rogue entry that bypassed `create()` — without the accessor
        itself raising before the scan can run."""
        return tuple(sorted(self._flags))

    def _unsafe_insert_for_testing(self, flag: AdapterFlag) -> None:
        """Bypass the closed-enum guard to insert a rogue flag directly.

        **Test-only** — see `AdapterRegistry._unsafe_insert_for_testing`
        for the identical rationale (preflight rogue-detection regression
        test). Production code must never call this.
        """
        self._flags[flag.engine_id] = flag
