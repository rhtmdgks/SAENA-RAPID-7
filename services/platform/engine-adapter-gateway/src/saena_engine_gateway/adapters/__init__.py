"""v1/vNext `EngineAdapter` implementations.

Only `ChatGPTSearchAdapter` exists in v1 (CLAUDE.md Engine scope; ADR-0013
closed enum `["chatgpt-search"]`). Google/Gemini adapters are intentionally
absent from this package — ADR-0001's option A keeps their eventual code
units physically separate under `packages/provider-adapters/*`, and no
Google/Gemini adapter may be constructed, registered, or flagged in v1 at
all (enforced by `AdapterRegistry.register` / `FlagRegistry.create`).
"""

from __future__ import annotations

from saena_engine_gateway.adapters.chatgpt_search import ChatGPTSearchAdapter

__all__ = ["ChatGPTSearchAdapter"]
