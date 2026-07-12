"""Policy Gate client PORT — ADR-0003 step (2) "Policy Gate 선행 검증".

`policy-gate-service` (`services/foundation/policy-gate-service`) IS
implemented (its real route: `POST /v1/gate/plan-check`,
`saena_policy_gate.app`/`saena_policy_gate.schemas`). Per this unit's task
spec, services must not import each other — the only legal way to reach
policy-gate is a locally-defined HTTP client PORT (`Protocol` + `httpx`
implementation + an in-process fake for tests), never a direct Python import
of `saena_policy_gate`.

w2-21 (ADR-0003, w2-14 E2E critic finding): `HttpPolicyGateClient` was
originally written against a forward-declared, never-cross-validated shape
(wrong path `/v1/plan-check`, wrong request fields, wrong response key) that
a real policy-gate-service call would 404/422 against. This patch unit
corrects the client to match policy-gate's actual published contract — see
`HttpPolicyGateClient`'s own docstring and `GateCheckRequest`'s docstring
(the latter also documents a real, still-open caller-side gap in `app.py`).

Fail-closed contract (ADR-0003 "policy-gate = fail-closed",
security-model.md "gate 장애 시 승인·실행 불가 — fail-open 금지"): ANY
transport error, timeout, non-200 response (including a 422 from a
malformed/incomplete request body), missing/invalid response field, or
locally-detected inability to build a complete, honest request is treated as
GATE UNAVAILABLE, never as an implicit allow or deny-with-reason. Approval is
IMPOSSIBLE while the gate is unreachable — `HttpPolicyGateClient.plan_check`
raises `saena_plan_contract.errors.PolicyGateUnavailableError` for every one
of those cases; it never returns a `GateDecision` with `allow=True` on
failure, and it never silently swallows the failure to let the caller
proceed. This is the single behavioral invariant this module exists to
enforce — see `app.py`'s decision endpoint for how the exception maps to the
ADR-0003/W2A exit-demo 503.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from saena_plan_contract.errors import PolicyGateUnavailableError

# Conservative, strict timeout (security-model.md fail-closed intent: a slow
# gate must resolve to "unavailable" quickly rather than hang the approval
# path indefinitely). Connect/read/write/pool all share this bound — there is
# no legitimate reason for a policy-gate pre-check call to take longer.
_DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Outcome of a Policy Gate pre-check (ADR-0003 step 2)."""

    allow: bool
    reasons: tuple[str, ...] = ()
    require_two_person: bool = False


@dataclass(frozen=True, slots=True)
class GateCheckRequest:
    """Projection of the plan/decision this port sends to policy-gate-service.

    w2-21 (ADR-0003, w2-14 E2E critic finding): the REAL policy-gate route
    (`POST /v1/gate/plan-check`, `saena_policy_gate.schemas.
    PlanCheckRequestBody`) requires `proposer_actor_id`, `approver_actor_id`,
    `evidence_ledger_hash`, `scope_max_globs`, `diff_max_files`, and
    `diff_max_lines` in addition to `contract_hash`/`approved_scope` — none of
    which the original (pre-w2-21) `GateCheckRequest` shape carried. Those six
    fields are added below as OPTIONAL (`None`-defaulted) so this dataclass's
    existing constructor call in `app.py` (`GateCheckRequest(contract_hash=...,
    tenant_id=..., high_risk=...)`) keeps compiling unmodified — extending
    this port must not itself force an out-of-scope caller-side edit.

    `approver_actor_id` carrying real person-identifying data here is NOT an
    ADR-0024(e)-2 violation: that ADR's PII-exclusion clause is scoped to the
    `plan.contract.approved.v1` PUBLISHED EVENT payload (its own Context (e)
    cites k3s spec §4.1's payload PII/secret-in-EVENTS prohibition) — this
    dataclass is a synchronous point-to-point HTTP pre-check request straight
    to policy-gate-service, not an event payload, and the gate's own
    `PlanCheckRequestBody` (its authoritative, published HTTP contract)
    REQUIRES `approver_actor_id` to run its own RBAC/self-approval-adjacent
    evaluation. No event, topic, or persisted envelope carries this value as
    a result of this dataclass — it never leaves the synchronous gate-check
    call.

    IMPORTANT — CALLER GAP (flagged, not silently patched; out of this unit's
    exclusive-write path, `app.py` is not touched here): `app.py`'s
    `submit_decision` handler does not currently have `evidence_ledger_hash`,
    `scope_max_globs`, `diff_max_files`, or `diff_max_lines` in scope at
    decision time — `_PlanFacts.put` (called from `propose_plan`, which DOES
    see these fields on the validated `ChangeplanActionContract`) never
    persists them, only `proposer_actor_id`/`high_risk`/`patch_unit_ids`/
    `run_id`. Until `app.py` is updated (a coordinated change, see this
    patch unit's final report) to populate these six new fields from stored
    plan facts, `HttpPolicyGateClient.plan_check` cannot fabricate safe
    values for them (defaulting security-relevant H-3 evidence/scope/budget
    data would risk a FALSE allow, the one outcome this module exists to
    prevent — module docstring) — a `None`/empty caller-supplied value for
    any of the four numeric/hash fields is therefore treated as a REQUEST
    THIS CLIENT CANNOT SAFELY SEND, and `plan_check` raises
    `PolicyGateUnavailableError` fail-closed BEFORE any HTTP call is made,
    exactly like a real transport failure — never silently omitted,
    zero-filled, or upgraded to an implicit allow.
    """

    contract_hash: str
    tenant_id: str
    high_risk: bool
    approved_scope: tuple[str, ...] = ()
    patch_unit_ids: tuple[str, ...] = ()
    proposer_actor_id: str | None = None
    approver_actor_id: str | None = None
    evidence_ledger_hash: str | None = None
    scope_max_globs: int | None = None
    diff_max_files: int | None = None
    diff_max_lines: int | None = None
    hypothesis_risks: tuple[str, ...] = ()


