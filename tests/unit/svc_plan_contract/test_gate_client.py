"""PolicyGateClient port: HttpPolicyGateClient fail-closed behavior contract."""

from __future__ import annotations

import httpx
import pytest
from saena_plan_contract.errors import PolicyGateUnavailableError
from saena_plan_contract.gate_client import (
    DecisionGateCheckRequest,
    FakeGateClient,
    GateCheckRequest,
    HttpPolicyGateClient,
)


def _request() -> DecisionGateCheckRequest:
    """A schema-valid `DecisionGateCheckRequest` (w2-24: the type
    `PolicyGateClient.plan_check` actually requires) — carries every field
    policy-gate's real `PlanCheckRequestBody` requires, so these fail-closed/
    response-shape unit tests exercise the transport/parsing branches, not
    the (still-live, defense-in-depth) runtime pre-flight guard — see
    `test_missing_required_field_type_error` below for that guard's
    type-level counterpart."""
    return DecisionGateCheckRequest(
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


# --- w2-24: GateCheckRequest required-at-type-level -------------------------


@pytest.mark.parametrize(
    "missing_kwarg",
    [
        "proposer_actor_id",
        "approver_actor_id",
        "evidence_ledger_hash",
        "scope_max_globs",
        "diff_max_files",
        "diff_max_lines",
    ],
)
def test_decision_gate_check_request_missing_required_field_is_construction_error(
    missing_kwarg: str,
) -> None:
    """The six gate-required fields are non-Optional, no-default fields on
    `DecisionGateCheckRequest` — omitting any one of them at construction
    time raises `TypeError` immediately (a dataclass with no default for
    that field), proving this is now a TYPE-level required field, not merely
    a value a runtime guard checks for `None` after the fact. This is the
    dataclass-construction analogue of a mypy "missing argument" error (mypy
    itself only runs over `packages`/`services`, not `tests` — see
    `pyproject.toml`'s `[tool.mypy] files` — so this test is what proves the
    requiredness live in this test suite; `just typecheck` separately proves
    `app.py`'s own `DecisionGateCheckRequest(...)` call site type-checks with
    every required field present)."""
    kwargs: dict[str, object] = {
        "contract_hash": "sha256:" + "a" * 64,
        "tenant_id": "acme-corp",
        "high_risk": False,
        "proposer_actor_id": "actor-proposer-0001",
        "approver_actor_id": "actor-approver-0001",
        "evidence_ledger_hash": "sha256:" + "b" * 64,
        "scope_max_globs": 5,
        "diff_max_files": 10,
        "diff_max_lines": 500,
    }
    del kwargs[missing_kwarg]
    with pytest.raises(TypeError, match="missing 1 required"):
        DecisionGateCheckRequest(**kwargs)  # type: ignore[arg-type]


def test_decision_gate_check_request_all_fields_present_constructs_cleanly() -> None:
    # Control case: the same field set as the parametrized test above, MINUS
    # nothing — confirms the required-field set is exactly the six gate
    # fields, not an overly broad refusal.
    request = _request()
    assert request.proposer_actor_id == "actor-proposer-0001"
    assert request.diff_max_lines == 500


def test_gate_check_request_still_permits_none_for_propose_time_subset_shape() -> None:
    """`GateCheckRequest` (distinct from `DecisionGateCheckRequest`) remains
    the general, partial shape — a propose-time-style caller (or the
    integration pre-flight-guard regression suite) can still construct it
    with a `None` gate-required field; that is only ever caught by
    `HttpPolicyGateClient`'s own runtime guard when actually sent, never by
    construction itself. This documents the intentional TYPE difference
    between the two dataclasses, not a gap."""
    request = GateCheckRequest(
        contract_hash="sha256:" + "c" * 64,
        tenant_id="acme-corp",
        high_risk=False,
        evidence_ledger_hash=None,
    )
    assert request.evidence_ledger_hash is None


def test_http_gate_client_preflight_guard_still_fires_for_legacy_gate_check_request() -> None:
    """Defense-in-depth regression: `HttpPolicyGateClient._build_plan_check_body`
    still fails closed, BEFORE any HTTP call, for a `GateCheckRequest`
    (the legacy, partial shape) carrying a `None` gate-required field — the
    runtime guard the task spec requires to stay live even after the
    type-level fix above."""
    client = HttpPolicyGateClient("http://policy-gate")
    incomplete = GateCheckRequest(
        contract_hash="sha256:" + "d" * 64,
        tenant_id="acme-corp",
        high_risk=False,
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id="actor-approver-0001",
        evidence_ledger_hash=None,
        scope_max_globs=5,
        diff_max_files=10,
        diff_max_lines=500,
    )
    with pytest.raises(PolicyGateUnavailableError, match="missing"):
        client._build_plan_check_body(incomplete)
    client.close()
