"""`POST /v1/engines/{engine_id}/requests` — boundary-check ordering.

Order under test (task spec): (1) path `engine_id` closed-enum check FIRST,
(2) feature-flag check, (3) adapter resolution, (4) payload/path `engine_id`
agreement, (5) stub `202` accept.
"""

from __future__ import annotations

import pytest
from conftest import TENANT_HEADERS
from fastapi.testclient import TestClient

# Task spec v1-lock regression suite: every one of these must be rejected at
# both the registry/flag layer (test_registry.py/test_flags.py) AND here at
# the HTTP boundary. "chatgpt" (not the exact enum value) is included to
# prove near-miss values are rejected too. "" is handled separately below
# (see TestEmptyEngineIdPathSegment) since an empty `{engine_id}` path
# segment never reaches this route at all — Starlette's path-param matcher
# treats `//` as no match, producing a framework-level 404 before any
# application code (including the closed-enum guard) runs.
REJECTED_ENGINE_IDS = [
    "google-ai-overviews",
    "google-ai-mode",
    "gemini",
    "google",
    "bard",
    "chatgpt",
]


class TestClosedEnumBoundaryCheckedFirst:
    @pytest.mark.parametrize("rogue_engine_id", REJECTED_ENGINE_IDS)
    def test_non_enum_engine_id_rejected_with_403_policy_denied(
        self, client: TestClient, rogue_engine_id: str
    ) -> None:
        response = client.post(
            f"/v1/engines/{rogue_engine_id}/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 403
        body = response.json()
        assert body["error_code"] == "saena.policy_denied.engine_not_permitted"
        assert "not permitted in v1" in body["detail"]

    @pytest.mark.parametrize("rogue_engine_id", REJECTED_ENGINE_IDS)
    def test_non_enum_engine_id_rejected_even_on_empty_registry(
        self, empty_client: TestClient, rogue_engine_id: str
    ) -> None:
        """Closed-enum rejection happens before adapter/flag lookup, so it
        is identical regardless of registry state — proving the ordering,
        not just the outcome."""
        response = empty_client.post(
            f"/v1/engines/{rogue_engine_id}/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "saena.policy_denied.engine_not_permitted"

    def test_exact_enum_value_is_not_rejected_at_this_layer(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 202


class TestClosedEnumRejectsNearMissVariants:
    """Locks in the no-normalization guarantee at the HTTP boundary,
    mirroring `test_engine_gateway_registry.TestRegisterRejectsNearMissVariants`
    -- a caller cannot bypass the closed enum via case-folding, incidental
    whitespace, or a Unicode homoglyph. Requests are made with the raw
    path segment; `httpx`/starlette's `TestClient` percent-encodes
    whitespace/non-ASCII automatically, so this exercises the exact same
    server-side decoding a real client's request would."""

    @pytest.mark.parametrize(
        "variant_engine_id",
        [
            "ChatGPT-Search",
            "CHATGPT-SEARCH",
            "chatgpt-search ",
            " chatgpt-search",
            "chatgpt-sеarch",  # Cyrillic 'е' (U+0435) homoglyph for Latin 'e'
        ],
        ids=[
            "mixed-case",
            "upper-case",
            "trailing-whitespace",
            "leading-whitespace",
            "cyrillic-e-homoglyph",
        ],
    )
    def test_variant_rejected_with_403_policy_denied(
        self, client: TestClient, variant_engine_id: str
    ) -> None:
        response = client.post(
            f"/v1/engines/{variant_engine_id}/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "saena.policy_denied.engine_not_permitted"


class TestEmptyEngineIdPathSegment:
    """An empty `{engine_id}` path segment (`POST /v1/engines//requests`)
    never reaches `submit_engine_request` at all -- Starlette's router does
    not match `//` against a non-empty-by-default path parameter, so the
    request is rejected at the routing layer with a plain framework 404
    before the application's closed-enum guard (or any other application
    code) ever runs. This is a distinct rejection mechanism from
    `EngineNotPermittedError` (RFC 9457, `saena.policy_denied.*`), but it is
    still a rejection -- the important invariant the task spec's `""` case
    protects is "an empty engine_id can never resolve to a 202 accept",
    which holds here by construction, not merely by this test.
    """

    def test_empty_path_segment_never_reaches_the_route(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines//requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 404
        assert response.status_code != 202

    def test_empty_path_segment_rejected_even_on_empty_registry(
        self, empty_client: TestClient
    ) -> None:
        response = empty_client.post(
            "/v1/engines//requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 404
        assert response.status_code != 202


class TestFeatureFlagCheck:
    def test_flag_off_rejects_with_403_policy_denied(self, flag_off_client: TestClient) -> None:
        response = flag_off_client.post(
            "/v1/engines/chatgpt-search/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 403
        body = response.json()
        assert body["error_code"] == "saena.policy_denied.adapter_disabled"


class TestAdapterResolution:
    def test_flag_on_but_not_registered_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi.testclient import TestClient as _TestClient
        from saena_engine_gateway.app import create_app
        from saena_engine_gateway.flags import FlagRegistry
        from saena_engine_gateway.registry import AdapterRegistry

        monkeypatch.setenv("SAENA_TENANT_ID", "acme-corp")
        flags = FlagRegistry()
        flags.create("chatgpt-search", enabled=True)
        app = create_app(registry=AdapterRegistry(), flags=flags)
        client = _TestClient(app)
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == "saena.not_found.adapter_missing"


class TestPayloadPathEngineIdMismatch:
    def test_mismatched_payload_engine_id_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": "gemini"},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "saena.validation.engine_id_mismatch"

    def test_matching_payload_engine_id_is_accepted(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": "chatgpt-search"},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 202

    def test_omitted_payload_engine_id_is_accepted(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"query": "site:example.com"},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 202


class TestStubAccept:
    def test_202_body_shape(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"query": "site:example.com"},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 202
        body = response.json()
        assert body["engine_id"] == "chatgpt-search"
        assert body["status"] == "accepted"
        assert "request_id" in body and body["request_id"]
        assert body["echo"]["request"] == {"query": "site:example.com"}

    def test_each_request_gets_a_distinct_request_id(self, client: TestClient) -> None:
        first = client.post(
            "/v1/engines/chatgpt-search/requests", json={}, headers=TENANT_HEADERS
        ).json()
        second = client.post(
            "/v1/engines/chatgpt-search/requests", json={}, headers=TENANT_HEADERS
        ).json()
        assert first["request_id"] != second["request_id"]