@runtime_checkable
class PolicyGateClient(Protocol):
    """Local port — ADR-0003 step (2), "Policy Gate 선행 검증·기록"."""

    def plan_check(self, request: GateCheckRequest) -> GateDecision:
        """Return the gate's decision for `request`.

        MUST raise `saena_plan_contract.errors.PolicyGateUnavailableError`
        (never return a decision) if the gate is unreachable, times out,
        responds with a non-200 status (including a 422 from a malformed
        request body), returns a missing/invalid `decision` field, or (for
        `HttpPolicyGateClient` specifically) `request` itself is missing
        fields the real gate route requires — fail-closed, no exceptions to
        this rule (module docstring).
        """
        ...

    def health(self) -> bool:
        """Return whether the gate currently answers health checks.

        Never raises — a transport failure here is reported as `False`, not
        propagated, since callers use this for informational/readiness
        purposes only (the authoritative fail-closed check is always
        `plan_check`, not `health`).
        """
        ...


class HttpPolicyGateClient:
    """`httpx`-backed `PolicyGateClient` — strict timeout, fail-closed.

    `base_url` should point at `policy-gate-service`'s real HTTP API
    (`services/foundation/policy-gate-service`, `saena_policy_gate.app`).

    w2-21 (ADR-0003, w2-14 E2E critic finding — the DEFECT this patch unit
    closes): this client now posts to the REAL route, `{base_url}/v1/gate/
    plan-check` (previously the non-existent `{base_url}/v1/plan-check`),
    with a request body matching `saena_policy_gate.schemas.
    PlanCheckRequestBody` exactly (previously a GateCheckRequest-shaped body
    the real route would reject with 422 — see `_build_plan_check_body`),
    and parses `saena_policy_gate.schemas.GateDecisionResponse`'s actual
    `{decision: "allow"|"deny", reasons, require_two_person, ...}` shape
    (previously read a non-existent `payload["allow"]` boolean). `health()`
    now also targets the real `{base_url}/v1/health` route (previously
    `{base_url}/health`).
    """

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _build_plan_check_body(self, request: GateCheckRequest) -> dict[str, Any]:
        """Build a `PlanCheckRequestBody`-shaped payload from `request`.

        Fail-closed pre-flight (module docstring — no HTTP call happens for
        a request this client cannot honestly represent): `proposer_actor_id`,
        `approver_actor_id`, `evidence_ledger_hash`, `scope_max_globs`,
        `diff_max_files`, and `diff_max_lines` are REQUIRED by the real gate
        route (`PlanCheckRequestBody`, no defaults) but are OPTIONAL
        (`None`-defaultable) on `GateCheckRequest` (see that dataclass's
        docstring for the caller-gap this reflects — `app.py` does not yet
        populate them). A `None` value for any of them here means this
        client was asked to check a plan without knowing whether it actually
        satisfies H-3 evidence/scope/diff-budget policy — fabricating a
        value (e.g. `0` or `""`) would either fail every real gate call on a
        bogus validation error OR, worse, pass a made-up value the gate
        might accept, producing an allow this client has no basis to trust.
        Neither is acceptable under the fail-closed contract, so this raises
        `PolicyGateUnavailableError` immediately instead.
        """
        missing = [
            name
            for name, value in (
                ("proposer_actor_id", request.proposer_actor_id),
                ("approver_actor_id", request.approver_actor_id),
                ("evidence_ledger_hash", request.evidence_ledger_hash),
                ("scope_max_globs", request.scope_max_globs),
                ("diff_max_files", request.diff_max_files),
                ("diff_max_lines", request.diff_max_lines),
            )
            if value is None
        ]
        if missing:
            raise PolicyGateUnavailableError(
                "GateCheckRequest is missing fields policy-gate's "
                "PlanCheckRequestBody requires — refusing to send a "
                "fabricated/incomplete plan-check request",
                context={"missing_fields": missing, "contract_hash": request.contract_hash},
            )
        return {
            "contract_hash": request.contract_hash,
            "proposer_actor_id": request.proposer_actor_id,
            "approver_actor_id": request.approver_actor_id,
            "evidence_ledger_hash": request.evidence_ledger_hash,
            "approved_scope": list(request.approved_scope),
            "scope_max_globs": request.scope_max_globs,
            "diff_max_files": request.diff_max_files,
            "diff_max_lines": request.diff_max_lines,
            "hypothesis_risks": list(request.hypothesis_risks),
        }

    def plan_check(self, request: GateCheckRequest) -> GateDecision:
        body = self._build_plan_check_body(request)
        try:
            response = self._client.post(
                f"{self._base_url}/v1/gate/plan-check",
                json=body,
                headers={"X-Saena-Tenant-Id": request.tenant_id},
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            # httpx.TimeoutException subclasses (ConnectTimeout, ReadTimeout,
            # WriteTimeout, PoolTimeout) are ALSO httpx.TransportError
            # subclasses — this branch must be checked FIRST (more specific)
            # so a timeout is reported as "timed out" rather than falling
            # into the generic transport-error branch below.
            raise PolicyGateUnavailableError(
                "policy gate timed out", context={"detail": str(exc)}
            ) from exc
        except httpx.TransportError as exc:
            raise PolicyGateUnavailableError(
                "policy gate transport error", context={"detail": str(exc)}
            ) from exc
        if response.status_code != 200:
            # Covers a still-mismatched-body 422 exactly like any other
            # non-200 — never parsed as an implicit allow/deny.
            raise PolicyGateUnavailableError(
                "policy gate returned a non-200 response",
                context={"status_code": response.status_code},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PolicyGateUnavailableError(
                "policy gate response was not valid JSON", context={"detail": str(exc)}
            ) from exc
        try:
            decision = payload["decision"]
            if decision not in ("allow", "deny"):
                raise PolicyGateUnavailableError(
                    "policy gate response had an invalid decision value",
                    context={"decision": decision},
                )
            return GateDecision(
                allow=decision == "allow",
                reasons=tuple(payload.get("reasons", ())),
                require_two_person=bool(payload.get("require_two_person", False)),
            )
        except (KeyError, TypeError) as exc:
            raise PolicyGateUnavailableError(
                "policy gate response missing required fields", context={"detail": str(exc)}
            ) from exc

    def health(self) -> bool:
        try:
            response = self._client.get(f"{self._base_url}/v1/health", timeout=self._timeout)
        except httpx.HTTPError:
            return False
        return response.status_code == 200


@dataclass
class FakeGateClient:
    """In-process test double — `allow` / `deny` / `down` modes.

    - `mode="allow"`: `plan_check` returns `GateDecision(allow=True, ...)`.
    - `mode="deny"`: `plan_check` returns `GateDecision(allow=False, ...)`.
    - `mode="down"`: `plan_check` raises `PolicyGateUnavailableError` — the
      fail-closed demo path (ADR-0003/W2A exit demo).

    `require_two_person` is a settable field so tests can independently
    exercise H-7's own two-person requirement even when the gate itself
    allows (the gate's `require_two_person` signal and
    `saena_domain.policy.evaluate_h7_two_person_approval`'s own `high_risk`
    derivation are two independent inputs `app.py`'s decision endpoint both
    honors — see that module for how they combine).
    """

    mode: str = "allow"
    reasons: tuple[str, ...] = ()
    require_two_person: bool = False
    calls: list[GateCheckRequest] = field(default_factory=list)

    def plan_check(self, request: GateCheckRequest) -> GateDecision:
        self.calls.append(request)
        if self.mode == "down":
            raise PolicyGateUnavailableError(
                "fake gate is down", context={"contract_hash": request.contract_hash}
            )
        if self.mode == "deny":
            return GateDecision(
                allow=False,
                reasons=self.reasons or ("denied by fake gate",),
                require_two_person=self.require_two_person,
            )
        return GateDecision(
            allow=True, reasons=self.reasons, require_two_person=self.require_two_person
        )

    def health(self) -> bool:
        return self.mode != "down"


__all__ = [
    "FakeGateClient",
    "GateCheckRequest",
    "GateDecision",
    "HttpPolicyGateClient",
    "PolicyGateClient",
]
