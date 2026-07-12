"""`HttpPolicyGateClient.plan_check` response-parsing edge cases that a real,
schema-conformant `policy-gate-service` app never actually produces (a
malformed JSON body, a `decision` value outside `{"allow","deny"}`, a
timeout) — exercised directly against `httpx.MockTransport` so these
fail-closed branches are proven live, not merely reachable in theory.

Complements `test_fail_closed.py` (transport-error/non-200 shapes) and
`test_old_bug_regression_guard.py` (a real, still-mismatched-body 422).
"""

from __future__ import annotations

import httpx
import pytest
from gate_contract_factories import make_request
from saena_plan_contract.errors import PolicyGateUnavailableError
from saena_plan_contract.gate_client import HttpPolicyGateClient


def test_read_timeout_is_gate_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient(
        "http://policy-gate", client=httpx.Client(transport=transport), timeout=5.0
    )

    with pytest.raises(PolicyGateUnavailableError, match="timed out"):
        client.plan_check(make_request(contract_hash="sha256:" + "1" * 63 + "b"))

    client.close()


def test_malformed_json_response_is_gate_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient(
        "http://policy-gate", client=httpx.Client(transport=transport), timeout=5.0
    )

    with pytest.raises(PolicyGateUnavailableError, match="not valid JSON"):
        client.plan_check(make_request(contract_hash="sha256:" + "2" * 63 + "b"))

    client.close()


def test_missing_decision_key_is_gate_unavailable() -> None:
    """A 200 response body without the `decision` key at all — the OLD bug's
    exact response shape (`{"allow": True, ...}`) would land here too, since
    `payload["decision"]` raises `KeyError` for it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"allow": True, "reasons": []})

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient(
        "http://policy-gate", client=httpx.Client(transport=transport), timeout=5.0
    )

    with pytest.raises(PolicyGateUnavailableError, match="missing required fields"):
        client.plan_check(make_request(contract_hash="sha256:" + "3" * 63 + "b"))

    client.close()


def test_invalid_decision_value_is_gate_unavailable() -> None:
    """A `decision` key present but with a value outside `{"allow","deny"}`
    (e.g. a future/typo'd enum member) is treated as gate-unavailable, never
    coerced into an implicit allow or deny."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"decision": "maybe", "reasons": [], "require_two_person": False},
        )

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient(
        "http://policy-gate", client=httpx.Client(transport=transport), timeout=5.0
    )

    with pytest.raises(PolicyGateUnavailableError, match="invalid decision value"):
        client.plan_check(make_request(contract_hash="sha256:" + "4" * 63 + "b"))

    client.close()


def test_null_decision_value_is_gate_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"decision": None, "reasons": [], "require_two_person": False}
        )

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient(
        "http://policy-gate", client=httpx.Client(transport=transport), timeout=5.0
    )

    with pytest.raises(PolicyGateUnavailableError, match="invalid decision value"):
        client.plan_check(make_request(contract_hash="sha256:" + "5" * 63 + "b"))

    client.close()
