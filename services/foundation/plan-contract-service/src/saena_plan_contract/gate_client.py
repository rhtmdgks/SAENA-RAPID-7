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

w2-24 (Wave 2 critic follow-up — "GateCheckRequest required-at-type-level"):
w2-21 shipped `GateCheckRequest` with all six policy-gate-required fields
(`proposer_actor_id`, `approver_actor_id`, `evidence_ledger_hash`,
`scope_max_globs`, `diff_max_files`, `diff_max_lines`) `None`-defaulted, and
relied ENTIRELY on `HttpPolicyGateClient._build_plan_check_body`'s runtime
pre-flight guard to fail closed on a missing field. That is correct
defense-in-depth but was the ONLY protection — a caller could construct and
pass an incomplete request and only find out at call time. This patch unit
introduces `DecisionGateCheckRequest`, a DISTINCT, all-fields-required
dataclass for the one call site that actually needs a complete request at
DECISION time (`app.py`'s `submit_decision`, via
`PolicyGateClient.plan_check`) — so a decision-time gate call missing a
required field is now a mypy/construction-time TYPE error, not merely a
runtime deny. `GateCheckRequest` itself is UNCHANGED (still all-Optional
past its three original required fields) and remains the general-purpose,
PARTIAL projection shape: it is still used directly by
`tests/integration/gate_contract` to exercise the runtime pre-flight guard
as its own regression surface (the guard stays live, per this unit's task
spec, as defense-in-depth against any FUTURE caller that builds a request
some other way than through `DecisionGateCheckRequest`), and remains
available for a hypothetical PROPOSE-time gate pre-check that only ever has
a SUBSET of these fields in scope (no `approver_actor_id` exists yet at
propose time — see `DecisionGateCheckRequest`'s own docstring for why that
field specifically cannot be required any earlier than decision time).
`PolicyGateClient.plan_check` (the port `Protocol`), `HttpPolicyGateClient`,
and `FakeGateClient` all now take `DecisionGateCheckRequest` — the one and
only shape `app.py` actually builds and sends today.

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
    """GENERAL, PARTIAL projection of the plan/decision this port can send to
    policy-gate-service — every policy-gate-required field beyond the three
    original ones (`contract_hash`/`tenant_id`/`high_risk`) is OPTIONAL
    (`None`-defaulted) on this shape.

    w2-21 (ADR-0003, w2-14 E2E critic finding): the REAL policy-gate route
    (`POST /v1/gate/plan-check`, `saena_policy_gate.schemas.
    PlanCheckRequestBody`) requires `proposer_actor_id`, `approver_actor_id`,
    `evidence_ledger_hash`, `scope_max_globs`, `diff_max_files`, and
    `diff_max_lines` in addition to `contract_hash`/`approved_scope`. w2-21
    added those six fields here as OPTIONAL and closed the caller-side gap in
    `app.py` (`_PlanFacts` now carries every H-3 fact `submit_decision` needs
    to populate them) — but `plan_check` itself still only had this ALL-
    OPTIONAL shape to type against, so a caller could construct and send an
    incomplete request and find out only at runtime (via
    `HttpPolicyGateClient._build_plan_check_body`'s pre-flight guard).

    w2-24 (Wave 2 critic follow-up): `PolicyGateClient.plan_check` (the port
    itself) now requires `DecisionGateCheckRequest` below, not this class —
    `GateCheckRequest` remains for two purposes only: (1) as the base a
    hypothetical PROPOSE-time gate pre-check would build from (propose time
    genuinely has only a SUBSET of these fields in scope — no
    `approver_actor_id` exists until an `ApprovalDecision` is submitted), and
    (2) as the direct-construction shape `tests/integration/gate_contract`
    uses to exercise `HttpPolicyGateClient`'s runtime pre-flight guard as its
    own regression surface (the guard is kept live as defense-in-depth per
    this unit's task spec, in case a future caller builds a request some
    other way than through `DecisionGateCheckRequest`).

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


@dataclass(frozen=True, slots=True)
class DecisionGateCheckRequest:
    """COMPLETE, decision-time Policy Gate request — every field policy-gate's
    real `PlanCheckRequestBody` requires is a REQUIRED (non-Optional) field
    here, at the TYPE level (w2-24, Wave 2 critic follow-up). This is the
    shape `app.py`'s `submit_decision` handler actually builds (see that
    module: it always has every one of these fields in scope by decision
    time — six from `_PlanFacts`, `approver_actor_id` from the submitted
    `ApprovalDecision` itself) and the ONLY shape `PolicyGateClient.plan_check`
    (the port `Protocol`) now accepts.

    Why `approver_actor_id` is required HERE but stays Optional on the plain
    `GateCheckRequest`: a plan's approver is not known until an
    `ApprovalDecision` is actually submitted — a hypothetical PROPOSE-time
    gate pre-check (there is none wired today; `app.py`'s `propose_plan`
    handler does not call `gate.plan_check` at all) would only ever have the
    OTHER five fields in scope, never this one. Splitting the type this way
    means the five fields that ARE always present by decision time (and,
    not coincidentally, already available at propose time too) do not need
    two different required-ness rules depending on caller — every field
    genuinely required at DECISION time is required here, full stop; a
    lower-information propose-time caller (if one is ever wired) stays on
    the plain, all-Optional `GateCheckRequest` instead of this class.

    The runtime fail-closed pre-flight guard in
    `HttpPolicyGateClient._build_plan_check_body` remains defense-in-depth
    (task spec) even though every field here is already non-Optional at
    construction time — a `str` field can still be constructed from an
    unvalidated caller `""`, so the guard's non-empty/None check is not made
    entirely redundant by this type change, and continuing to enforce it in
    both places costs nothing.
    """

    contract_hash: str
    tenant_id: str
    high_risk: bool
    proposer_actor_id: str
    approver_actor_id: str
    evidence_ledger_hash: str
    scope_max_globs: int
    diff_max_files: int
    diff_max_lines: int
    approved_scope: tuple[str, ...] = ()
    patch_unit_ids: tuple[str, ...] = ()
    hypothesis_risks: tuple[str, ...] = ()


@runtime_checkable
class PolicyGateClient(Protocol):
    """Local port — ADR-0003 step (2), "Policy Gate 선행 검증·기록".

    `plan_check` takes `DecisionGateCheckRequest` (w2-24) — the complete,
    all-fields-required decision-time shape — not the general, partial
    `GateCheckRequest`, so a caller missing a policy-gate-required field
    fails to even CONSTRUCT the request (mypy/type-construction error), not
    merely to pass a runtime pre-flight guard.
    """

    def plan_check(self, request: DecisionGateCheckRequest) -> GateDecision:
        """Return the gate's decision for `request`.

        MUST raise `saena_plan_contract.errors.PolicyGateUnavailableError`
        (never return a decision) if the gate is unreachable, times out,
        responds with a non-200 status (including a 422 from a malformed
        request body), or returns a missing/invalid `decision` field —
        fail-closed, no exceptions to this rule (module docstring).
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

    def _build_plan_check_body(
        self, request: DecisionGateCheckRequest | GateCheckRequest
    ) -> dict[str, Any]:
        """Build a `PlanCheckRequestBody`-shaped payload from `request`.

        Accepts EITHER `DecisionGateCheckRequest` (the type `plan_check`
        itself now requires — every field already non-Optional, w2-24) OR
        the general, partial `GateCheckRequest` (accepted here ONLY so the
        runtime pre-flight guard below stays independently exercisable —
        `tests/integration/gate_contract`'s caller-gap regression suite
        constructs `GateCheckRequest` directly, with a deliberate `None`
        override, to prove this guard is live defense-in-depth, per this
        unit's task spec — see `GateCheckRequest`'s own docstring, item (2)).

        Fail-closed pre-flight (module docstring — no HTTP call happens for
        a request this client cannot honestly represent): `proposer_actor_id`,
        `approver_actor_id`, `evidence_ledger_hash`, `scope_max_globs`,
        `diff_max_files`, and `diff_max_lines` are REQUIRED by the real gate
        route (`PlanCheckRequestBody`, no defaults). For a
        `DecisionGateCheckRequest` these are already non-Optional at the type
        level (w2-24) — this check only fires in practice for a value one of
        Python's own escape hatches smuggled past that (e.g. an explicit
        `# type: ignore` at a call site, or the legacy `GateCheckRequest`
        path above). A `None` value for any of them here means this client
        was asked to check a plan without knowing whether it actually
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
                "gate check request is missing fields policy-gate's "
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

    def plan_check(self, request: DecisionGateCheckRequest) -> GateDecision:
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
    calls: list[DecisionGateCheckRequest] = field(default_factory=list)

    def plan_check(self, request: DecisionGateCheckRequest) -> GateDecision:
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
    "DecisionGateCheckRequest",
    "FakeGateClient",
    "GateCheckRequest",
    "GateDecision",
    "HttpPolicyGateClient",
    "PolicyGateClient",
]
