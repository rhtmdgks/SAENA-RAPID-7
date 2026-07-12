"""Policy Gate client PORT — ADR-0003 step (2) "Policy Gate 선행 검증".

`policy-gate-service` (`services/foundation/policy-gate-service`) is
**NOT IMPLEMENTED** as of this patch unit (see that service's own README).
Per this unit's task spec, services must not import each other — the only
legal way to reach policy-gate is a locally-defined HTTP client PORT
(`Protocol` + `httpx` implementation + an in-process fake for tests), never a
direct Python import of `saena_policy_gate`.

Fail-closed contract (ADR-0003 "policy-gate = fail-closed",
security-model.md "gate 장애 시 승인·실행 불가 — fail-open 금지"): ANY
transport error, timeout, or non-200 response from the gate is treated as
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
    """Minimal, non-PII projection of the plan/decision sent to the gate.

    Deliberately does NOT carry `approver_actor_id` (ADR-0024(e)-2 — the same
    PII-exclusion principle the `plan.contract.approved.v1` payload follows
    applies to this outbound gate-check request; the gate only needs to know
    WHAT is being approved and its risk shape, not WHO is approving it).
    """

    contract_hash: str
    tenant_id: str
    high_risk: bool
    approved_scope: tuple[str, ...] = ()
    patch_unit_ids: tuple[str, ...] = ()


@runtime_checkable
class PolicyGateClient(Protocol):
    """Local port — ADR-0003 step (2), "Policy Gate 선행 검증·기록"."""

    def plan_check(self, request: GateCheckRequest) -> GateDecision:
        """Return the gate's decision for `request`.

        MUST raise `saena_plan_contract.errors.PolicyGateUnavailableError`
        (never return a decision) if the gate is unreachable, times out, or
        responds with a non-200 status — fail-closed, no exceptions to this
        rule (module docstring).
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

    `base_url` should point at `policy-gate-service`'s (future) HTTP API. No
    endpoint contract for that service exists yet (NOT IMPLEMENTED) — this
    client posts to `{base_url}/v1/plan-check` and `{base_url}/health` as a
    forward-declared shape; the concrete request/response JSON keys below
    (`allow`, `reasons`, `require_two_person`) are this client's own minimal
    expectation, documented here so policy-gate-service's eventual
    implementation has an explicit contract to match.
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

    def plan_check(self, request: GateCheckRequest) -> GateDecision:
        body: dict[str, Any] = {
            "contract_hash": request.contract_hash,
            "tenant_id": request.tenant_id,
            "high_risk": request.high_risk,
            "approved_scope": list(request.approved_scope),
            "patch_unit_ids": list(request.patch_unit_ids),
        }
        try:
            response = self._client.post(
                f"{self._base_url}/v1/plan-check", json=body, timeout=self._timeout
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
            return GateDecision(
                allow=bool(payload["allow"]),
                reasons=tuple(payload.get("reasons", ())),
                require_two_person=bool(payload.get("require_two_person", False)),
            )
        except (KeyError, TypeError) as exc:
            raise PolicyGateUnavailableError(
                "policy gate response missing required fields", context={"detail": str(exc)}
            ) from exc

    def health(self) -> bool:
        try:
            response = self._client.get(f"{self._base_url}/health", timeout=self._timeout)
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
