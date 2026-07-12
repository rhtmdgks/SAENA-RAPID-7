"""Shared W2A approval-flow harness — wires the four merged W2A services'
real FastAPI apps together over their real HTTP surfaces, backed by SHARED
`saena_domain.persistence` in-memory ports so events/decisions/audit entries
actually flow between them within one test process.

Component-wired, not import-wired: this module builds one `TestClient` per
service app. `PlanContractHttpGateAdapter` is the one piece of NEW glue code
this patch unit contributes — a `saena_plan_contract.gate_client.
PolicyGateClient` Protocol implementation that calls the REAL
`policy-gate-service` FastAPI app via a `fastapi.testclient.TestClient`
(NOT a bare `httpx.Client(transport=httpx.ASGITransport(...))`:
`ASGITransport` only implements `handle_async_request`, and plan-contract's
sync route handler — running inside FastAPI's sync-endpoint threadpool —
cannot await it; `TestClient` wraps the same ASGI app behind a sync-callable
portal per request, which IS safe to invoke from that threadpool context,
and is the same transport every other test in this repo already uses to
call a FastAPI app synchronously), translating between
`GateCheckRequest`/`GateDecision` (plan-contract's own port shape) and
`PlanCheckRequestBody`/`GateDecisionResponse` (policy-gate's actual HTTP
shape) — see that class's own docstring for the exact field-shape gap this
closes and why it exists (plan-contract-service's own README documents
`HttpPolicyGateClient`'s request shape as "not yet cross-validated against a
real policy-gate-service implementation"; this adapter is that
cross-validation, done at the ONLY layer this patch unit is allowed to touch:
tests/, not either service's own exclusive-write path).

`AuditChainRelay` is the second piece of glue: `plan-contract-service`'s own
`AuditTrailStore` (`audit_trail.py`) is explicitly documented as an
in-process-only descriptor buffer, NOT a call into `audit-ledger-service`
(services must not import each other, and no HTTP client to that service
exists in plan-contract's own exclusive-write path). Proving "audit chain
contains the decision trail and verify() is green" (W2A exit condition 1)
therefore requires this test harness to relay `AuditTrailRecord`s recorded
during a decision into a REAL `audit-ledger-service` TestClient append call —
exactly the kind of service-to-service event relay a real deployment's future
consumer/outbox-bridge would perform, done here explicitly so the two
services' real HTTP surfaces are both exercised and chained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from saena_audit_ledger import create_app as create_audit_ledger_app
from saena_domain.persistence import (
    InMemoryAuditLedger,
    InMemoryOutbox,
    InMemoryPlanRepository,
)
from saena_domain.persistence.memory import InMemoryDecisionRecordStore
from saena_forge_console.app import create_app as create_forge_console_app
from saena_forge_console.lineage import InMemoryLineagePort
from saena_forge_console.run_store import RunStore
from saena_plan_contract import create_app as create_plan_contract_app
from saena_plan_contract.audit_trail import AuditTrailStore
from saena_plan_contract.gate_client import GateCheckRequest, GateDecision
from saena_policy_gate.app import create_app as create_policy_gate_app
from saena_policy_gate.app import get_decision_store, get_engine
from saena_policy_gate.engine import PolicyEngine
from saena_policy_gate.rules import default_engine_rules

#: `_ChangePlanLike`/H-3 policy fields policy-gate's `PlanCheckRequestBody`
#: requires that plan-contract's own `GateCheckRequest` port shape does not
#: carry (see `PlanContractHttpGateAdapter` docstring) — sourced from the
#: SAME `single-patch-unit.json`/`with-rejected-alternatives.json` fixture
#: shape `plan_contract_factories.py` already uses, kept here as the
#: adapter's own defaults so a caller that only has a `GateCheckRequest` in
#: hand (the plan-contract-service route's own call shape) still produces a
#: schema-valid `PlanCheckRequestBody`.
_DEFAULT_EVIDENCE_LEDGER_HASH = "sha256:" + "a" * 64
_DEFAULT_SCOPE_MAX_GLOBS = 5
_DEFAULT_DIFF_MAX_FILES = 10
_DEFAULT_DIFF_MAX_LINES = 500


class PlanContractHttpGateAdapter:
    """`PolicyGateClient` Protocol implementation backed by a REAL
    `policy-gate-service` HTTP surface (`fastapi.testclient.TestClient`
    over the real ASGI app, no live socket — see module docstring for why
    `TestClient`, not a bare `httpx.Client(transport=ASGITransport(...))`).

    Field-shape gap this adapter closes (the concrete, provable version of
    plan-contract-service README's "not yet cross-validated" open item):
    `saena_plan_contract.gate_client.GateCheckRequest` — the shape
    `plan-contract-service`'s own `submit_decision` route builds — carries
    only `contract_hash`/`tenant_id`/`high_risk`/`approved_scope`/
    `patch_unit_ids`. `saena_policy_gate.schemas.PlanCheckRequestBody` (the
    ACTUAL request body `POST /v1/gate/plan-check` requires) additionally
    requires `proposer_actor_id`, `approver_actor_id`, `evidence_ledger_hash`,
    `scope_max_globs`, `diff_max_files`, `diff_max_lines` — none of which
    `GateCheckRequest` carries. `HttpPolicyGateClient.plan_check` (the
    forward-declared production client in `gate_client.py`) posts the
    `GateCheckRequest` shape directly and would receive a 422 from a REAL
    policy-gate-service today — this integration-level adapter is where that
    gap surfaces and is bridged for THIS harness (see the final report's
    "DEFECT found in a merged unit" section: this is flagged, not silently
    patched into either service's own exclusive-write path).

    The bridge strategy: this adapter carries proposer/approver actor ids and
    H-3 policy facts (evidence_ledger_hash, scope/diff limits) set per-call
    via `configure_request_facts` (populated by the calling test from the
    SAME ChangePlan/ApprovalDecision body it already submitted to
    plan-contract-service), so the request this adapter sends to the real
    policy-gate app is genuinely schema-valid — not a stub.
    """

    def __init__(self, policy_gate_client: TestClient) -> None:
        self._client = policy_gate_client
        # Per-(tenant_id, contract_hash) facts a test populates before
        # submitting a decision — see module docstring. Falls back to the
        # module-level defaults above when a test does not need to exercise
        # a specific evidence/scope shape (e.g. the fail-closed demo, where
        # the gate call never resolves at all).
        self._facts: dict[tuple[str, str], dict[str, Any]] = {}

    def configure_request_facts(
        self,
        *,
        tenant_id: str,
        contract_hash: str,
        proposer_actor_id: str,
        approver_actor_id: str,
        evidence_ledger_hash: str = _DEFAULT_EVIDENCE_LEDGER_HASH,
        approved_scope: tuple[str, ...] | None = None,
        scope_max_globs: int = _DEFAULT_SCOPE_MAX_GLOBS,
        diff_max_files: int = _DEFAULT_DIFF_MAX_FILES,
        diff_max_lines: int = _DEFAULT_DIFF_MAX_LINES,
        hypothesis_risks: tuple[str, ...] = ("low",),
    ) -> None:
        """Configure the H-3/H-7 request facts this adapter sends to the
        real policy-gate app for `(tenant_id, contract_hash)`.

        `approved_scope`, when given, OVERRIDES the scope glob list the
        real `GateCheckRequest.approved_scope` would otherwise carry — used
        by the deny-path test to submit a scope-escaping glob (e.g.
        `"../etc/passwd"`) that `evaluate_h3_evidence_policy` rejects,
        producing a REAL `decision: "deny"` from policy-gate-service's own
        H-3 evaluator (the only decision surface `POST /v1/gate/plan-check`
        actually evaluates — it does NOT consult `PolicyEngine`/
        `AllowRule`s, unlike `POST /v1/gate/authorize`, `service.py`
        `check_plan`'s own `_evaluate` closure calls only
        `evaluate_h3_evidence_policy`).
        """
        self._facts[(tenant_id, contract_hash)] = {
            "proposer_actor_id": proposer_actor_id,
            "approver_actor_id": approver_actor_id,
            "evidence_ledger_hash": evidence_ledger_hash,
            "approved_scope": list(approved_scope) if approved_scope is not None else None,
            "scope_max_globs": scope_max_globs,
            "diff_max_files": diff_max_files,
            "diff_max_lines": diff_max_lines,
            "hypothesis_risks": list(hypothesis_risks),
        }

    def plan_check(self, request: GateCheckRequest) -> GateDecision:
        from saena_plan_contract.errors import PolicyGateUnavailableError

        facts = self._facts.get(
            (request.tenant_id, request.contract_hash),
            {
                "proposer_actor_id": "actor-proposer-0001",
                "approver_actor_id": "actor-approver-0001",
                "evidence_ledger_hash": _DEFAULT_EVIDENCE_LEDGER_HASH,
                "approved_scope": None,
                "scope_max_globs": _DEFAULT_SCOPE_MAX_GLOBS,
                "diff_max_files": _DEFAULT_DIFF_MAX_FILES,
                "diff_max_lines": _DEFAULT_DIFF_MAX_LINES,
                "hypothesis_risks": ["high"] if request.high_risk else ["low"],
            },
        )
        approved_scope = facts["approved_scope"]
        if approved_scope is None:
            approved_scope = list(request.approved_scope) or ["apps/web/docs/*"]
        body: dict[str, Any] = {
            "contract_hash": request.contract_hash,
            "proposer_actor_id": facts["proposer_actor_id"],
            "approver_actor_id": facts["approver_actor_id"],
            "evidence_ledger_hash": facts["evidence_ledger_hash"],
            "approved_scope": approved_scope,
            "scope_max_globs": facts["scope_max_globs"],
            "diff_max_files": facts["diff_max_files"],
            "diff_max_lines": facts["diff_max_lines"],
            "hypothesis_risks": facts["hypothesis_risks"],
            "diff_stats": None,
        }
        try:
            response = self._client.post(
                "/v1/gate/plan-check",
                json=body,
                headers={"X-Saena-Tenant-Id": request.tenant_id},
            )
        except httpx.TimeoutException as exc:
            raise PolicyGateUnavailableError(
                "policy gate timed out", context={"detail": str(exc)}
            ) from exc
        except httpx.TransportError as exc:
            raise PolicyGateUnavailableError(
                "policy gate transport error", context={"detail": str(exc)}
            ) from exc
        if response.status_code != 200:
            raise PolicyGateUnavailableError(
                "policy gate returned a non-200 response",
                context={"status_code": response.status_code},
            )
        payload = response.json()
        return GateDecision(
            allow=payload["decision"] == "allow",
            reasons=tuple(payload.get("reasons", ())),
            require_two_person=bool(payload.get("require_two_person", False)),
        )

    def health(self) -> bool:
        try:
            response = self._client.get("/v1/health")
        except httpx.HTTPError:
            return False
        return response.status_code == 200


class DownPolicyGateClient:
    """`PolicyGateClient` double that ALWAYS raises `PolicyGateUnavailableError`
    — the W2A exit fail-closed demo double (gate process unreachable /
    timed out), distinct from a policy-gate app that is up but DENIES
    (`PlanContractHttpGateAdapter` against a real `mode="deny"`-shaped
    request covers that path instead). Wraps the SAME real policy-gate
    TestClient transport as `PlanContractHttpGateAdapter` would, but a
    broken ASGI app (`_build_broken_policy_gate_app`) stands in for it, so
    this double still exercises a real (failing) HTTP round trip rather than
    raising in Python before any transport call happens.
    """

    def __init__(self, policy_gate_client: TestClient) -> None:
        self._client = policy_gate_client

    def plan_check(self, request: GateCheckRequest) -> GateDecision:
        from saena_plan_contract.errors import PolicyGateUnavailableError

        try:
            response = self._client.post(
                "/v1/gate/plan-check",
                json={
                    "contract_hash": request.contract_hash,
                    "proposer_actor_id": "actor-proposer-0001",
                    "approver_actor_id": "actor-approver-0001",
                    "evidence_ledger_hash": _DEFAULT_EVIDENCE_LEDGER_HASH,
                    "approved_scope": list(request.approved_scope) or ["apps/web/docs/*"],
                    "scope_max_globs": _DEFAULT_SCOPE_MAX_GLOBS,
                    "diff_max_files": _DEFAULT_DIFF_MAX_FILES,
                    "diff_max_lines": _DEFAULT_DIFF_MAX_LINES,
                    "hypothesis_risks": ["high"] if request.high_risk else ["low"],
                    "diff_stats": None,
                },
                headers={"X-Saena-Tenant-Id": request.tenant_id},
            )
        except httpx.HTTPError as exc:
            raise PolicyGateUnavailableError(
                "policy gate transport error (gate down)", context={"detail": str(exc)}
            ) from exc
        except Exception as exc:  # noqa: BLE001 — the broken app raises directly
            # `_build_broken_policy_gate_app`'s route handler raises a bare
            # `RuntimeError` — this client's own `TestClient` is constructed
            # with `raise_server_exceptions=False` (see `_build_broken_
            # policy_gate_client`) specifically so this branch is normally
            # unreachable and the `status_code != 200` branch below fires
            # instead; kept as defense-in-depth in case a future ASGI/
            # Starlette version changes that propagation behavior.
            raise PolicyGateUnavailableError(
                "policy gate raised while handling the request (gate down)",
                context={"detail": type(exc).__name__},
            ) from exc
        # A broken ASGI app (see `_build_broken_policy_gate_app`) always
        # produces a non-200 (its route handler raises before responding) —
        # fail-closed regardless of the specific status.
        raise PolicyGateUnavailableError(
            "policy gate returned a non-200 response (gate down)",
            context={"status_code": response.status_code},
        )

    def health(self) -> bool:
        return False


def _build_broken_policy_gate_app() -> FastAPI:
    """A policy-gate-SHAPED ASGI app whose `/v1/gate/plan-check` route
    always raises — the "gate process is up but every request fails"
    variant of gate-down (as opposed to `DownPolicyGateClient`'s "transport
    itself is unreachable" variant). Both routes through this harness prove
    the SAME fail-closed outcome (503 `gate_unavailable`, no transition) via
    two different real-world failure shapes.
    """
    app = FastAPI(title="broken-policy-gate")

    @app.post("/v1/gate/plan-check")
    async def _broken_plan_check() -> None:
        raise RuntimeError("simulated policy-gate outage")

    @app.get("/v1/health")
    async def _broken_health() -> None:
        raise RuntimeError("simulated policy-gate outage")

    return app


def _build_broken_policy_gate_client(app: FastAPI) -> TestClient:
    """`raise_server_exceptions=False` so a route that raises (see
    `_build_broken_policy_gate_app`) surfaces as an ordinary 500 HTTP
    response through this client, rather than re-raising the underlying
    Python exception into the caller — matching what a REAL unreachable/
    crashing policy-gate process would produce over the wire (a response,
    not an in-process exception), which is exactly the shape
    `DownPolicyGateClient.plan_check`'s non-200 branch is written to expect.
    """
    return TestClient(app, raise_server_exceptions=False)


@dataclass
class AuditChainRelay:
    """Relays `plan-contract-service`'s in-process `AuditTrailRecord`
    descriptors into a REAL `audit-ledger-service` TestClient — see module
    docstring for why this glue is necessary (plan-contract's own
    `AuditTrailStore` is documented as NOT a call into audit-ledger-service).
    """

    audit_client: TestClient
    service_role_header: dict[str, str] = field(
        default_factory=lambda: {"X-Saena-Roles": "service"}
    )

    def relay(
        self,
        *,
        tenant_id: str,
        contract_hash: str,
        action: str,
        recorded_at: str,
        trace_id: str,
        payload: dict[str, Any],
        run_id: str | None = None,
        actor_id: str | None = None,
    ) -> httpx.Response:
        body = {
            "action": action,
            "recorded_at": recorded_at,
            "scope": "tenant",
            "trace_id": trace_id,
            "payload": payload,
            "tenant_id": tenant_id,
            "run_id": run_id,
            "actor_id": actor_id,
        }
        response = self.audit_client.post(
            "/v1/audit/entries",
            json=body,
            headers={**self.service_role_header, "X-Saena-Tenant-Id": tenant_id},
        )
        return response

    def verify(self, *, tenant_id: str) -> httpx.Response:
        return self.audit_client.get(
            "/v1/audit/verify",
            headers={"X-Saena-Roles": "auditor", "X-Saena-Tenant-Id": tenant_id},
        )

    def read_entries(self, *, tenant_id: str) -> httpx.Response:
        return self.audit_client.get(
            "/v1/audit/entries",
            headers={"X-Saena-Roles": "auditor", "X-Saena-Tenant-Id": tenant_id},
        )


@dataclass
class ApprovalFlowHarness:
    """All four W2A service apps, wired over shared in-memory persistence.

    `policy_gate_client`/`gate_adapter` are built from a REAL
    `policy-gate-service` app (`create_policy_gate_app()`) — plan-contract's
    decision endpoint reaches it through `gate_adapter` (a `PolicyGateClient`
    Protocol implementation), never a direct Python import.
    """

    tenant_id: str
    plans: InMemoryPlanRepository
    outbox: InMemoryOutbox
    plan_audit_trail: AuditTrailStore
    ledger: InMemoryAuditLedger
    policy_gate_app: FastAPI
    policy_gate_client: TestClient
    policy_gate_decision_store: InMemoryDecisionRecordStore
    gate_adapter: PlanContractHttpGateAdapter
    plan_contract_app: FastAPI
    plan_contract_client: TestClient
    audit_ledger_app: FastAPI
    audit_ledger_client: TestClient
    audit_relay: AuditChainRelay
    forge_console_app: FastAPI
    forge_console_client: TestClient
    run_store: RunStore
    lineage_port: InMemoryLineagePort

    def close(self) -> None:
        self.policy_gate_client.close()
        self.plan_contract_client.close()
        self.audit_ledger_client.close()
        self.forge_console_client.close()


def build_harness(
    *,
    tenant_id: str,
    gate_engine: PolicyEngine | None = None,
) -> ApprovalFlowHarness:
    """Construct every W2A service app over SHARED in-memory ports, plus a
    real `policy-gate-service` app reachable from plan-contract-service via
    `PlanContractHttpGateAdapter`.

    `tenant_id` is threaded into plan-contract-service's `tenant_env_value`
    (its own in-process pod-env-value parameter, `create_app`'s own
    signature — not an OS environment variable) and forge-console-api's/
    policy-gate-service's `SAENA_TENANT_ID` process env var (those two
    services' tenant-reconciliation middleware reads `os.environ` directly,
    `tenant_middleware.py`/`tenant_reconcile.py`) — a caller building a
    SECOND harness for a different tenant in the SAME process (the
    cross-tenant test) must not do so concurrently with this one still
    reading `os.environ`; `tests/integration/approval_flow/
    test_cross_tenant.py` handles that ordering explicitly (see that
    module's own docstring).
    """
    plans = InMemoryPlanRepository()
    outbox = InMemoryOutbox()
    plan_audit_trail = AuditTrailStore()
    ledger = InMemoryAuditLedger()

    decision_store = InMemoryDecisionRecordStore()
    engine = gate_engine or PolicyEngine(default_engine_rules())
    policy_gate_app = create_policy_gate_app()
    policy_gate_app.dependency_overrides[get_decision_store] = lambda: decision_store
    policy_gate_app.dependency_overrides[get_engine] = lambda: engine
    policy_gate_client = TestClient(policy_gate_app)
    gate_adapter = PlanContractHttpGateAdapter(policy_gate_client)

    plan_contract_app = create_plan_contract_app(
        plans=plans,
        outbox=outbox,
        gate=gate_adapter,
        audit_trail=plan_audit_trail,
        tenant_env_value=tenant_id,
    )
    plan_contract_client = TestClient(plan_contract_app)

    audit_ledger_app = create_audit_ledger_app(ledger)
    audit_ledger_client = TestClient(audit_ledger_app)
    audit_relay = AuditChainRelay(audit_client=audit_ledger_client)

    run_store = RunStore()
    lineage_port = InMemoryLineagePort()
    forge_console_app = create_forge_console_app(run_store=run_store, lineage_port=lineage_port)
    forge_console_client = TestClient(forge_console_app)

    return ApprovalFlowHarness(
        tenant_id=tenant_id,
        plans=plans,
        outbox=outbox,
        plan_audit_trail=plan_audit_trail,
        ledger=ledger,
        policy_gate_app=policy_gate_app,
        policy_gate_client=policy_gate_client,
        policy_gate_decision_store=decision_store,
        gate_adapter=gate_adapter,
        plan_contract_app=plan_contract_app,
        plan_contract_client=plan_contract_client,
        audit_ledger_app=audit_ledger_app,
        audit_ledger_client=audit_ledger_client,
        audit_relay=audit_relay,
        forge_console_app=forge_console_app,
        forge_console_client=forge_console_client,
        run_store=run_store,
        lineage_port=lineage_port,
    )


def build_fail_closed_harness(*, tenant_id: str) -> ApprovalFlowHarness:
    """Variant of `build_harness` whose plan-contract app is wired to
    `DownPolicyGateClient` (backed by `_build_broken_policy_gate_app`) —
    the W2A exit "policy-gate fail-closed 데모" double. Everything else is
    identical to `build_harness` (same shared in-memory ports, real
    audit-ledger/forge-console apps) so the ONLY variable in a fail-closed
    test is gate reachability.
    """
    plans = InMemoryPlanRepository()
    outbox = InMemoryOutbox()
    plan_audit_trail = AuditTrailStore()
    ledger = InMemoryAuditLedger()

    broken_app = _build_broken_policy_gate_app()
    broken_client = _build_broken_policy_gate_client(broken_app)
    down_gate = DownPolicyGateClient(broken_client)

    plan_contract_app = create_plan_contract_app(
        plans=plans,
        outbox=outbox,
        gate=down_gate,
        audit_trail=plan_audit_trail,
        tenant_env_value=tenant_id,
    )
    plan_contract_client = TestClient(plan_contract_app)

    audit_ledger_app = create_audit_ledger_app(ledger)
    audit_ledger_client = TestClient(audit_ledger_app)
    audit_relay = AuditChainRelay(audit_client=audit_ledger_client)

    run_store = RunStore()
    lineage_port = InMemoryLineagePort()
    forge_console_app = create_forge_console_app(run_store=run_store, lineage_port=lineage_port)
    forge_console_client = TestClient(forge_console_app)

    return ApprovalFlowHarness(
        tenant_id=tenant_id,
        plans=plans,
        outbox=outbox,
        plan_audit_trail=plan_audit_trail,
        ledger=ledger,
        policy_gate_app=broken_app,
        policy_gate_client=broken_client,
        policy_gate_decision_store=InMemoryDecisionRecordStore(),
        gate_adapter=down_gate,  # type: ignore[arg-type]
        plan_contract_app=plan_contract_app,
        plan_contract_client=plan_contract_client,
        audit_ledger_app=audit_ledger_app,
        audit_ledger_client=audit_ledger_client,
        audit_relay=audit_relay,
        forge_console_app=forge_console_app,
        forge_console_client=forge_console_client,
        run_store=run_store,
        lineage_port=lineage_port,
    )


__all__ = [
    "ApprovalFlowHarness",
    "AuditChainRelay",
    "DownPolicyGateClient",
    "PlanContractHttpGateAdapter",
    "build_fail_closed_harness",
    "build_harness",
]
