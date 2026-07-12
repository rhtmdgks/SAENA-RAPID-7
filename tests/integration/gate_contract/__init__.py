"""w2-21 — real `HttpPolicyGateClient` <-> real `policy-gate-service`.

Closes the inter-service contract defect w2-14's E2E critic found (see
`saena_plan_contract.gate_client` module docstring): the pre-w2-21
`HttpPolicyGateClient` posted to a non-existent path with a request body
policy-gate's REAL `PlanCheckRequestBody` would reject, and parsed a
response key (`allow`) the REAL `GateDecisionResponse` never sends.

These tests wire the actual `HttpPolicyGateClient` (unmodified public
signature) against the actual `saena_policy_gate.app.create_app()` ASGI app.
`HttpPolicyGateClient` issues SYNC `httpx.Client` calls (`.post`/`.get`), and
a bare `httpx.ASGITransport` only implements `handle_async_request` (same
constraint `tests/integration/approval_flow/approval_harness.py`'s own
docstring documents for this repo's other component-wired suite) — so the
`httpx.Client` these tests inject into `HttpPolicyGateClient` is built from
`fastapi.testclient.TestClient(app)`, the same real, sync-callable transport
`TestClient` wraps around the ASGI app, passed straight through
`HttpPolicyGateClient`'s own `client: httpx.Client | None` constructor
parameter unmodified. Route dispatch, pydantic request/response validation,
and JSON (de)serialization are all real — this is not a stub.

A regression back to the old path (`/v1/plan-check`), old request shape
(`GateCheckRequest` fields posted directly), or old response key (`allow`)
would surface here as a 404/422 from the real app or a
`PolicyGateUnavailableError` raised for the WRONG reason — see
`test_old_bug_regression_guard.py`.
"""

from __future__ import annotations
