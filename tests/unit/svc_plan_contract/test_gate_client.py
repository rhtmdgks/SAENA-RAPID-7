"""PolicyGateClient port: HttpPolicyGateClient fail-closed behavior contract."""

from __future__ import annotations

import httpx
import pytest
from saena_plan_contract.errors import PolicyGateUnavailableError
from saena_plan_contract.gate_client import FakeGateClient, GateCheckRequest, HttpPolicyGateClient


def _request() -> GateCheckRequest:
    """A schema-valid `GateCheckRequest` — carries every field policy-gate's
    real `PlanCheckRequestBody` requires (w2-21: `HttpPolicyGateClient` now
    fails closed via its own pre-flight guard, BEFORE any HTTP call, if any
    of these six are `None` — see `gate_client.GateCheckRequest`'s
    docstring), so these fail-closed/response-shape unit tests exercise the
    transport/parsing branches, not the pre-flight guard."""
    return GateCheckRequest(
        contract_hash="sha256:" + "a" * 64,
        tenant_id="acme-corp",
        high_risk=False,
        approved_scope=("apps/web/docs/*",),
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id="actor-approver-0001",
        evidence_ledger_hash="sha256:" + "b" * 64,
        scope_max_globs=5,
        diff_max_files=10,
        diff_max_lines=500,
        hypothesis_risks=("low",),
    )


def test_http_gate_client_transport_error_is_gate_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    with pytest.raises(PolicyGateUnavailableError):
        client.plan_check(_request())


def test_http_gate_client_timeout_is_gate_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    with pytest.raises(PolicyGateUnavailableError, match="timed out"):
        client.plan_check(_request())


def test_http_gate_client_close_closes_owned_client() -> None:
    client = HttpPolicyGateClient("http://policy-gate")
    assert client._owns_client is True
    client.close()
    assert client._client.is_closed


def test_http_gate_client_close_does_not_close_injected_client() -> None:
    injected = httpx.Client()
    client = HttpPolicyGateClient("http://policy-gate", client=injected)
    client.close()
    assert injected.is_closed is False
    injected.close()


def test_http_gate_client_non_200_is_gate_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    with pytest.raises(PolicyGateUnavailableError):
        client.plan_check(_request())


def test_http_gate_client_malformed_json_is_gate_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    with pytest.raises(PolicyGateUnavailableError):
        client.plan_check(_request())


def test_http_gate_client_missing_fields_is_gate_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"reasons": []})

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    with pytest.raises(PolicyGateUnavailableError):
        client.plan_check(_request())


def test_http_gate_client_200_allow_returns_decision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"decision": "allow", "reasons": [], "require_two_person": False}
        )

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    decision = client.plan_check(_request())
    assert decision.allow is True
    assert decision.require_two_person is False


def test_http_gate_client_200_deny_returns_decision_with_reasons() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"decision": "deny", "reasons": ["scope escape"]})

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    decision = client.plan_check(_request())
    assert decision.allow is False
    assert decision.reasons == ("scope escape",)


def test_http_gate_client_health_returns_false_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    assert client.health() is False


def test_http_gate_client_health_true_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient("http://policy-gate", client=httpx.Client(transport=transport))
    assert client.health() is True


def test_fake_gate_client_down_mode_raises_unavailable() -> None:
    gate = FakeGateClient(mode="down")
    with pytest.raises(PolicyGateUnavailableError):
        gate.plan_check(_request())
    assert gate.health() is False


def test_fake_gate_client_records_calls() -> None:
    gate = FakeGateClient(mode="allow")
    gate.plan_check(_request())
    assert len(gate.calls) == 1
    assert gate.calls[0].contract_hash == _request().contract_hash
