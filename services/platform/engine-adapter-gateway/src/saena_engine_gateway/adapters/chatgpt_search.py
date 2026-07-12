"""`ChatGPTSearchAdapter` — the single v1 `EngineAdapter` (ADR-0001, ADR-0013).

Spec basis: `packages/provider-adapters/chatgpt-search/README.md` ("Primary
v1 provider adapter for ChatGPT Search... CONFIRMED as 1st implementation
target. Code NOT IMPLEMENTED"), CLAUDE.md Engine scope v1.

**v1 gateway scope is boundary enforcement, not observation.** This class
proves the engine-boundary machinery (registry, flags, HTTP surface) works
end-to-end for exactly one real `engine_id`. It does not call ChatGPT
Search, does not parse citations, and does not perform rate-limiting beyond
what the gateway's flag/registry layers already enforce.
`submit_observation_request` is deterministic and side-effect-free: it
echoes back a stub acknowledgement shaped like a future real response, so
callers (and this patch unit's own tests) can assert on a stable contract
now.

**W4 real implementation**: chatgpt-observer-service (Algorithm §6.2) owns
the actual OAI-SearchBot-eligible observation methodology, citation
normalization, and query experiment execution — that logic supersedes this
stub's `submit_observation_request` body. This class's `engine_id` /
`capabilities` shape and the gateway boundary it sits behind are expected to
remain stable across that upgrade; only the method body changes.
"""

from __future__ import annotations

from typing import Any

_ENGINE_ID = "chatgpt-search"

#: Stub capability tags (task spec: "stub capabilities, deterministic").
#: Mirrors the scope list in
#: `packages/provider-adapters/chatgpt-search/README.md` ("OAI-SearchBot
#: eligibility; citation observation; query experiment; visibility
#: measurement") — declared here as capability identifiers a future
#: capability-gated router can consult, not yet backed by real behaviour.
_CAPABILITIES: frozenset[str] = frozenset(
    {
        "oai_searchbot_eligibility",
        "citation_observation",
        "query_experiment",
        "visibility_measurement",
    }
)


class ChatGPTSearchAdapter:
    """The single v1 `EngineAdapter` implementation, for `engine_id ==
    "chatgpt-search"`."""

    @property
    def engine_id(self) -> str:
        return _ENGINE_ID

    @property
    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def submit_observation_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Deterministic stub acknowledgement.

        Does not inspect `request` beyond echoing it back unchanged under
        `"request"` — no real engine call is made (W4 note above). Returns a
        plain dict (not a pydantic model) since no observation-request
        contract has been CONFIRMED yet; the HTTP layer
        (`saena_engine_gateway.app`) is responsible for shaping this into
        the actual `202` response body.
        """
        return {
            "engine_id": self.engine_id,
            "status": "accepted_stub",
            "request": dict(request),
        }
